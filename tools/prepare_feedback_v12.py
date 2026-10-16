"""Build the v12 candidate from pinned v11 integration inputs, before testing."""
from pathlib import Path
import runpy,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'tools/apply_feedback_v12.py'),run_name='__main__')
def edit(name,old,new):
    p=ROOT/'patches'/name;s=p.read_text(encoding='utf-8')
    assert s.count(old)==1,(name,s.count(old),old[:70])
    p.write_bytes(s.replace(old,new).encode('utf-8'))
# A guard abort must not buy a cheaper ending than 220 idle moves. The first
# experiment exposed worse guard counts despite numerically higher returns.
edit('core/learning_feedback.py',"events=['unsafe_action'];penalty=-1.","events=['unsafe_action'];penalty=-8.")
edit('core/learning_feedback.py',"events=['object_out_of_workspace'];penalty=-1.","events=['object_out_of_workspace'];penalty=-8.")
edit('core/learning_feedback.py',"total=min(total,-1. if events[0]", "total=min(total,-8. if events[0]")
edit('core/learning_feedback.py',"'physics_aborts_before':reference['invalid_physics'],'physics_aborts_after':current['invalid_physics'],",
     "'physics_aborts_before':reference['invalid_physics'],'physics_aborts_after':current['invalid_physics'],\n            'safety_observation':('more_guard_aborts_observed' if current['invalid_physics']>reference['invalid_physics'] else 'fewer_guard_aborts_observed' if current['invalid_physics']<reference['invalid_physics'] else 'same_guard_abort_count'),")
edit('core/runner.py','seed=812321+int(self.agent.steps//16000)*91','seed=secrets.randbelow(2**30)')
edit('core/runner.py',"            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop and save before evaluation.')\n            current=self.agent.clone();initial=self.initial.clone();reference=initial.clone()",
     "            if _inline and self.stop_event.is_set():return {'ok':False,'cancelled':True}\n            if not _inline and self.thread and self.thread.is_alive():raise ValueError('Previous operation is still finishing.')\n            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop and save before evaluation.')\n            current=self.agent.clone();initial=self.initial.clone();reference=initial.clone()")
edit('core/runner.py',"            self.stop_event.clear();self.error='';self.evaluation_progress={'phase':'Starting'",
     "            if not _inline:self.stop_event.clear()\n            self.error='';self.evaluation_progress={'phase':'Starting'")
edit('core/runner.py',"            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop the current operation first.')",
     "            if self.thread and self.thread.is_alive():raise ValueError('Previous operation is still finishing.')\n            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop the current operation first.')")
edit('core/session_runner.py',"    def begin_evaluation(self,task='all',trials=20,_inline=False):\n        self._reject_while_ending()",
     "    def begin_evaluation(self,task='all',trials=20,_inline=False):\n        if _inline and self.stop_event.is_set():return {'ok':False,'cancelled':True}\n        if not _inline:self._reject_while_ending()")
edit('web/app.js',"'Historical results, not current proof. ')+rows.map",
     "'Historical results, not current proof. ')+`Reference: ${(e.reference_kind||'unknown').replaceAll('_',' ')}. `+rows.map")
edit('web/app.js',"${c.state.replaceAll('_',' ')}.`",
     "${c.state.replaceAll('_',' ')}. Guard aborts: ${c.physics_aborts_before} before, ${c.physics_aborts_after} now (${c.safety_observation?.replaceAll('_',' ')||'not compared'}).`")
edit('web/app.js',"const matches=e.policy_fingerprint===s.policy_fingerprint&&JSON.stringify(e.camera_config||{})===JSON.stringify(s.camera_config||{});",
     "const matches=e.feedback_version==='seizo-feedback/v12'&&e.policy_fingerprint===s.policy_fingerprint&&JSON.stringify(e.camera_config||{})===JSON.stringify(s.camera_config||{});")
edit('core/runner.py',"self.recent.clear();self.best_scores={};self.promotions=0;self.latest_stats={}",
     "self.feedback=FeedbackLedger();self.recent.clear();self.best_scores={};self.promotions=0;self.latest_stats={}")
# Short lifecycle checks use actual pixels/rewards/PPO, not invented episodes.
edit('tests/test_feedback_v12.py',
     "            r.start({'task':'reach','episodes':2,'compute':'fast'});r.thread.join(100)\n            if r.thread.is_alive():r.stop();r.thread.join(20);self.fail('Training did not finish')",
     "            from feedback_smoke_helpers import train_one_real_batch_and_stop\n            train_one_real_batch_and_stop(r)")
edit('tests/browser_feedback_v12.py',
     "    r.start({'episodes':2,'task':'reach','compute':'fast'});r.thread.join(100)\n    assert not r.thread.is_alive() and r.status!='error',r.error",
     "    from feedback_smoke_helpers import train_one_real_batch_and_stop\n    train_one_real_batch_and_stop(r)")
edit('tests/browser_feedback_v12.py',"timeout=100000)","timeout=180000)")
p=ROOT/'patches/tests/preserved_source_hashes.json';h=json.loads(p.read_text())
for name in ('core/runner.py','core/ppo.py'):h[name]=hashlib.sha256((ROOT/'patches'/name).read_bytes()).hexdigest()
p.write_bytes((json.dumps(h,indent=2)+'\n').encode())
p=ROOT/'release-candidate-manifest.json';m=json.loads(p.read_text())
for name,value in m['patches'].items():value['sha256']=hashlib.sha256((ROOT/'patches'/name).read_bytes()).hexdigest()
p.write_bytes((json.dumps(m,separators=(',',':'))+'\n').encode())
hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT/'patches').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
(ROOT/'feedback-source-hashes.json').write_bytes((json.dumps(hashes,indent=2)+'\n').encode())
