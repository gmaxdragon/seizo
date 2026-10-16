"""Strict no-motion wire protocol. Standard library only; no device drivers.

A proposal describes one SIMULATED policy decision. Acceptance is a receipt,
not execution permission. Physical calibration and execution are unavailable.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
import uuid

SCHEMA = 'seizo-proposal/v1'
INTENT_SCHEMA = 'seizo-task-intent/v1'
POLICY_ID = 'seizo-detailed-view-curriculum-v9'
ACTION_ID = 'seizo-five-controls-sim-delta/v1'
TASKS = ('reach', 'orient', 'push', 'lift', 'place', 'rotate', 'orient_place')
TARGETS = ('red_cube', 'green_cylinder', 'blue_ball')
AXES = ('base', 'shoulder', 'forearm', 'wrist', 'gripper')
SCALES = (3., 3., 3., 7., .16)
UNITS = ('sim_degree', 'sim_degree', 'sim_degree', 'sim_degree', 'opening_fraction')
MAX_BODY = 16000
MAX_FRAME_AGE = 5.
MAX_LIFETIME = 10.
STATES = ('proposed', 'rejected', 'simulated', 'received_by_mock_pi',
          'authorized', 'executed', 'physically_verified')
SHA_RE = re.compile(r'^[0-9a-f]{64}$')

class Rejected(ValueError):
    """A public, non-secret, machine-readable rejection reason."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Rejected(code)


def exact(obj, keys, code='unknown_or_missing_fields'):
    require(type(obj) is dict and set(obj) == set(keys), code)


def number(value, low, high, code='invalid_number'):
    require(type(value) in (int, float) and math.isfinite(value)
            and low <= value <= high, code)
    return float(value)


def integer(value, low, high, code='invalid_integer'):
    require(type(value) is int and low <= value <= high, code)
    return value


def identifier(value):
    require(type(value) is str, 'invalid_id')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise Rejected('invalid_id') from None
    require(str(parsed) == value and parsed.version == 4, 'invalid_id')
    return value


def digest(value):
    require(type(value) is str and SHA_RE.fullmatch(value) is not None, 'invalid_sha256')
    return value


def strict_json(raw):
    require(type(raw) in (bytes, str), 'json_required')
    require(len(raw.encode('utf-8') if type(raw) is str else raw) <= MAX_BODY, 'body_too_large')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        raise Rejected('nonfinite_json')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except Rejected:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise Rejected('malformed_json') from None


def canonical(obj):
    try:
        return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError):
        raise Rejected('invalid_json_value') from None


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def sign(key, raw):
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def parse_intent(raw):
    obj = strict_json(raw)
    require(type(obj) is dict and obj.get('schema') == INTENT_SCHEMA, 'unsupported_intent_schema')
    if obj.get('status') == 'unsupported':
        exact(obj, ('schema', 'status'))
        raise Rejected('unsupported_instruction')
    exact(obj, ('schema', 'status', 'task', 'target'))
    require(obj['status'] == 'supported', 'unsupported_instruction')
    require(type(obj['task']) is str and obj['task'] in TASKS, 'unsupported_task')
    require(type(obj['target']) is str and obj['target'] in TARGETS, 'unknown_target')
    return obj


def action_from_policy(values):
    require(type(values) is list and len(values) == 5, 'five_actions_required')
    a = [number(x, -1., 1., 'invalid_policy_action') for x in values]
    return {'type': 'simulator_policy_delta', 'mapping_id': ACTION_ID,
            'axis_order': list(AXES), 'normalized': a,
            'requested_delta': [x * scale for x, scale in zip(a, SCALES)],
            'delta_units': list(UNITS), 'simulation_step_seconds': .06}


def validate_proposal(p, *, now, session_id, expected):
    exact(p, ('schema', 'proposal_id', 'session_id', 'created_at', 'expires_at',
              'domain', 'intent', 'checkpoint', 'observation', 'calibration',
              'actions', 'evaluation', 'automatic_motion_enabled'))
    require(p['schema'] == SCHEMA, 'unsupported_proposal_schema')
    identifier(p['proposal_id'])
    require(identifier(p['session_id']) == session_id, 'session_replaced_or_restarted')
    require(p['domain'] == 'simulation' and p['automatic_motion_enabled'] is False, 'physical_execution_disabled')
    created = number(p['created_at'], 0, now + .25, 'future_proposal')
    expires = number(p['expires_at'], 0, now + MAX_LIFETIME + .25, 'invalid_expiry')
    require(created <= now < expires and 0 < expires - created <= MAX_LIFETIME, 'expired_proposal')
    parse_intent(canonical(p['intent']))
    cp = p['checkpoint']
    exact(cp, ('model_id', 'sha256', 'fingerprint', 'optimizer_updates', 'episodes'))
    require(cp['model_id'] == POLICY_ID, 'incompatible_model')
    digest(cp['sha256']); digest(cp['fingerprint'])
    integer(cp['optimizer_updates'], 1, 2**53, 'checkpoint_has_no_training')
    integer(cp['episodes'], 0, 2**53)
    require(cp == expected['checkpoint'], 'checkpoint_mismatch')
    cal = p['calibration']
    exact(cal, ('simulation_id', 'contract_sha256', 'physical_id'))
    digest(cal['contract_sha256'])
    require(cal['simulation_id'] == 'estimated-simulation:' + cal['contract_sha256'], 'calibration_identity_mismatch')
    require(cal['physical_id'] is None, 'physical_calibration_unavailable')
    require(cal == expected['calibration'], 'calibration_identity_mismatch')
    obs = p['observation']
    exact(obs, ('id', 'source', 'captured_at', 'previous_captured_at', 'valid',
                'camera_names', 'helpers_masked', 'input_sha256'))
    identifier(obs['id']); digest(obs['input_sha256'])
    require(obs['source'] == 'rendered_simulation' and obs['helpers_masked'] is True, 'wrong_observation_source')
    require(obs['camera_names'] == ['overhead', 'wrist'], 'camera_set_mismatch')
    require(type(obs['valid']) is list and len(obs['valid']) == 2
            and all(v is True for v in obs['valid']), 'camera_unavailable')
    for key in ('captured_at', 'previous_captured_at'):
        require(type(obs[key]) is list and len(obs[key]) == 2, 'camera_timestamp_missing')
        for stamp in obs[key]:
            number(stamp, 0, now + .25, 'future_observation')
            require(0 <= now - stamp <= MAX_FRAME_AGE, 'stale_observation')
    for previous, current in zip(obs['previous_captured_at'], obs['captured_at']):
        require(previous <= current <= created, 'observation_order_invalid')
    require(type(p['actions']) is list and len(p['actions']) == 1, 'one_decision_only')
    a = p['actions'][0]
    exact(a, ('type', 'mapping_id', 'axis_order', 'normalized', 'requested_delta',
              'delta_units', 'simulation_step_seconds'))
    require(type(a['requested_delta']) is list and len(a['requested_delta']) == 5, 'five_actions_required')
    for value, scale in zip(a['requested_delta'], SCALES):
        number(value, -scale, scale, 'invalid_requested_delta')
    derived = action_from_policy(a['normalized'])
    require(a == derived, 'action_mapping_or_units_mismatch')
    require(p['evaluation'] == expected['evaluation'], 'evaluation_mismatch')
    ev = p['evaluation']
    exact(ev, ('task', 'report_sha256', 'contract_sha256', 'demonstrated', 'blockers',
               'trials', 'successes', 'random_successes'))
    require(ev['task'] == p['intent']['task'], 'evaluation_task_mismatch')
    require(ev['demonstrated'] is True and ev['blockers'] == [], 'skill_not_demonstrated')
    digest(ev['report_sha256'])
    require(ev['contract_sha256'] == cal['contract_sha256'], 'stale_evaluation_contract')
    n = integer(ev['trials'], 20, 100, 'insufficient_evaluation')
    k = integer(ev['successes'], 0, n)
    baseline = integer(ev['random_successes'], 0, n)
    require(k / n >= .70 and k > baseline, 'skill_not_demonstrated')
    return p


class ReceiptStore:
    """In-memory mock-Pi session. Nothing is queued, persisted, or executed."""
    def __init__(self, expected, *, key=None, clock=time.time):
        self.key = key or secrets.token_bytes(32)
        self.session_id = str(uuid.uuid4())
        self.expected = strict_json(canonical(expected))
        self.clock = clock
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.seen = set()
        self.receipts = 0

    def stop(self):
        self.stopped.set()  # No AI, model lock, renderer, or network dependency.

    def receive(self, raw, signature):
        require(type(raw) is bytes and len(raw) <= MAX_BODY, 'body_too_large')
        require(type(signature) is str and hmac.compare_digest(sign(self.key, raw), signature), 'authentication_failed')
        p = strict_json(raw)
        with self.lock:
            require(not self.stopped.is_set(), 'stopped')
            require(type(p) is dict, 'proposal_object_required')
            pid = identifier(p.get('proposal_id'))
            require(pid not in self.seen, 'replayed_proposal')
            require(len(self.seen) < 256, 'session_request_limit')
            self.seen.add(pid)  # Failed authenticated requests cannot be retried either.
            validate_proposal(p, now=self.clock(), session_id=self.session_id, expected=self.expected)
            require(not self.stopped.is_set(), 'stopped')
            self.receipts += 1
        return {'schema': 'seizo-proposal-receipt/v1', 'proposal_id': pid,
                'session_id': self.session_id, 'proposal_sha256': sha256(raw),
                'state': 'received_by_mock_pi', 'received': True,
                'automatic_motion_enabled': False, 'authorized': False,
                'executed': False, 'physically_verified': False,
                'physical_blockers': ['physical_calibration_missing', 'hardware_not_commissioned',
                                      'physical_execution_not_implemented']}
