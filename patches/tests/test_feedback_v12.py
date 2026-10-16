"""Reward causality and falsifiable learning claims. Fixtures are not skill tests."""
import copy,json,tempfile,unittest,importlib.util,threading,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from core.learning_feedback import assess,FeedbackLedger,update_evidence,compare_scores,VERSION
from core.view_policy import Agent

class Rewards(unittest.TestCase):
    def test_unsafe_action_negative_even_with_large_base_reward(self):
        r=assess(reward=3.,progress=1.,guard='table-clearance guard')
        self.assertLess(r['total_reward'],0);self.assertFalse(r['discovery_allowed'])
        self.assertEqual(r['reason'],'unsafe_action')
    def test_fault_not_mislabelled_as_bad_choice(self):
        r=assess(reward=.2,progress=1.,guard='both mounted cameras unavailable')
        self.assertEqual(r['reason'],'sensor_or_physics_fault');self.assertFalse(r['discovery_allowed'])
    def test_dropping_held_object_gets_penalty(self):
        r=assess(reward=.2,progress=.1,was_held=True,held=False,previous_lift=30.)
        self.assertLess(r['total_reward'],0);self.assertIn('dropped_object',r['events'])
    def test_empty_grasp_and_timeout_are_not_success(self):
        r=assess(reward=0.,progress=0.,closing_empty=True,truncated=True)
        self.assertEqual(r['events'],['empty_grasp','time_limit']);self.assertAlmostEqual(r['penalty'],-.35)
    def test_desired_object_contact_is_not_blanket_penalized(self):
        r=assess(reward=.3,progress=.1,held=True)
        self.assertEqual(r['total_reward'],.3);self.assertTrue(r['discovery_allowed'])
    def test_no_novelty_reward_for_regression(self):
        r=assess(reward=-.03,progress=-.02)
        self.assertFalse(r['discovery_allowed']);self.assertEqual(r['penalty'],0.)
    def test_limits_do_not_define_new_geometry(self):
        r=assess(reward=.05,progress=.02,limit=True)
        self.assertLess(r['total_reward'],0);self.assertFalse(r['discovery_allowed'])
    def test_success_retains_original_bonus(self):
        r=assess(reward=5.,progress=.3,success=True)
        self.assertEqual(r['total_reward'],5.);self.assertEqual(r['penalty'],0.)
    def test_invalid_measurements_refused(self):
        for x in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):assess(reward=x,progress=0.)
    def test_inactive_does_not_count_as_new_failure(self):
        f=FeedbackLedger();f.observe([assess(reward=-1.,progress=-1.,active=False)])
        self.assertEqual(f.steps,0)
    def test_bounded_ledger_preserved_by_json(self):
        f=FeedbackLedger();f.observe([assess(reward=-.1,progress=-.1)])
        for i in range(200):f.episode({'episode':i,'task':0,'success':False})
        g=FeedbackLedger(json.loads(json.dumps(f.snapshot())))
        self.assertEqual(g.snapshot(),f.snapshot());self.assertEqual(len(g.episodes),100)

class GradientDirection(unittest.TestCase):
    def test_ppo_negative_feedback_reduces_likelihood_of_that_action(self):
        # Unit causality check on controlled inputs, not camera-task performance.
        a=Agent();x=np.zeros((2,a.obs_size),np.float32)
        z=np.zeros((2,5),np.float32);z[:,0]=[-.6,.6]
        old=a.logprob(z,a.forward(x)[0]);before={k:v.copy() for k,v in a.p.items()};fp=a.signature();u=a.updates
        stats=a.update((x,z,old,np.array([-1.,1.],np.float32),np.zeros(2,np.float32)),epochs=1)
        now=a.logprob(z,a.forward(x)[0])
        self.assertLess(now[0]-now[1],old[0]-old[1])
        proof=update_evidence(a,before,fp,u,2,stats)
        self.assertGreater(proof['actor']['changed_parameters'],0);self.assertTrue(proof['weights_updated'])
        self.assertFalse(proof['skill_improvement_proven'])
    def test_reversed_feedback_reverses_correction(self):
        a=Agent();x=np.zeros((2,a.obs_size),np.float32);z=np.zeros((2,5),np.float32);z[:,0]=[-.6,.6]
        old=a.logprob(z,a.forward(x)[0]);a.update((x,z,old,np.array([1.,-1.],np.float32),np.zeros(2,np.float32)),epochs=1)
        now=a.logprob(z,a.forward(x)[0]);self.assertGreater(now[0]-now[1],old[0]-old[1])

class Claims(unittest.TestCase):
    def row(self,successes,n=20,invalid=0):
        return {'trials':n,'task':'reach','seed':10,'successes':successes,'invalid_physics':invalid,
                'mean_error_mm':50.,'outcomes':[{'success':i<successes} for i in range(n)]}
    def test_counter_or_reward_not_proof(self):
        r=compare_scores(self.row(0),self.row(0),self.row(1),'before_training')
        self.assertEqual(r['state'],'no_success_change_detected');self.assertFalse(r['mastery_claim'])
    def test_one_trial_never_proves_learning(self):
        r=compare_scores(self.row(1,1),self.row(0,1),self.row(0,1),'before_training')
        self.assertEqual(r['state'],'small_sample_not_proof')
    def test_detects_regression_and_improvement_in_synthetic_counts(self):
        for before,after,label in ((0,12,'improved'),(12,0,'regressed')):
            r=compare_scores(self.row(after),self.row(before),self.row(1),'before_training')
            self.assertTrue(r['state'].startswith(label));self.assertFalse(r['physical_validation'])
    def test_unpaired_trials_rejected(self):
        r=self.row(5);r['seed']=1
        with self.assertRaises(ValueError):compare_scores(r,self.row(0),self.row(1),'before_training')

@unittest.skipUnless(importlib.util.find_spec('mujoco'),'MuJoCo tests run in release CI')
class ActualSimulator(unittest.TestCase):
    def test_actual_camera_guard_penalty_reaches_rollout(self):
        from core.view_world import ViewWorld
        from core.ppo import rollout
        w=ViewWorld(seed=66,camera_config={'profile':'fixed'},learning_enabled=True,view_mode='two');a=Agent()
        try:
            # Inject a guard outcome to test reward plumbing, not fake skill.
            def guard(i):w.physics_failures[i]=True;w.guard_reason[i]='table-clearance guard'
            with patch.object(w,'_integrate',side_effect=guard):
                _,reward,term,_,info=w.step([[0,0,0,0,0]])
            self.assertTrue(term[0]);self.assertLess(reward[0],0)
            self.assertEqual(info['discovery_bonus'][0],0)
            self.assertEqual(w.frame()['learning_feedback']['reason'],'unsafe_action')
            self.assertAlmostEqual(reward[0],w.last_feedback[0]['total_reward'],places=5)
        finally:w.close()
    def test_runner_real_update_feedback_and_preservation(self):
        from core.view_runner import ViewRunner
        with tempfile.TemporaryDirectory() as td:
            r=ViewRunner(td);r.save();old=(Path(td)/'policy.npz').read_bytes()
            from feedback_smoke_helpers import train_one_real_batch_and_stop
            train_one_real_batch_and_stop(r)
            self.assertNotEqual(r.status,'error',r.error)
            self.assertEqual((Path(td)/'pre_feedback_v12.npz').read_bytes(),old)
            self.assertGreater(r.feedback.steps,0);self.assertIsNotNone(r.feedback.last_update)
            r2=ViewRunner(td);self.assertEqual(r2.agent.signature(),r.agent.signature())
            self.assertEqual(r2.feedback.snapshot(),r.feedback.snapshot())
    def test_frozen_evaluation_exposes_all_outcomes(self):
        from core.runner import evaluate
        from core.view_world import ViewWorld
        a=Agent();fp=a.signature();rng=copy.deepcopy(a.rng.bit_generator.state)
        row=evaluate(a,'reach',1,seed=9271,world_factory=ViewWorld,
            world_options={'view_mode':'two','camera_config':{'profile':'fixed'}})
        self.assertEqual(len(row['outcomes']),1);self.assertEqual(sum(row['failure_counts'].values()),1)
        self.assertEqual(a.signature(),fp);self.assertEqual(a.rng.bit_generator.state,rng)
        self.assertFalse(row['physical_motion'])

if __name__=='__main__':unittest.main()
