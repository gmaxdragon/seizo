"""Regression tests for crossing jaws, two servo ownership, contact and rendering state."""
import json,unittest,tempfile,os
from pathlib import Path
import numpy as np
import mujoco
from core.mjcf import xml_model,validate_structure,MODEL_VERSION,SUBSTEPS
from core.gripper_geometry import jaw_shift,aperture_mm,SPEC,MAX_ANGLE
from core.mujoco_world import MuJoCoWorld
from core.gripper_check import run_check,check_world
ROOT=Path(__file__).resolve().parents[1]

class GripperV5(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.open=run_check('open_close');cls.turn=run_check('wrist');cls.contact=run_check('contact')
 def test_exactly_two_tool_servo_controls(self):
  w=MuJoCoWorld();self.assertEqual(w.model.nu,5)
  self.assertEqual([w.model.actuator(i).name for i in range(3,5)],['motor_wrist','motor_gripper'])
 def test_linkages_are_passive_not_extra_motor_outputs(self):
  self.assertEqual(validate_structure()['joints'],9)
  self.assertEqual(validate_structure()['actuators'],5)
 def test_opposing_jaw_collision_not_excluded(self):
  from xml.etree import ElementTree as ET
  for e in ET.fromstring(xml_model()).findall('.//contact/exclude'):
   self.assertNotEqual({e.get('body1'),e.get('body2')},{'left_jaw','right_jaw'})
 def test_never_negative_analytic_aperture(self):
  vals=[aperture_mm(v) for v in np.linspace(0,1,1001)]
  self.assertGreaterEqual(min(vals),6.0);self.assertGreater(max(vals),40.)
  self.assertTrue(np.all(np.diff(vals)>0))
 def test_link_length_is_constant(self):
  L=np.hypot(*SPEC['link'][:2])
  for a in np.linspace(0,1,201):
   dx,dy=jaw_shift(a);self.assertAlmostEqual(np.hypot(46+dx,31+dy),L,places=10)
 def test_actual_3d_mesh_does_not_cross_midplane(self):
  mesh=json.loads((ROOT/'web/assets/meshes.json').read_text())['finger']
  verts=np.array(mesh['p']).reshape(-1,3)
  for f in self.open['frames']+self.turn['frames']:
   wrist=np.array(f['rigid_bodies']['wrist']).reshape(4,4).T
   inv=np.linalg.inv(wrist)
   for name,side in [('jawLeft',1),('jawRight',-1)]:
    mat=np.array(f['rigid_bodies'][name]).reshape(4,4).T
    pts=verts.copy();pts[:,1]*=side
    out=(inv@mat@np.c_[pts,np.ones(len(pts))].T).T
    self.assertGreater((out[:,1]*side).min(),2.7)
 def test_visual_open_close_uses_real_simulated_gap(self):
  fs=self.open['frames'];opens=[f['pose']['gripper'] for f in fs]
  self.assertLess(min(opens),.01);self.assertGreater(max(opens),.98)
 def test_close_does_not_turn_wrist(self):
  self.assertLess(max(abs(f['pose']['wrist']) for f in self.open['frames']),.02)
 def test_wrist_turn_does_not_close_jaws(self):
  f=self.turn['frames'];self.assertGreater(max(x['pose']['wrist'] for x in f),34.)
  self.assertLess(min(x['pose']['wrist'] for x in f),-34.)
  self.assertGreater(min(x['pose']['gripper'] for x in f),.995)
 def test_arm_stays_locked_only_in_diagnostic(self):
  for f in self.turn['frames']+self.open['frames']:
   self.assertLess(abs(f['pose']['base']),.02)
   self.assertLess(abs(f['pose']['shoulder']-65),.03)
   self.assertLess(abs(f['pose']['forearm']+25),.04)
 def test_contact_resists_and_allows_further_closing_command(self):
  r=self.contact;self.assertTrue(r['contact_seen'])
  self.assertGreater(r['continued_closing_steps_after_contact'],20)
  phases=[f for f in r['frames'] if f['diagnostic_phase']=='Close and squeeze']
  self.assertLess(phases[-1]['gripper_requested_opening'],.001)
  self.assertGreater(phases[-1]['pose']['gripper'],.30)
  self.assertLess(phases[-1]['pose']['gripper'],.65)
 def test_contact_torque_bounded(self):
  self.assertGreater(self.contact['peak_virtual_gripper_torque_nm'],.02)
  self.assertLessEqual(self.contact['peak_virtual_gripper_torque_nm'],.060001)
 def test_reopening_releases_contact(self):
  self.assertGreater(self.contact['frames'][-1]['pose']['gripper'],.98)
  self.assertFalse(self.contact['frames'][-1]['arm_object_contact'])
 def test_no_learning_claim_or_real_commands_in_diagnostic(self):
  for r in (self.open,self.turn,self.contact):
   self.assertFalse(r['weights_updated']);self.assertFalse(r['physical_motion'])
   self.assertFalse(r['success']);self.assertEqual(r['policy_updates'],0)
 def test_invalid_input_rejected(self):
  w=MuJoCoWorld();
  with self.assertRaises(ValueError):w.step(np.full((1,5),np.nan))
  with self.assertRaises(ValueError):run_check('physical')
 def test_held_target_does_not_chase_gravity(self):
  w=MuJoCoWorld(seed=8);q=w.targetq.copy()
  for _ in range(20):w.step(np.zeros((1,5)))
  np.testing.assert_allclose(w.targetq,q,rtol=0,atol=1e-12)
 def test_free_block_held_by_contacts_then_released(self):
  w,q=check_world('open_close');d=w.data[0];m=w.model
  q[4]=.44;w.q[0]=q;w.targetq[0]=q;w._set_pose(d,q);mujoco.mj_forward(m,d)
  b=m.body('wrist_and_palm').id
  p=d.xpos[b]+d.xmat[b].reshape(3,3)@np.array([.169,0.,.001])
  d.qpos[w.objadr[0]:w.objadr[0]+3]=p;d.qvel[:]=0;q[4]=0.;w._command(d,q)
  for _ in range(2500):mujoco.mj_step(m,d)
  mujoco.mj_forward(m,d)
  # No weld or grasp teleport. An initially pre-positioned free block is held
  # by the two jaws' contacts, then drops when the jaws open. Not AI training.
  self.assertGreater(d.xpos[w.bid['red_cube'],2],p[2]-.008)
  q[4]=1.;w._command(d,q)
  for _ in range(2000):mujoco.mj_step(m,d)
  mujoco.mj_forward(m,d)
  self.assertAlmostEqual(d.xpos[w.bid['red_cube'],2],.077,delta=.001)
 def test_old_policy_identity_not_compatible(self):
  self.assertNotEqual(MODEL_VERSION,'seizo-five-control-mujoco-rigid-v4')
 def test_box_cylinder_ball_rotations_provided(self):
  for o in self.open['frames'][-1]['objects']:
   self.assertEqual(len(o['quaternion_wxyz']),4)
 def test_initial_pose_has_no_deep_internal_penetration(self):
  for seed in [3,8,19,52]:
   w=MuJoCoWorld(seed=seed);d=w.data[0];m=w.model
   contacts=[c.dist for c in d.contact[:d.ncon] if c.dist<-.001]
   self.assertFalse(contacts,contacts)
 def test_random_stress_no_crossing(self):
  w=MuJoCoWorld(seed=12);rng=np.random.default_rng(112)
  for _ in range(250):
   f=w.step(rng.uniform(-1,1,(1,5)));self.assertTrue(np.isfinite(f[0]).all())
   if f[2][0] or f[3][0]:w.reset()
   d=w.data[0]
   self.assertLess(abs(d.qpos[w.model.jnt_qposadr[w.jid['left_finger']]]-d.qpos[w.model.jnt_qposadr[w.jid['right_finger']]]),.02)

if __name__=='__main__':unittest.main()
