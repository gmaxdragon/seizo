"""Keep the cheaper-early-abort loophole and hidden safety regression closed."""
import unittest
from core.learning_feedback import assess,compare_scores

class TerminalCosts(unittest.TestCase):
    def test_guard_abort_cost_exceeds_full_idle_attempt(self):
        idle=220*(-.015)-.25
        result=assess(reward=3.,progress=1.,guard='table-clearance guard')
        self.assertLess(result['total_reward'],idle)
        self.assertFalse(result['discovery_allowed'])
    def test_object_escape_cost_exceeds_full_idle_attempt(self):
        result=assess(reward=2.,progress=1.,fallen=True)
        self.assertLess(result['total_reward'],220*(-.015)-.25)
    def test_no_success_change_does_not_hide_more_guard_aborts(self):
        row={'trials':3,'task':'reach','seed':23,'successes':0,'invalid_physics':0,
             'mean_error_mm':150.,'outcomes':[{'success':False}]*3}
        after={**row,'invalid_physics':3}
        result=compare_scores(after,row,row,'before_training')
        self.assertEqual(result['state'],'small_sample_not_proof')
        self.assertEqual(result['safety_observation'],'more_guard_aborts_observed')
        self.assertEqual(result['physics_aborts_after'],3)
        self.assertFalse(result['mastery_claim'])
    def test_reward_growth_not_success_improvement(self):
        row={'trials':20,'task':'reach','seed':23,'successes':0,'invalid_physics':0,
             'mean_return':-3.5,'mean_error_mm':150.,'outcomes':[{'success':False}]*20}
        result=compare_scores({**row,'mean_return':-1.5,'invalid_physics':20},row,row,'before_training')
        self.assertEqual(result['state'],'no_success_change_detected')
        self.assertEqual(result['safety_observation'],'more_guard_aborts_observed')

if __name__=='__main__':unittest.main()
