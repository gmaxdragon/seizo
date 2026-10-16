"""Short lifecycle test using real pixels/rewards/PPO, not a task-mastery test.

The initial two-full-episode smoke exceeded its 100-second CI budget. Exercise
one actual eight-transition update followed by STOP/save instead. Production
rollout length and episode limits are not changed by this test helper.
"""
from unittest.mock import patch
from core.ppo import rollout


def train_one_real_batch_and_stop(runner):
    original_update=runner.agent.update
    def short_rollout(agent,world,length,**kwargs):
        return rollout(agent,world,min(8,length),**kwargs)
    def update_then_stop(*args,**kwargs):
        result=original_update(*args,**kwargs)
        runner.stop_event.set()
        return result
    with patch('core.runner.rollout',side_effect=short_rollout), \
         patch.object(runner.agent,'update',side_effect=update_then_stop):
        runner.start({'task':'reach','episodes':2,'compute':'fast'})
        runner.thread.join(60.)
        if runner.thread.is_alive():
            runner.stop_event.set();runner.thread.join(25.)
            raise AssertionError('Eight real transitions/update/STOP did not finish within test budget')
    if runner.status=='error':raise AssertionError(runner.error)
    evidence=runner.feedback.last_update
    assert runner.feedback.steps>0 and evidence is not None
    assert evidence['samples']>1 and evidence['weights_updated']
    assert evidence['actor']['changed_parameters']>0
    assert runner.save_verified
    return evidence
