import tempfile,time,unittest,json,copy
from pathlib import Path
from unittest.mock import patch
import numpy as np,mujoco
from core.view_observation import encode,NAMES,WIDTH,HEIGHT,OBS_SIZE
from core.view_curriculum import ViewSchedule,MotionDiscovery
from core.view_policy import Agent
from core.view_world import ViewWorld
from core.view_runner import ViewRunner
from core.ppo import rollout
from core.runner import evaluate

class Observation(unittest.TestCase):
 def test_hidden_helpers_zero_current_and_history(self):
  rng=np.random.default_rng(2);a=rng.integers(0,256,(4,HEIGHT,WIDTH,3),np.uint8);b=a.copy()
  args=(0,0,0,.5,np.zeros(5),[1,1,0,0],[0]*4)
  x=encode(a,b,*args);a[2:]=255;b[2:]=0;y=encode(a,b,*args)
  np.testing.assert_array_equal(x,y);self.assertEqual(x.shape,(OBS_SIZE,))
 def test_available_view_changes_input(self):
  a=np.zeros((4,HEIGHT,WIDTH,3),np.uint8);b=a.copy();b[2,20:180]=255
  args=(0,0,0,.5,np.zeros(5),[1]*4,[0]*4)
  self.assertFalse(np.array_equal(encode(a,a,*args),encode(b,a,*args)))
 def test_no_state_keyword(self):
  with self.assertRaises(TypeError):encode(simulator=object())

class Curriculum(unittest.TestCase):
 def test_initial_and_final_masks(self):
  r=np.random.default_rng(1);s=ViewSchedule()
  self.assertTrue(s.masks(r).all());s.stage=2
  np.testing.assert_array_equal(s.masks(r),[1,1,0,0])
 def test_fade_is_not_timed_or_assisted_score(self):
  s=ViewSchedule();v={'sensor_condition':'two_mounted_cameras','trials':20,'success_rate':.75,'invalid_physics':0,'weights_updated':False}
  self.assertFalse(s.observe_test({**v,'sensor_condition':'four_cameras'}));self.assertEqual(s.stage,0)
  self.assertFalse(s.observe_test(v));self.assertTrue(s.observe_test(v));self.assertEqual(s.stage,1)
  self.assertFalse(s.observe_test({**v,'trials':1}));self.assertEqual(s.streak,0)
 def test_no_credit_for_camera_changes_or_repeated_pose(self):
  d=MotionDiscovery();q=np.zeros(5);d.reset([0,0,0],q,0)
  self.assertEqual(d.reward([0,0,0],q,q),0)
  self.assertGreater(d.reward([13,0,0],q,q),0)
  self.assertEqual(d.reward([0,0,0],q,q),0)
  self.assertEqual(d.reward([13,0,0],q,q),0)
 def test_cap_fade_and_invalid(self):
  d=MotionDiscovery();q=np.zeros(5);d.reset([0,0,0],q,0)
  total=sum(d.reward([i*13,0,0],q,q) for i in range(100))
  self.assertLessEqual(total,.500001)
  d.reset([0,0,0],q,500);self.assertEqual(d.reward([13,0,0],q,q),0)
  d.reset([0,0,0],q,0);self.assertEqual(d.reward([13,0,0],q,q,True),0)

class ActualViews(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.w=ViewWorld(seed=42,camera_config={'profile':'fixed'},view_mode='all')
 @classmethod
 def tearDownClass(cls):cls.w.close()
 def test_detailed_images_are_real_rendered_meshes(self):
  w=self.w;x=w.observation()
  self.assertEqual(x.shape,(1,OBS_SIZE));self.assertEqual(w.model.ncam,4)
  self.assertGreater(w.model.nmesh,80);self.assertGreater(np.std(w._current),10)
  self.assertTrue(all(float(np.std(im))>10 for im in w._current[0]))
 def test_no_added_motor_or_contact_disabled(self):
  m=self.w.model;self.assertEqual(m.nu,5)
  for k in range(m.ngeom):
   n=m.geom(k).name
   if n.startswith('detail_'):self.assertEqual(m.geom_contype[k],0)
  for name in ('left_jaw_contact','right_jaw_contact'):
   self.assertGreater(m.geom_contype[m.geom(name).id],0)
 def test_fixed_cameras_do_not_jump_during_attempt(self):
  w=self.w;old=json.dumps(w.scene_settings[0]);w.step(np.zeros((1,5)))
  self.assertEqual(old,json.dumps(w.scene_settings[0]))
 def test_rendered_input_not_privileged_state(self):
  w=self.w;w.observation();expected=w.observation();q=w.q.copy();objects=w.objects.copy()
  try:
   w.q[:]=777;w.objects[:]=-999
   np.testing.assert_array_equal(expected,w.observation())
  finally:w.q[:]=q;w.objects[:]=objects
 def test_mounted_camera_parents_match_config(self):
  m=self.w.model
  self.assertEqual(m.cam_bodyid[m.camera('overhead').id],0)
  self.assertEqual(m.cam_bodyid[m.camera('wrist').id],m.body('wrist_mount').id)
 def test_guards_remain_active(self):
  self.assertGreaterEqual(self.w.table_clearance(0),.00149)
  for n in ('rear_lower_tab','rear_upper_tab'):self.assertAlmostEqual(self.w.model.geom(n).size[2]*2000,7)
 def test_evaluation_world_two_only_no_discovery_bonus(self):
  w=ViewWorld(seed=1,view_mode='two',camera_config={'profile':'fixed'})
  try:
   w.observation();self.assertTrue(np.all(w._current[0,2:]==0))
   _,_,_,_,info=w.step([[.1,0,0,0,0]])
   self.assertEqual(info['discovery_bonus'][0],0)
   self.assertEqual(w.frame()['cameras']['policy_camera_names'],['overhead','wrist'])
  finally:w.close()

class Persistence(unittest.TestCase):
 def test_saved_views_and_previous_policy_preserved(self):
  with tempfile.TemporaryDirectory() as p:
   from app import default_runner
   root=Path(p);(root/'camera_pixels_v8').mkdir();f=root/'camera_pixels_v8/policy.npz';f.write_bytes(b'old untouched')
   r=default_runner(root);r.agent.views.stage=1;r.agent.views.streak=1;r.set_views('two');r.save()
   again=default_runner(root);self.assertEqual(again.agent.signature(),r.agent.signature())
   self.assertEqual((again.agent.views.stage,again.agent.views.streak,again.agent.view_mode),(1,1,'two'))
   self.assertEqual(f.read_bytes(),b'old untouched')
 def test_evaluation_forces_helpers_off_even_if_practice_all(self):
  with tempfile.TemporaryDirectory() as p:
   r=ViewRunner(p);r.agent.view_mode='all'
   self.assertEqual(r.evaluation_options()['view_mode'],'two')
   self.assertFalse(r.evaluation_options()['learning_enabled'])
 def test_stopping_and_saving_actual_detailed_training(self):
  with tempfile.TemporaryDirectory() as p:
   r=ViewRunner(p);r.start({'episodes':1000,'task':'reach','compute':'fast'})
   deadline=time.time()+15
   while r.agent.steps<2 and time.time()<deadline:
    if r.status=='error':self.fail(r.error)
    time.sleep(.1)
   r.stop();r.thread.join(20);self.assertFalse(r.thread.is_alive());self.assertTrue(r.save_verified)
   again=ViewRunner(p);self.assertEqual(again.agent.steps,r.agent.steps);self.assertEqual(again.agent.signature(),r.agent.signature())
 def test_actual_pixel_batch_updates_not_pretrained(self):
  a=Agent();before=a.signature();w=ViewWorld(seed=66,camera_config={'profile':'fixed'},learning_enabled=True,view_mode='all')
  try:
   batch,ep=rollout(a,w,8);a.update(batch,epochs=1)
   self.assertNotEqual(a.signature(),before);self.assertGreater(a.updates,0)
  finally:w.close()

if __name__=='__main__':unittest.main()
