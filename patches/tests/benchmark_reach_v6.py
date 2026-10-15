import sys,tempfile,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core.runner import Runner,evaluate
with tempfile.TemporaryDirectory() as td:
 r=Runner(td);begin=time.monotonic();pre=evaluate(r.agent,'reach',n=20,seed=123712)
 print(json.dumps({'before':pre}),flush=True)
 r.start({'task':'reach','episodes':500,'compute':'fast'})
 while r.thread.is_alive():
  r.thread.join(15);s=r.snapshot();print(json.dumps({k:s[k] for k in ('status','episodes','moves','updates','recent_success_rate')}),flush=True)
 assert r.status=='complete',r.error
 post=evaluate(r.agent,'reach',n=20,seed=123712);random=evaluate(r.agent,'reach',n=20,seed=123712,random_policy=True)
 report={'model_id':r.snapshot()['model_id'],'before':pre,'after':post,'random_actions':random,'learning':r.last_run,'seconds':time.monotonic()-begin,'physical_motion':False,'cloud_requests':0}
 (ROOT/'evidence/reach_learning_benchmark.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
