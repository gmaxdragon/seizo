"""Regression for real missing-contact and ghost-contact bugs in old Seizo engine."""
import unittest
import numpy as np
from core.world import World, fk, FLOOR, D, MODEL_ID
from core.contact import colliders, solve_capsule_contacts, FINGER_RADIUS

class CollisionTests(unittest.TestCase):
    def forearm_rib_scene(self):
        w=World(1,seed=31,task='reach',fault_probability=0.)
        w.q[0]=[0.,55.,0.,0.,.9]
        w.targetq=w.q.copy();w.v[:]=0
        arm=fk(w.q)
        beam=arm[2][0]+np.array([108.,0.,0.])
        w.radius[0,:]=12.
        w.objects[0,0]=beam+np.array([0.,0.,40.])
        w.objects[0,1]=[200.,-300.,FLOOR+12.]
        w.objects[0,2]=[200.,300.,FLOOR+12.]
        w.ov[:]=0;w.pinched[:]=False
        return w,beam,arm[0]

    def test_actual_previously_failing_forearm_crossrib_drop(self):
        w,beam,tcp=self.forearm_rib_scene()
        for _ in range(20):w._object_step(tcp,np.zeros((1,3)))
        self.assertGreaterEqual(w.objects[0,0,2]-12.,beam[2]+9.-.03)
        self.assertGreater(w.contact_steps[0],0)

    def test_unrelated_distant_objects_do_not_exchange_momentum(self):
        w,beam,tcp=self.forearm_rib_scene()
        # This test finds the ghost impulse in the old simulator that pushed
        # non-touching objects sideways, even when meters apart.
        w.objects[0,0]=[2000.,0.,500.]
        w.objects[0,1]=[2300.,200.,500.]
        w.objects[0,2]=[2700.,-200.,500.]
        w.ov[:]=0.
        w.ov[0,0,:2]=[110.,0.]
        w.ov[0,1,:2]=[-50.,0.]
        w.ov[0,2,:2]=[0.,25.]
        before=w.ov[0,:,:2].copy()
        w._object_step(tcp,np.zeros((1,3)))
        # Five 0.995 damping steps; no extra impulse from distant objects.
        np.testing.assert_allclose(w.ov[0,:,:2],before*(.995**5),atol=.01)

    def test_actual_collider_names_cover_moving_arm_base_and_fingers(self):
        w=World(2,seed=5)
        a,b,r,n=colliders(w.q,fk,D)
        self.assertEqual((2,len(n),3),a.shape)
        self.assertEqual(a.shape,b.shape)
        for text in ('base_tower','forearm_cross_rib_108','wrist_palm','upper_rail_-1','jaw_-1','jaw_1'):
            self.assertIn(text,n)
        self.assertTrue((r>0).all())

    def test_very_close_contact_resolves_outside_colliders(self):
        w,beam,tcp=self.forearm_rib_scene()
        starts,ends,r,names=colliders(w.q,fk,D)
        i=names.index('forearm_cross_rib_108')
        pos=np.array([[[beam[0],beam[1],beam[2]+1.]]],dtype=float)
        vel=np.array([[[0.,0.,-350.]]])
        touched,_=solve_capsule_contacts(pos,vel,starts[:,i:i+1],ends[:,i:i+1],r[i:i+1],np.array([[12.]]),previous_positions=pos.copy())
        self.assertTrue(touched[0,0])
        self.assertGreaterEqual(pos[0,0,2],beam[2]+9+12-.01)
        self.assertGreaterEqual(vel[0,0,2],-.01)

    def test_no_fake_grasp_far_from_jaws(self):
        w=World(1,7,'lift')
        w.objects[:,:,:2]=10000.
        w.q[0,4]=0.;w.targetq[0,4]=0.
        tcp=fk(w.q)[0]
        for _ in range(3):w._object_step(tcp,np.zeros((1,3)))
        self.assertFalse(w.pinched.any())

    def test_aperture_matches_contact_geometry(self):
        w=World(1,12,'lift');w.q[0,4]=0.62
        starts,ends,r,names=colliders(w.q,fk,D)
        i=names.index('jaw_-1');j=names.index('jaw_1')
        spacing=np.linalg.norm(starts[0,i]-starts[0,j])
        self.assertAlmostEqual(spacing,6+50*.62,places=5)

    def test_neural_model_version_invalidates_old_physics_policy(self):
        self.assertIn('v3',MODEL_ID)

if __name__=='__main__':unittest.main()

# Test the migration separately so a changed physics model does not present a
# pre-fix PPO checkpoint as validated data.
class CheckpointMigrationTests(unittest.TestCase):
    def test_incompatible_weights_archived_not_destroyed(self):
        import tempfile,io,json,time
        from pathlib import Path
        from core.ppo import Agent
        from core.runner import Runner
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            a=Agent();a.save(folder/'policy.npz')
            original=(folder/'policy.npz').read_bytes()
            # Modify only policy metadata to simulate a real v2 file while
            # keeping the payload a structurally valid NumPy archive.
            with np.load(io.BytesIO(original),allow_pickle=False) as z:
                payload={k:z[k] for k in z.files}
            meta=json.loads(str(payload['meta']))
            meta['model_id']='seizo-five-control-contact-ppo-v2'
            payload['meta']=np.array(json.dumps(meta))
            np.savez_compressed(folder/'policy.npz',**payload)
            prior=(folder/'policy.npz').read_bytes()
            runner=Runner(folder)
            self.assertEqual(runner.status,'ready')
            backups=list(folder.glob('legacy_physics_checkpoint_*/policy.npz'))
            self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_bytes(),prior)
            self.assertEqual(runner.agent.episodes,0)
            self.assertFalse((folder/'policy.npz').exists())
