"""Actual local HTTP tests; no cloud or device credentials are used."""
import unittest,json,re,tempfile,threading,urllib.request,urllib.error
from unittest.mock import patch
from pathlib import Path
import numpy as np
import app
from core.runner import Runner

class CloudStub:
 def status(self):return {'key_loaded':False}

class HTTP(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.r=Runner(self.tmp.name);self.token='local-test-only-token'
  self.s=app.Server(('127.0.0.1',0),app.make_handler(self.r,self.token,threading.Event(),CloudStub(),'test-instance'))
  self.th=threading.Thread(target=self.s.serve_forever,daemon=True);self.th.start()
  self.url='http://127.0.0.1:'+str(self.s.server_port)
 def tearDown(self):
  self.r.shutdown();self.s.shutdown();self.s.server_close();self.th.join();self.tmp.cleanup()
 def request(self,path,data=None,authorized=True,origin=None):
  headers={'X-Lab-Token':self.token if authorized else 'wrong','Origin':origin or self.url,'Content-Type':'application/json'}
  req=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
  try:
   with urllib.request.urlopen(req,timeout=15) as r:return r.status,r.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def test_check_routes_are_real_physics_not_weight_changes(self):
  before=self.r.agent.signature();s,b=self.request('/api/gripper-check',{'mode':'open_close'});r=json.loads(b)
  self.assertEqual(s,200);self.assertGreater(len(r['frames']),100)
  self.assertGreater(max(f['pose']['gripper'] for f in r['frames'])-min(f['pose']['gripper'] for f in r['frames']),.95)
  self.assertFalse(r['physical_motion']);self.assertFalse(r['weights_updated']);self.assertEqual(before,self.r.agent.signature())
 def test_unauthorized_and_wrong_origin_rejected(self):
  self.assertEqual(self.request('/api/gripper-check',{'mode':'wrist'},authorized=False)[0],403)
  self.assertEqual(self.request('/api/gripper-check',{'mode':'wrist'},origin='https://example.invalid')[0],403)
 def test_nonexistent_hardware_and_unknown_modes_rejected(self):
  self.assertEqual(self.request('/api/gripper-check',{'mode':'physical'})[0],400)
  self.assertEqual(self.request('/api/move-real-motor',{})[0],404)
 def test_diagnostic_during_training_blocked(self):
  self.r.status='training'
  self.assertEqual(self.request('/api/gripper-check',{'mode':'contact'})[0],400)
  self.r.status='ready'
 def test_gripper_controls_in_actual_served_page(self):
  s,b=self.request('/');html=b.decode();self.assertEqual(s,200)
  self.assertIn('id="gripperCheck"',html);self.assertIn('id="gripperMode"',html)
  self.assertIn('value="contact"',html)
 def test_missing_mujoco_blocks_approximate_training(self):
  class Missing:__module__='core.world'
  with patch.object(app,'World',Missing):
   s,b=self.request('/api/gripper-check',{'mode':'open_close'})
   self.assertEqual(s,400);self.assertIn('MuJoCo',b.decode())

class Migration(unittest.TestCase):
 def test_v4_policy_archived_byte_for_byte(self):
  with tempfile.TemporaryDirectory() as td:
   r=Runner(td);p=Path(td)/'policy.npz';r.save()
   with np.load(p,allow_pickle=False) as z:data={k:z[k] for k in z.files}
   meta=json.loads(str(data['meta']));meta['model_id']='seizo-five-control-mujoco-rigid-v4';data['meta']=np.array(json.dumps(meta))
   with p.open('wb') as h:np.savez_compressed(h,**data)
   old=p.read_bytes();r2=Runner(td);backups=list(Path(td).glob('legacy_physics_checkpoint_*/policy.npz'))
   self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),old)
   self.assertEqual(r2.agent.updates,0)
if __name__=='__main__':unittest.main()
