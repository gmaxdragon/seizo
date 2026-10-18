"""Regression: frozen evaluation reuses GL context, keeps paired trials and safety."""
import os
import unittest
import numpy as np
from core.runner import evaluate


class FakePolicy:
    def signature(self):return 'unchanged-ppo-weights'
    def act(self,obs,deterministic=True,rng=None):
        return np.zeros((1,5),dtype=float),None


class CountingWorld:
    worlds=[]
    image_policy=True
    def __init__(self,n=1,seed=0,task='reach',fault_probability=0.,**opts):
        if n!=1:raise ValueError('one environment only')
        self.n=n
        self.task_setting=task
        self.fault_probability=fault_probability
        self.rng=np.random.default_rng(seed)
        self.camera_rng=np.random.default_rng(seed+7933)
        self.scenes=[]
        self.count=0
        self.closed=0
        CountingWorld.worlds.append(self)
    def reset(self):
        self.count=0
        self.scenes.append((self.task_setting,float(self.fault_probability),
                            float(self.rng.random()),float(self.camera_rng.random())))
    def observation(self):
        return np.zeros((1,8),np.float32)
    def step(self,a):
        self.count+=1
        done=self.count>=4
        metric={'success':np.array([False]),'fault':np.array([False]),
                'invalid_physics':np.array([False]),'return':np.array([.1]),
                'steps':np.array([self.count]),'distance':np.array([30.]),
                'object_distance':np.array([50.]),'lift':np.array([0.]),
                'object_angle_error':np.array([0.]),'guard_reason':np.array(['']),
                'failure_reason':np.array(['time_limit' if done else 'progress'])}
        return self.observation(),np.array([0.]),np.array([done]),np.array([False]),metric
    def close(self):self.closed+=1


class FrozenWorldReuseTests(unittest.TestCase):
    def setUp(self):CountingWorld.worlds.clear()
    def test_one_world_not_per_trial(self):
        result=evaluate(FakePolicy(),'reach',n=5,seed=27,world_factory=CountingWorld)
        self.assertEqual(len(CountingWorld.worlds),1)
        self.assertEqual(len(CountingWorld.worlds[0].scenes),5)
        self.assertEqual(CountingWorld.worlds[0].closed,1)
        self.assertEqual(result['trials'],5)
        self.assertFalse(result['weights_updated'])
    def test_policy_vs_baseline_scenarios_are_paired(self):
        evaluate(FakePolicy(),'reach',n=5,seed=27,world_factory=CountingWorld)
        scenes0=list(CountingWorld.worlds[0].scenes)
        evaluate(FakePolicy(),'reach',n=5,seed=27,world_factory=CountingWorld,random_policy=True)
        self.assertEqual(scenes0,CountingWorld.worlds[1].scenes)
    def test_single_shared_world_across_policies_tasks_and_faults(self):
        shared=CountingWorld()
        try:
            evaluate(FakePolicy(),'reach',n=3,seed=29,world_factory=CountingWorld,evaluation_world=shared)
            evaluate(FakePolicy(),'orient',n=3,seed=39,world_factory=CountingWorld,evaluation_world=shared)
            evaluate(FakePolicy(),'reach',n=3,seed=49,world_factory=CountingWorld,
                     evaluation_world=shared,fault_probability=1.)
            self.assertEqual(len(CountingWorld.worlds),1)
            self.assertEqual(shared.closed,0)
            self.assertEqual(len(shared.scenes),9)
            self.assertEqual(shared.scenes[-1][1],1.0)
        finally:shared.close()
        self.assertEqual(shared.closed,1)
    def test_stop_closes_and_does_not_publish_partial_pass(self):
        calls=[0]
        def stop():
            calls[0]+=1
            return calls[0]>6
        with self.assertRaises(InterruptedError):
            evaluate(FakePolicy(),'reach',n=5,seed=27,world_factory=CountingWorld,stop=stop)
        self.assertEqual(CountingWorld.worlds[0].closed,1)
    def test_full_runner_wires_one_shared_context(self):
        from pathlib import Path
        source=(Path(__file__).parents[1]/'core'/'runner.py').read_text()
        self.assertIn('shared_evaluation_world=self.World(',source)
        self.assertIn('evaluation_world=shared_evaluation_world',source)
        self.assertIn('shared_evaluation_world.close()',source)
        self.assertNotIn('mujoco.viewer',source)
    def test_training_frees_gl_context_before_validation(self):
        from pathlib import Path
        src=(Path(__file__).parents[1]/'core'/'runner.py').read_text()
        training=src.split('    def _train(self):',1)[1].split('    def stop(self):',1)[0]
        mid=training.split('if self.agent.steps>=next_eval and not stopped():',1)[1]
        self.assertLess(mid.index('env.close()'),mid.index('val=evaluate('))
        finish=training.split("self.agent.episodes-self.start_episodes>=10:",1)[1]
        self.assertLess(finish.index('env.close()'),finish.index('self.begin_evaluation('))

    @unittest.skipUnless(os.environ.get('SEIZO_TEST_REAL_MUJOCO')=='1','Opt-in true rendered MuJoCo gate')
    def test_actual_rgb_and_guard_with_reused_renderer(self):
        from core.view_policy import Agent
        from core.view_world import ViewWorld
        result=evaluate(Agent(),'reach',n=2,seed=20261017,world_factory=ViewWorld,
                        world_options={'camera_config':{'profile':'fixed'},'view_mode':'two'})
        self.assertEqual(result['trials'],2)
        self.assertEqual(result['observation_mode'],'two_rgb_cameras')
        self.assertFalse(result['weights_updated'])
        self.assertEqual(result['faults'],0)


if __name__=='__main__':
    unittest.main()
