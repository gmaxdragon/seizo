from pathlib import Path
from tempfile import TemporaryDirectory
import json,time
from core.camera_policy import Agent
from core.camera_world import CameraWorld
from core.ppo import rollout
a=Agent();before=a.signature();w=CameraWorld(seed=10,camera_config={'profile':'fixed'})
start=time.monotonic()
try:
 for _ in range(3):
  batch,completed=rollout(a,w,16)
  a.update(batch,epochs=2,minibatch=32)
 result={'observation_mode':'two_rendered_RGB_views','before_fingerprint':before,
         'after_fingerprint':a.signature(),'updates':a.updates,'movement_decisions':a.steps,
         'completed_episodes':a.episodes,'elapsed_seconds':time.monotonic()-start,
         'weights_changed':before!=a.signature(),'task_success_proven':False,
         'cloud_calls':0,'physical_motion':False,'note':'Short integration run, NOT evidence of learned manipulation.'}
 Path('evidence').mkdir(exist_ok=True)
 Path('evidence/camera_learning_smoke.json').write_text(json.dumps(result,indent=2))
 f=w.frame()
 import base64
 for name in ('overhead','wrist'):Path('evidence/'+name+'.png').write_bytes(base64.b64decode(f['cameras'][name]))
 print(json.dumps(result))
finally:w.close()
