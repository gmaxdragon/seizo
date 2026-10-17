"""Explicit-click, cancellable AI -> saved policy -> mock-Pi proposal flow."""
from __future__ import annotations
import copy
import threading
import time
import uuid
from .proposal_protocol import SCHEMA, Rejected, require, validate_proposal
from .proposal_policy import (runtime_contract, load_saved_policy,
                              evaluation_evidence, infer_saved_decision)
from .proposal_receiver import MockPiTransport

BUSY = ('training', 'stopping', 'evaluating', 'watching')
LEASE_SECONDS = 8.


class ProposalBridge:
    def __init__(self, runner, cloud, render_dispatch=None):
        self.runner, self.cloud = runner, cloud
        self.render_dispatch = render_dispatch
        self.lock = threading.RLock()
        self.thread = None
        self.cancel = threading.Event()
        self.transport = None
        self.deadline = 0.
        self.job_id = None
        self.reason = 'not_started'
        self.result = {'state': 'idle'}

    def snapshot(self):
        with self.lock:
            return {**copy.deepcopy(self.result), 'job_id': self.job_id,
                    'busy': bool(self.thread and self.thread.is_alive()),
                    'transport': 'loopback_mock_pi', 'real_pi_connected': False,
                    'automatic_motion_enabled': False, 'authorized': False,
                    'executed': False, 'physically_verified': False,
                    'simulator_steps_executed': 0, 'weights_updated': False,
                    'physical_blockers': ['physical_calibration_missing',
                        'hardware_not_commissioned', 'physical_execution_not_implemented']}

    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def stop(self, reason='stopped'):
        # Set the event before any bookkeeping. Never wait for cloud inference,
        # renderer, policy loading, network receipt, or the learner's lock.
        self.reason = reason
        self.cancel.set()
        transport = self.transport
        if transport is not None:
            transport.stop()
        with self.lock:
            self.result = {**self.result, 'state': 'rejected', 'blockers': [reason],
                           'receipt': None}
        return {'ok': True, 'state': 'stopped', 'automatic_motion_enabled': False}

    def heartbeat(self, job_id):
        with self.lock:
            require(job_id == self.job_id and self.active(), 'no_active_proposal')
            require(not self.cancel.is_set() and time.monotonic() < self.deadline,
                    'proposal_lease_expired')
            self.deadline = time.monotonic() + LEASE_SECONDS
        return {'ok': True}

    def _check(self):
        require(not self.cancel.is_set(), self.reason)
        if time.monotonic() >= self.deadline:
            self.stop('browser_connection_lost')
            raise Rejected('browser_connection_lost')

    def begin(self, instruction, model):
        require(type(instruction) is str and 1 <= len(instruction.strip()) <= 500,
                'instruction_required_max_500_characters')
        require(type(model) is str, 'invalid_model')
        with self.lock:
            require(not self.active(), 'previous_proposal_still_finishing')
            require(self.runner.status not in BUSY and self.runner.status != 'error', 'stop_and_save_first')
            self.cancel = threading.Event(); self.reason = 'stopped'
            self.job_id = str(uuid.uuid4()); self.deadline = time.monotonic() + LEASE_SECONDS
            self.result = {'state': 'checking_checkpoint', 'blockers': []}
            self.thread = threading.Thread(target=self._work, args=(instruction.strip(), model), daemon=True)
            self.thread.start()
        return {'ok': True, 'job_id': self.job_id, 'automatic_motion_enabled': False}

    def _publish(self, **values):
        self._check()
        with self.lock:
            require(not self.cancel.is_set(), self.reason)
            self.result.update(values)

    def _work(self, instruction, model):
        transport = None
        try:
            self._check()
            with self.runner.lock:
                config = copy.deepcopy(self.runner.camera_config)
                generation = self.runner.generation
                current_fingerprint = self.runner.agent.signature()
            agent, identity = load_saved_policy(self.runner.folder, config)
            require(identity['fingerprint'] == current_fingerprint, 'unsaved_policy_changes')
            contract = runtime_contract(config)
            self._publish(checkpoint=identity, state='interpreting_instruction')
            intent, usage = self.cloud.interpret_task(instruction, model)
            self._check()
            evidence = evaluation_evidence(self.runner.folder, identity, intent['task'], contract)
            self._publish(intent=intent, evaluation=evidence, api=usage, state='reading_saved_policy')
            def read_policy():
                return infer_saved_decision(
                    agent, intent, config, lambda: self.cancel.is_set() or time.monotonic() >= self.deadline)
            # Windows GLFW creates the simulated camera context only on
            # the process main thread. The cloud/API worker remains remote
            # from that context and can still be stopped immediately.
            action, observation, frame, details = (
                self.render_dispatch.call(read_policy,timeout=20)
                if self.render_dispatch is not None else read_policy())
            self._check()
            with self.runner.lock:
                require(self.runner.generation == generation
                        and self.runner.agent.signature() == identity['fingerprint']
                        and self.runner.camera_config == config, 'policy_or_scene_configuration_changed')
            # Check the immutable source bytes again before making a proposal.
            from .proposal_protocol import sha256
            require(sha256((self.runner.folder/'policy.npz').read_bytes()) == identity['sha256'],
                    'saved_checkpoint_changed_during_proposal')
            calibration = {'simulation_id': 'estimated-simulation:' + contract,
                           'contract_sha256': contract, 'physical_id': None}
            expected = {'checkpoint': identity, 'calibration': calibration, 'evaluation': evidence}
            transport = MockPiTransport(expected)
            with self.lock:
                self.transport = transport
            self._check()
            now = time.time()
            proposal = {'schema': SCHEMA, 'proposal_id': str(uuid.uuid4()),
                        'session_id': transport.session_id, 'created_at': now,
                        'expires_at': now + 10., 'domain': 'simulation', 'intent': intent,
                        'checkpoint': identity, 'observation': observation,
                        'calibration': calibration, 'actions': [action], 'evaluation': evidence,
                        'automatic_motion_enabled': False}
            self._publish(state='proposed', proposal=proposal, frame=frame, details=details,
                          blockers=evidence['blockers'])
            validate_proposal(proposal, now=time.time(), session_id=transport.session_id, expected=expected)
            self._check()
            receipt = transport.send(proposal)
            self._publish(state='received_by_mock_pi', receipt=receipt, blockers=[])
        except Rejected as exc:
            with self.lock:
                self.result.update(state='rejected', blockers=[self.reason if self.cancel.is_set() else exc.code])
        except (ValueError, OSError, RuntimeError):
            # No provider body, credential, instruction, or local path is echoed.
            with self.lock:
                self.result.update(state='rejected', blockers=['proposal_dependency_or_provider_error'])
        except Exception:
            with self.lock:
                self.result.update(state='rejected', blockers=['proposal_internal_error'])
        finally:
            if transport is not None:
                transport.close()
            with self.lock:
                self.transport = None
