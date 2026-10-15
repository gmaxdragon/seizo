"""Rigorous CPU-only checks of the optional REAL MuJoCo contact solver.

Runs on GitHub-hosted Linux with `pip install mujoco`; skips no physics tests
there. The test never imports serial, GPIO, Raspberry Pi or control drivers.
"""
import math
import unittest
import numpy as np
from core.mjcf import validate_structure, xml_model, MODEL_VERSION


class TestMJCFStatic(unittest.TestCase):
    def test_physical_model_has_nine_joints_and_free_objects(self):
        info=validate_structure()
        self.assertEqual(info['joints'],9)
        self.assertEqual(info['actuators'],5)
        self.assertEqual(info['free_objects'],3)

    def test_no_real_robot_drivers_or_lie_about_calibration(self):
        xml=xml_model()
        self.assertIn('freejoint name="free_red"',xml)
        self.assertIn('forcerange=',xml)
        self.assertIn('gravity="0 0 -9.81"',xml)
        self.assertNotIn('serial.',xml)
        self.assertNotIn('GPIO',xml)


try:
    import mujoco
    from core.mujoco_world import MuJoCoWorld
except ImportError:
    mujoco=None


@unittest.skipIf(mujoco is None,'Free MuJoCo package not installed locally; CI installs and runs these tests')
class TestMuJoCoDynamics(unittest.TestCase):
    def test_model_compiles_and_geometries_are_distinct(self):
        model=mujoco.MjModel.from_xml_string(xml_model())
        self.assertEqual(model.nu,5)
        self.assertEqual(model.nq,30)
        self.assertEqual(model.nv,27)
        names=[mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) for i in range(model.ngeom)]
        self.assertIn('forearm_crossbar_mid',names)
        self.assertIn('left_jaw_contact',names)
        self.assertIn('object_red',names)
        self.assertIn('object_green',names)
        self.assertIn('object_blue',names)
        for i in range(model.nu):
            self.assertEqual(model.actuator_forcelimited[i],1)
            self.assertGreater(model.actuator_forcerange[i,1],0)

    def test_free_object_falls_then_is_stopped_by_desk(self):
        model=mujoco.MjModel.from_xml_string(xml_model())
        data=mujoco.MjData(model)
        adr=model.jnt_qposadr[model.joint('free_red').id]
        data.qpos[adr:adr+3]=[0.65,0.0,0.3]
        mujoco.mj_forward(model,data)
        for _ in range(700):mujoco.mj_step(model,data)
        z=float(data.qpos[adr+2])
        self.assertGreater(z,.065+.012-.005)
        self.assertLess(z,.065+.012+.012)
        self.assertTrue(np.isfinite(data.qpos).all())

    def test_camera_visual_link_is_not_a_hidden_motor(self):
        world=MuJoCoWorld(n=1,seed=12)
        self.assertEqual(world.model.nu,5)
        self.assertEqual(len(world.q[0]),5)
        self.assertFalse(any('camera_tower' in name for name in (' '.join(n for n in world.jid))))

    def test_move_fingers_without_teleporting_objects(self):
        w=MuJoCoWorld(n=1,task='lift',seed=19)
        original=w.objects.copy()
        w.step(np.array([[0.,0.,0.,0.,-1.]]))
        self.assertTrue(np.isfinite(w.objects).all())
        self.assertTrue(np.isfinite(w.q).all())
        self.assertLess(np.linalg.norm(w.objects-original,axis=2).max(),200.)
        frame=w.frame()
        self.assertEqual(frame['model_id'],MODEL_VERSION)
        self.assertFalse(frame['physical_motion'])
        self.assertIn('MuJoCo',frame['physics_backend'])

    def test_collision_with_forearm_uses_a_real_contact(self):
        w=MuJoCoWorld(n=1,task='reach',seed=30)
        d=w.data[0];m=w.model
        rib=m.geom('forearm_crossbar_mid').id
        red=m.geom('object_red').id
        # Place a real rigid cube overlapping a real forearm rib. The engine
        # MUST produce contact constraints (not scripted pinched=True).
        center=d.geom_xpos[rib].copy()
        adr=w.objadr[0]
        d.qpos[adr:adr+3]=center+[0.,0.,.008]
        d.qpos[adr+3:adr+7]=[1,0,0,0]
        mujoco.mj_forward(m,d)
        touches=any({int(c.geom1),int(c.geom2)}=={rib,red} for c in d.contact[:d.ncon])
        self.assertTrue(touches,'No actual MuJoCo contact constraint between solid rib and cube')

    def test_not_learning_when_just_watching(self):
        w=MuJoCoWorld(n=2,task='all',seed=6)
        assert w.observation().shape==(2,49)
        before=w.count.copy()
        for _ in range(4):
            obs,reward,term,trunc,info=w.step(np.zeros((2,5)))
            self.assertTrue(np.isfinite(obs).all())
            self.assertTrue(np.isfinite(reward).all())
            self.assertEqual(len(info['success']),2)
        self.assertTrue(np.all(w.count==before+4))

    def test_motor_force_saturation(self):
        w=MuJoCoWorld(n=1,task='reach',seed=8)
        w.step(np.array([[1.,1.,-1.,1.,-1.]]))
        d=w.data[0];m=w.model
        for k in range(m.nu):
            lo,hi=m.actuator_forcerange[k]
            self.assertLessEqual(float(d.actuator_force[k]),hi+1e-5)
            self.assertGreaterEqual(float(d.actuator_force[k]),lo-1e-5)


if __name__=='__main__':unittest.main()
