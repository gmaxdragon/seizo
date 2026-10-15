"""End-to-end: actual MuJoCo backend, policy playback and PPO weight updates."""
from __future__ import annotations
import os,tempfile,unittest,time
from pathlib import Path
import numpy as np

try:import mujoco
except ImportError:mujoco=None


@unittest.skipIf(mujoco is None,'Requires real MuJoCo; GitHub CI installs it')
class TestIntegration(unittest.TestCase):
    def test_runner_backend_and_saved_policy_trial(self):
        os.environ['SEIZO_PHYSICS_ENGINE']='mujoco'
        from core.runner import Runner,World,MODEL_ID
        from core.mjcf import MODEL_VERSION
        self.assertEqual(MODEL_ID,MODEL_VERSION)
        with tempfile.TemporaryDirectory() as td:
            r=Runner(td)
            snap=r.snapshot()
            self.assertIn('MuJoCo',snap['physics'])
            self.assertEqual(snap['updates'],0)
            trace=r.trial('reach',source='untrained',seed=123)
            self.assertEqual(trace['weights_updated'],False)
            self.assertFalse(trace['physical_motion'])
            self.assertGreater(len(trace['frames']),2)
            self.assertTrue(all(f['model_id']==MODEL_VERSION for f in trace['frames']))

    def test_short_real_physics_neural_training_and_reload(self):
        os.environ['SEIZO_PHYSICS_ENGINE']='mujoco'
        from core.runner import Runner,MODEL_ID
        with tempfile.TemporaryDirectory() as td:
            r=Runner(td)
            initial=r.agent.signature()
            r.start({'episodes':2,'task':'reach','compute':'fast'})
            r.thread.join(timeout=85)
            if r.thread.is_alive():
                r.stop();r.thread.join(timeout=15)
                self.fail('Real rigid physics learning did not stop within 85 seconds')
            snap=r.snapshot()
            self.assertNotEqual(snap['status'],'error',snap['error'])
            self.assertGreater(snap['updates'],0)
            self.assertGreaterEqual(snap['episodes'],2)
            self.assertNotEqual(initial,r.agent.signature())
            self.assertTrue((Path(td)/'policy.npz').exists())
            r2=Runner(td)
            self.assertEqual(r2.agent.signature(),r.agent.signature())
            self.assertEqual(r2.agent.updates,r.agent.updates)


if __name__=='__main__':unittest.main()
