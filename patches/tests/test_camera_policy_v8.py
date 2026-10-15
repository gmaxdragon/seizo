import unittest, json, tempfile, time, hashlib, ast, threading
from pathlib import Path
import numpy as np
from core.camera_observation import encode, OBS_SIZE, WIDTH, HEIGHT, CONTRACT, POLICY_ID
from core.camera_world import CameraWorld, validate_config, camera_xml
from core.camera_policy import Agent
from core.runner import Runner, evaluate
import mujoco

class InputContract(unittest.TestCase):
 def test_only_pixels_and_known_instructions(self):
  black=np.zeros((2,HEIGHT,WIDTH,3),np.uint8)
  x=encode(black,black,0,0,0,.5,np.zeros(5),[1,1],[0,0])
  self.assertEqual(x.shape,(OBS_SIZE,))
  self.assertTrue(np.isfinite(x).all())
  self.assertIn('true joint position',CONTRACT['forbidden_inputs'])
 def test_actor_cannot_accept_simulator_object(self):
  with self.assertRaises(TypeError):encode(simulator='hidden')
 def test_two_views_required(self):
  with self.assertRaises(ValueError):encode(np.zeros((3,HEIGHT,WIDTH,3),np.uint8),None,0,0,0,.5,np.zeros(5),[1,1],[0,0])
 def test_frame_change_changes_actor_input(self):
  a=np.zeros((2,HEIGHT,WIDTH,3),np.uint8);b=a.copy();b[:,40:60,40:60,0]=255
  args=(0,0,0.,.5,np.zeros(5),[1,1],[0,0])
  self.assertFalse(np.array_equal(encode(a,a,*args),encode(b,a,*args)))
 def test_configuration_bounds(self):
  for c in ({'overhead_height_m':9},{'profile':'anywhere'},{'wrist_mount':'sky'},{'frame_faults':1}):
   with self.assertRaises(ValueError):validate_config(c)

class RenderedCameras(unittest.TestCase):
 def test_real_images_and_no_hidden_state_leak_after_capture(self):
  w=CameraWorld(seed=41)
  try:
   before=w.observation()
   self.assertEqual(w.model.ncam,2);self.assertGreater(np.std(w._current),3)
   w.q[:]=999;w.objects[:]=-999;w.tcp[:]=888;w.pinched[:]=True
   np.testing.assert_array_equal(before,w.observation())
   self.assertTrue(w.frame()['cameras']['overhead'].startswith('iVBOR'))
  finally:w.close()
 def test_wrist_is_mounted_and_overhead_is_stationary(self):
  for mount,parent in [('before_roll','wrist_mount'),('with_roll','wrist_and_palm')]:
   w=CameraWorld(seed=10,camera_config={'wrist_mount':mount})
   try:
    self.assertEqual(int(w.model.cam_bodyid[w.model.camera('overhead').id]),0)
    self.assertEqual(int(w.model.cam_bodyid[w.model.camera('wrist').id]),w.model.body(parent).id)
   finally:w.close()
 def test_bounded_variation_and_no_teleporting_camera_within_trial(self):
  w=CameraWorld(seed=41)
  try:
   initial=json.dumps(w.scene_settings[0],sort_keys=True)
   w.step(np.zeros((1,5)))
   self.assertEqual(initial,json.dumps(w.scene_settings[0],sort_keys=True))
   w.reset()
   self.assertNotEqual(initial,json.dumps(w.scene_settings[0],sort_keys=True))
  finally:w.close()
 def test_fixed_camera_setup_is_repeatable(self):
  w=CameraWorld(seed=41,camera_config={'profile':'fixed'})
  try:
   first=json.dumps(w.scene_settings[0],sort_keys=True);w.reset()
   self.assertEqual(first,json.dumps(w.scene_settings[0],sort_keys=True))
  finally:w.close()
 def test_7mm_rear_tabs_and_initial_clearance(self):
  w=CameraWorld(seed=78189)
  try:
   for name in ('rear_upper_tab','rear_lower_tab'):
    self.assertAlmostEqual(float(w.model.geom_size[w.model.geom(name).id,2])*2000,7)
   self.assertGreaterEqual(w.table_clearance(0),.030)
  finally:w.close()
 def test_camera_gone_does_not_fall_back_to_simulator_state(self):
  w=CameraWorld(seed=10)
  try:
   w.observation();w._available[:]=False
   _,_,term,_,info=w.step(np.ones((1,5)))
   self.assertTrue(term[0]);self.assertTrue(info['invalid_physics'][0])
   self.assertFalse(info['success'][0])
  finally:w.close()
 def test_table_guard_rejects_below_table_substep(self):
  w=CameraWorld(seed=41,camera_config={'profile':'fixed'})
  try:
   # A conservative reset, followed by repeated requested downward motion.
   minimum=w.table_clearance(0)
   for _ in range(60):
    _,_,term,trunc,info=w.step(np.array([[0.,-1.,-1.,0.,0.]]))
    minimum=min(minimum,w.table_clearance(0))
    if term[0] or trunc[0]:break
   self.assertGreaterEqual(minimum,.00149)
   self.assertFalse(info['success'][0])
   self.assertTrue(w.guard_reason[0])
  finally:w.close()

class PersistenceAndEvidence(unittest.TestCase):
 def test_camera_policy_has_distinct_identity_and_roundtrip(self):
  a=Agent()
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'policy.npz';a.save(p);b,_=Agent.load(p)
   self.assertEqual(a.signature(),b.signature())
   self.assertEqual(a.model_id,POLICY_ID)
   self.assertEqual(a.p['p1'].shape[0],OBS_SIZE)
 def test_stop_and_save_during_actual_camera_training(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   r.start({'episodes':1000,'task':'reach','compute':'fast'})
   time.sleep(1)
   r.stop();r.thread.join(20)
   self.assertFalse(r.thread.is_alive());self.assertEqual(r.status,'paused')
   self.assertTrue(r.save_verified)
   again=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   self.assertEqual(again.agent.signature(),r.agent.signature())
   self.assertEqual(again.agent.steps,r.agent.steps)
   receipt=json.loads((Path(tmp)/'last_save_receipt.json').read_text())
   self.assertTrue(receipt['verified_by_reload'])
 def test_current_lesson_is_not_mastery(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   r.config['task']='rotate'
   self.assertEqual(r.snapshot()['lesson'],'Lift and rotate')
   self.assertTrue(all(s['status']=='not evaluated' and not s['mastery_claim'] for s in r.skill_evidence()))
 def test_evaluation_freezes_weights_and_can_cancel(self):
  a=Agent();sig=a.signature()
  with self.assertRaises(InterruptedError):
   evaluate(a,'reach',1,world_factory=CameraWorld,stop=lambda:True)
  self.assertEqual(a.signature(),sig)
 def test_tiny_genuine_pixel_training_changes_weights(self):
  from core.ppo import rollout
  w=CameraWorld(seed=10);a=Agent();sig=a.signature()
  try:
   batch,_=rollout(a,w,4)
   a.update(batch,epochs=1)
   self.assertNotEqual(a.signature(),sig);self.assertGreater(a.updates,0)
  finally:w.close()

class PreviewAndInputRegressions(unittest.TestCase):
 def test_active_preview_reuses_actual_frame_without_new_renderer(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   r.preview_frame={'cameras':{'overhead':'stored','wrist':'stored'},'tool':[1,2,3]}
   r.status='training'
   self.assertEqual(r.camera_preview()['tool'],[1,2,3])
   with self.assertRaises(ValueError):r.camera_preview(resample=True)
 def test_invalid_watch_seed_does_not_leave_runner_busy(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   with self.assertRaises(ValueError):r.trial(seed='invalid')
   self.assertEqual(r.status,'ready')
 def test_recorded_skill_is_stale_after_weights_change(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   r.last_evaluation={'policy_fingerprint':r.agent.signature(),'by_task':[]}
   # A lesson selected or a nonzero update count alone does not grant a skill.
   r.agent.updates=99
   self.assertTrue(all(not item['mastery_claim'] for item in r.skill_evidence()))

class FrozenCancellationSave(unittest.TestCase):
 def test_one_trial_ui_setting_is_accepted_and_cancel_saves(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   sig=r.agent.signature()
   r.begin_evaluation(task='reach',trials=1)
   r.stop();r.thread.join(30)
   self.assertFalse(r.thread.is_alive());self.assertNotEqual(r.status,'error',r.error)
   self.assertTrue(r.save_verified);self.assertEqual(sig,r.agent.signature())
 def test_cancelled_camera_watch_saves_even_without_training(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runner(tmp,agent_factory=Agent,world_factory=CameraWorld)
   errors=[]
   def work():
    try:r.trial('reach',seed=41)
    except InterruptedError:pass
    except Exception as e:errors.append(str(e))
   worker=threading.Thread(target=work)
   worker.start();time.sleep(.6);r.stop();worker.join(30)
   self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
   self.assertTrue(r.save_verified);self.assertTrue((Path(tmp)/'policy.npz').exists())

if __name__=='__main__':unittest.main()
