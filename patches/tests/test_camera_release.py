"""Default production entrypoint and frozen evaluation must use the SAME fake cameras."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app import default_runner,BUILD
from core.view_observation import POLICY_ID,CONTRACT,OBS_SIZE
from core.view_policy import Agent
from core.view_world import ViewWorld as CameraWorld
from core.runner import evaluate

class CameraProduction(unittest.TestCase):
    def test_default_existing_application_is_image_driven(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=b'old state-policy checkpoint must survive'
            (root/'policy.npz').write_bytes(old)
            r=default_runner(root)
            self.assertTrue(r.is_camera)
            self.assertIs(r.World,CameraWorld)
            self.assertIs(r.Agent,Agent)
            self.assertEqual(r.config['episodes'],1000)
            self.assertEqual(r.model_id,POLICY_ID)
            self.assertEqual(r.snapshot()['input_source'],'detailed_simulated_cameras')
            self.assertFalse(r.snapshot()['uses_real_cameras'])
            r.save();s=default_runner(root)
            self.assertEqual(s.agent.signature(),r.agent.signature())
            self.assertEqual((root/'policy.npz').read_bytes(),old)
            self.assertEqual(s.folder,root/'camera_views_v9')

    def test_frozen_test_receives_camera_vector_not_privileged_state(self):
        agent=Agent();shape=[]
        original=agent.act
        def observe(obs,*args,**kwargs):
            shape.append(obs.shape)
            self.assertEqual(obs.shape[1],OBS_SIZE)
            return original(obs,*args,**kwargs)
        agent.act=observe
        before=agent.signature()
        result=evaluate(agent,'reach',1,seed=19,world_factory=CameraWorld,
                        world_options={'camera_config':{'profile':'fixed'},'view_mode':'two'})
        self.assertTrue(shape)
        self.assertEqual(before,agent.signature())
        self.assertFalse(result['weights_updated'])
        self.assertEqual(result['input_source'],'simulated_overhead_and_wrist_rgb')

    def test_ui_explains_input_and_uses_existing_starter(self):
        root=Path(__file__).resolve().parents[1]
        text=(root/'web/index.html').read_text(encoding='utf-8')
        self.assertIn('See what the learner sees',text)
        self.assertIn('Train / resume',text);self.assertIn('Test all tasks',text)
        self.assertIn('START_SEIZO.bat',(root/'START_HERE.txt').read_text())
        self.assertNotIn('START_CAMERA_TEST.bat',(root/'START_HERE.txt').read_text())
        self.assertEqual(CONTRACT['camera_names'],['overhead','wrist','side','front'])
        self.assertIn('masked',CONTRACT['test_condition'])
        self.assertTrue(CONTRACT['simulation_only'])
        self.assertEqual(BUILD,'seizo-learning-feedback-v12')

if __name__=='__main__':unittest.main()
