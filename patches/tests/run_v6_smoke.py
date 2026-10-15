"""Reproducible local learning and all-task evaluation. No network or robot access."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core.runner import Runner
from core.world import TASKS
OUT=ROOT/'evidence';OUT.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as td:
 r=Runner(td);before=r.agent.signature();t=time.monotonic()
 r.start({'task':'all','episodes':50,'compute':'fast'})
 r.thread.join(120)
 if r.thread.is_alive():r.stop();r.thread.join(20);raise RuntimeError('Short training exceeded test time budget')
 assert r.status=='complete',r.error
 result={'model_id':r.snapshot()['model_id'],'training':r.last_run,'elapsed_training_seconds':time.monotonic()-t,
         'training_task_counts':r.counts,'before_hash':before,'after_hash':r.agent.signature()}
 assert before!=r.agent.signature()
 print(json.dumps({'training_done':result}),flush=True)
 r.begin_evaluation('all',5)
 while r.thread.is_alive():
  r.thread.join(5)
  print(json.dumps({'evaluation_progress':r.evaluation_progress}),flush=True)
 assert r.status!='error',r.error
 assert len(r.last_evaluation['by_task'])==len(TASKS)
 assert result['after_hash']==r.agent.signature()
 result['evaluation']=r.last_evaluation;result['experience']=r.experience_summary()
 result['total_seconds']=time.monotonic()-t;result['actual_cloud_calls']=0;result['physical_motion']=False
 (OUT/'v6_learning_smoke.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'complete':True,'elapsed_s':result['total_seconds'],'current':r.last_evaluation['current']}),flush=True)
