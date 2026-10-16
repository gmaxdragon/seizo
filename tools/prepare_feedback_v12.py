"""Prepare v12 plus cancellation/fresh-validation review, before any tests."""
from pathlib import Path
import runpy,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'tools/apply_feedback_v12.py'),run_name='__main__')
def edit(name,old,new):
    p=ROOT/'patches'/name;s=p.read_text(encoding='utf-8')
    assert s.count(old)==1,(name,s.count(old))
    p.write_bytes(s.replace(old,new).encode('utf-8'))
edit('core/runner.py','seed=812321+int(self.agent.steps//16000)*91','seed=secrets.randbelow(2**30)')
edit('core/runner.py',"            current=self.agent.clone();initial=self.initial.clone();reference=initial.clone()",
     "            if _inline and self.stop_event.is_set():return {'ok':False,'cancelled':True}\n            current=self.agent.clone();initial=self.initial.clone();reference=initial.clone()")
edit('core/runner.py',"            self.stop_event.clear();self.error='';self.evaluation_progress={'phase':'Starting'",
     "            if not _inline:self.stop_event.clear()\n            self.error='';self.evaluation_progress={'phase':'Starting'")
edit('core/session_runner.py',"    def begin_evaluation(self,task='all',trials=20,_inline=False):\n        self._reject_while_ending()",
     "    def begin_evaluation(self,task='all',trials=20,_inline=False):\n        if _inline and self.stop_event.is_set():return {'ok':False,'cancelled':True}\n        if not _inline:self._reject_while_ending()")
edit('web/app.js',"'Historical results, not current proof. ')+rows.map",
     "'Historical results, not current proof. ')+`Reference: ${(e.reference_kind||'unknown').replaceAll('_',' ')}. `+rows.map")
# Recalculate integrity metadata for reviewed bytes, without weakening checks.
p=ROOT/'patches/tests/preserved_source_hashes.json';h=json.loads(p.read_text())
for name in ('core/runner.py','core/ppo.py'):h[name]=hashlib.sha256((ROOT/'patches'/name).read_bytes()).hexdigest()
p.write_bytes((json.dumps(h,indent=2)+'\n').encode())
p=ROOT/'release-candidate-manifest.json';m=json.loads(p.read_text())
for name,value in m['patches'].items():value['sha256']=hashlib.sha256((ROOT/'patches'/name).read_bytes()).hexdigest()
p.write_bytes((json.dumps(m,separators=(',',':'))+'\n').encode())
hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT/'patches').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
(ROOT/'feedback-source-hashes.json').write_bytes((json.dumps(hashes,indent=2)+'\n').encode())
