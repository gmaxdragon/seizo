"""Read-only adapter for Seizo's existing v9 PPO and RGB observation pipeline.

No new policy, training, key store, calibration, IK, or controller is invented.
The runtime snapshot is a saved checkpoint, not the mutable training object.
"""
from __future__ import annotations
import io
import importlib.metadata
import json
from pathlib import Path
import time
import uuid
import zipfile
import numpy as np
from .proposal_protocol import (POLICY_ID, SCALES, TASKS, TARGETS, Rejected,
                                action_from_policy, canonical, require, sha256)

CONTRACT_FILES = (
    'core/learning_feedback.py', 'core/world.py', 'core/ppo.py', 'core/view_policy.py', 'core/view_observation.py',
    'core/view_world.py', 'core/view_curriculum.py', 'core/camera_world.py',
    'core/camera_observation.py', 'core/mujoco_world.py', 'core/mjcf.py',
    'core/_arm_template.py', 'core/contact.py', 'core/detailed_scene.py',
    'web/assets/kinematics.json', 'web/assets/camera_parts.json',
    'web/assets/camera_lod.json.gz', 'web/assets/room_wood.png', 'web/assets/room_fabric.png')


def runtime_contract(camera_config):
    root = Path(__file__).resolve().parents[1]
    from . import world
    from .view_observation import CONTRACT, POLICY_ID as actual_id
    require(actual_id == POLICY_ID and tuple(world.DELTA) == SCALES, 'action_mapping_changed')
    require(type(camera_config) is dict, 'camera_configuration_required')
    config = camera_config
    files = {name: sha256((root / name).read_bytes()) for name in CONTRACT_FILES}
    versions = {}
    for name in ('numpy', 'mujoco'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'not-installed'
    return sha256(canonical({'schema': 'seizo-proposal-runtime/v1', 'files': files, 'versions': versions,
                             'observations': CONTRACT, 'camera_config': config,
                             'test_views': ['overhead', 'wrist']}))


def load_saved_policy(folder, camera_config):
    from .view_policy import Agent
    path = Path(folder) / 'policy.npz'
    require(path.is_file(), 'saved_checkpoint_missing')
    require(path.stat().st_size <= 64 * 1024 * 1024, 'checkpoint_too_large')
    raw = path.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            require(sum(x.file_size for x in z.infolist()) <= 96 * 1024 * 1024, 'checkpoint_too_large')
        # Existing loader checks model, observation dimensions, all parameter and
        # optimizer shapes, finite weights, and the neural fingerprint.
        agent, extra = Agent.load(io.BytesIO(raw))
    except Rejected:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        raise Rejected('saved_checkpoint_incompatible_or_corrupt') from None
    require(agent.updates > 0, 'checkpoint_has_no_training')
    require(canonical(extra.get('camera_config', {})) == canonical(camera_config),
            'checkpoint_camera_configuration_mismatch')
    identity = {'model_id': agent.model_id, 'sha256': sha256(raw),
                'fingerprint': agent.signature(), 'optimizer_updates': agent.updates,
                'episodes': agent.episodes}
    return agent, identity


def evaluation_evidence(folder, identity, task, contract):
    """Existing full evaluation, not episode totals or cloud self-confidence."""
    evidence = {'task': task, 'report_sha256': None, 'contract_sha256': contract,
                'demonstrated': False, 'blockers': [], 'trials': 0,
                'successes': 0, 'random_successes': 0}
    path = Path(folder) / 'evaluation.json'
    if not path.is_file():
        evidence['blockers'] = ['frozen_evaluation_missing']
        return evidence
    try:
        require(path.stat().st_size <= 1000000, 'evaluation_too_large')
        raw = path.read_bytes(); r = json.loads(raw)
        evidence['report_sha256'] = sha256(raw)
        require(r.get('model_id') == identity['model_id']
                and r.get('policy_fingerprint') == identity['fingerprint'], 'evaluation_checkpoint_mismatch')
        require(r.get('proposal_contract_sha256') == contract, 'evaluation_contract_missing_or_stale')
        require(r.get('fingerprint_unchanged') is True and r.get('weights_updated') is False
                and r.get('physical_motion') is False, 'invalid_frozen_evaluation')
        rows = [x for x in r['by_task'] if x['current']['task'] == task]
        require(len(rows) == 1, 'requested_task_not_evaluated')
        current, random = rows[0]['current'], rows[0]['random_actions']
        n, k, b = current['trials'], current['successes'], random['successes']
        require(all(type(x) is int for x in (n, k, b)) and 1 <= n <= 100
                and 0 <= k <= n and 0 <= b <= n, 'invalid_evaluation_counts')
        evidence.update(trials=n, successes=k, random_successes=b)
        require(random['trials'] == n and random['task'] == task
                and random['seed'] == current['seed'], 'unpaired_random_baseline')
        for row in (current, random):
            require(row.get('weights_updated') is False and row.get('physical_motion') is False
                    and row.get('sensor_condition') == 'two_mounted_cameras', 'evaluation_wrong_camera_condition')
            require(row.get('invalid_physics') == 0 and row.get('faults') == 0, 'evaluation_contains_faults')
        require(n >= 20, 'evaluation_needs_at_least_20_trials')
        require(k / n >= .70 and k > b, 'requested_skill_not_demonstrated')
        evidence['demonstrated'] = True
    except Rejected as exc:
        evidence['blockers'] = [exc.code]
    except (OSError, ValueError, KeyError, TypeError):
        evidence['blockers'] = ['evaluation_unreadable']
    return evidence


def infer_saved_decision(agent, intent, camera_config, stopped):
    """One decision, from newly rendered two-camera input. No physical I/O.

Only initial scene selection changes here. It chooses the requested named
object BEFORE inference, never searches for an action or a successful outcome.
The task's destination/orientation remains the existing simulator's goal.
"""
    from .view_world import ViewWorld
    require(intent['task'] in TASKS and intent['target'] in TARGETS, 'unsupported_instruction')
    target = TARGETS.index(intent['target'])
    require(not stopped(), 'stopped')
    world = ViewWorld(n=1, seed=290117, task=intent['task'], camera_config=camera_config,
                      view_mode='two', learning_enabled=False)
    try:
        # Reset only; never use motion/IK to create a successful example.
        for attempt in range(32):
            require(not stopped(), 'stopped')
            if int(world.target_obj[0]) == target:
                break
            world.reset()
        else:
            raise Rejected('requested_simulation_target_unavailable')
        before = time.time()
        world._cached = [None]  # Force fresh images, not an old UI preview.
        obs = world.observation()
        require(not stopped(), 'stopped')
        require(world._available[0, :2].all() and not world._available[0, 2:].any(), 'camera_unavailable')
        require(not world.physics_failures[0] and not world.guard_reason[0], 'invalid_simulation_scene')
        signature = agent.signature()
        action = agent.act(obs, deterministic=True)[0][0].tolist()
        require(signature == agent.signature(), 'inference_changed_checkpoint')
        require(not stopped(), 'stopped')
        frame = world.frame()
        observation = {'id': str(uuid.uuid4()), 'source': 'rendered_simulation',
                       # Conservative render-start time, never postdated cached frames.
                       'captured_at': [before, before], 'previous_captured_at': [before, before],
                       'valid': [True, True], 'camera_names': ['overhead', 'wrist'],
                       'helpers_masked': True, 'input_sha256': sha256(obs.tobytes())}
        return action_from_policy(action), observation, frame, {
            'scene_seed': 290117, 'scene_resets': attempt,
            'goal_scope': 'existing_simulator_goal_only',
            'simulator_steps_executed': 0, 'weights_updated': False}
    finally:
        world.close()
