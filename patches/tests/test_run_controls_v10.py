import json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from core.run_timing import RunTiming
from core.session_runner import SessionRunner,checked_ui
from core.view_policy import Agent
from core.view_world import ViewWorld

class Clock:
 def __init__(self):self.t=0
 def __call__(self):return self.t

class TimingTests(unittest.TestCase):
 def test_unknown_has_no_fabricated_eta(self):
  with tempfile.TemporaryDirectory() as td:
   t=RunTiming(Path(td)/'t.json');e=t.estimate({'cold|train|reach':1000})
   self.assertIsNone(e['seconds']);self.assertEqual(e['state'],'calibrating')
   self.assertTrue(e['not_a_skill_eta']);self.assertFalse(e['range_is_guarantee'])
 def test_known_rate_and_range(self):
  with tempfile.TemporaryDirectory() as td:
   t=RunTiming(Path(td)/'t.json');k=t.key('p','train','reach')
   for _ in range(20):t.record(k,10)
   e=t.estimate({k:100});self.assertEqual(e['seconds'],1000)
   self.assertLess(e['range_seconds'][0],1000);self.assertGreater(e['range_seconds'][1],1000)
   self.assertEqual(e['state'],'measured')
 def test_live_progress_reduces_estimate_and_counts(self):
  with tempfile.TemporaryDirectory() as td:
   c=Clock();t=RunTiming(Path(td)/'t.json',clock=c);k=t.key('p','eval_policy','reach')
   for _ in range(10):t.record(k,20)
   t.start('test',{k:10});self.assertEqual(t.snapshot()['seconds'],200)
   t.completed(k);c.t=5;v=t.snapshot();self.assertEqual(v['seconds'],175);self.assertEqual(v['completed_trials'],1)
 def test_related_task_estimate_is_explicitly_provisional(self):
  with tempfile.TemporaryDirectory() as td:
   t=RunTiming(Path(td)/'t.json')
   for _ in range(10):t.record(t.key('p','eval_policy','reach'),20)
   e=t.estimate({t.key('p','eval_random','lift'):10})
   self.assertEqual(e['state'],'provisional');self.assertIsNotNone(e['seconds'])
   self.assertIsNone(t.estimate({t.key('different','eval_random','lift'):10})['seconds'])
 def test_history_reload_and_bad_samples(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'timing.json';t=RunTiming(p)
   for x in [10]*10+[-1,float('nan'),float('inf')]:t.record('p|train|reach',x)
   t.save();u=RunTiming(p);self.assertEqual(len(u.samples['p|train|reach']),10)
   obj=json.loads(p.read_text());obj['host']='another machine';p.write_text(json.dumps(obj))
   self.assertFalse(RunTiming(p).samples)

class SessionTests(unittest.TestCase):
 def test_test_count_includes_policy_random_and_faults(self):
  with tempfile.TemporaryDirectory() as td:
   r=SessionRunner(td)
   try:
    self.assertEqual(r.estimate_run('test',trials=20)['remaining_trials'],290)
    self.assertEqual(r.estimate_run('test',trials=100)['remaining_trials'],1450)
    for n in [True,0,1.5]:
     with self.assertRaises(ValueError):r.estimate_run('train',episodes=n)
   finally:r.shutdown()
 def test_end_ack_does_not_wait_for_model_lock(self):
  with tempfile.TemporaryDirectory() as td:
   r=SessionRunner(td);r.save();ready=threading.Event();release=threading.Event()
   def hold():
    with r.lock:ready.set();release.wait(2)
   th=threading.Thread(target=hold);th.start();ready.wait(2)
   start=time.perf_counter();reply=r.end_run();latency=time.perf_counter()-start
   self.assertLess(latency,.2);self.assertFalse(reply['save_complete']);self.assertTrue(reply['tab_remains_open'])
   self.assertTrue(r.stop_event.is_set());release.set();th.join();r._end_worker.join(10)
   self.assertEqual(r.end_state['state'],'saved');r.shutdown()
 def test_original_v9_weights_budget_and_ui_survive(self):
  with tempfile.TemporaryDirectory() as td:
   original=Agent();original.episodes=37;original.steps=450
   original.save(Path(td)/'policy.npz',{'target':1000,'config':{'episodes':1000,'task':'reach','compute':'cad','fault_probability':0.0}})
   r=SessionRunner(td);before=r.agent.signature();u={**r.ui,'speed':450,'eval_trials':20,'hide_previews':True}
   r.end_run(u);r._end_worker.join(15)
   self.assertEqual(r.agent.signature(),before);self.assertEqual(r.agent.episodes,37)
   self.assertEqual(r.estimate_run('train',task='reach')['remaining_trials'],963)
   r.shutdown();s=SessionRunner(td)
   try:self.assertEqual(s.agent.signature(),before);self.assertEqual(s.ui,u);self.assertEqual(s.target,1000)
   finally:s.shutdown()
 def test_camera_framing_uses_actual_camera_not_secret_input(self):
  w=ViewWorld(1,61,'reach',view_mode='all',camera_config={'profile':'fixed','framing':'workspace','wrist_height_m':.075})
  try:
   f=w.frame();self.assertEqual(f['cameras']['settings']['framing'],'workspace')
   self.assertAlmostEqual(f['cameras']['settings']['wrist_local_pos'][2],.075)
   self.assertFalse(f['cameras']['settings']['lens_height_is_measured'])
  finally:w.close()
 def test_settings_reject_unknown_and_keep_default_no_sleep_change(self):
  self.assertFalse(checked_ui({})['keep_awake'])
  for bad in [{'x':1},{'keep_awake':1},{'task':'physical motor'},{'episodes':True}]:
   with self.assertRaises(ValueError):checked_ui(bad)

if __name__=='__main__':unittest.main()
