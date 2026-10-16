"""Bounded real camera-policy experiment. No synthetic success scores or cloud.

Starts a separate test policy, never replaces the user's existing checkpoint.
Training and held-out seeds are disjoint. Poor results are retained and reported.
"""
import json,sys,time,tempfile,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.view_policy import Agent
from core.view_world import ViewWorld
from core.ppo import rollout
from core.runner import evaluate
from core.learning_feedback import FeedbackLedger,update_evidence,compare_scores
root=Path(__file__).resolve().parents[1]
physical_attempts=[]
def audit(event,args):
    if event=='open' and str(args[0]).startswith(('/dev/tty','/dev/gpio','/dev/i2c','/sys/class/gpio')):
        physical_attempts.append(str(args[0]));raise RuntimeError('Device access forbidden in this experiment')
sys.addaudithook(audit)
a=Agent(seed=101);initial=a.clone();ledger=FeedbackLedger();start=time.monotonic()
options={'view_mode':'two','camera_config':{'profile':'fixed'},'learning_enabled':False}
seed=940031
before=evaluate(initial,'reach',5,seed=seed,world_factory=ViewWorld,world_options=options)
baseline=evaluate(initial,'reach',5,seed=seed,random_policy=True,world_factory=ViewWorld,world_options=options)
w=ViewWorld(seed=41723,task='reach',view_mode='two',camera_config={'profile':'fixed'},learning_enabled=True)
try:
    while a.episodes<30 and a.steps<4096 and time.monotonic()-start<360:
        def frame(world,info):
            if info is not None:ledger.observe(world.last_feedback)
        batch,episodes=rollout(a,w,64,on_episode=ledger.episode,on_frame=frame)
        if batch is not None and len(batch[0])>1:
            old={k:v.copy() for k,v in a.p.items()};fp=a.signature();updates=a.updates
            stats=a.update(batch,epochs=4)
            ledger.last_update=update_evidence(a,old,fp,updates,len(batch[0]),stats)
        print('ACTUAL CAMERA TRAINING',a.episodes,a.steps,a.updates,flush=True)
finally:w.close()
fp=a.signature();rng=copy.deepcopy(a.rng.bit_generator.state)
after=evaluate(a,'reach',5,seed=seed,world_factory=ViewWorld,world_options=options)
assert a.signature()==fp and a.rng.bit_generator.state==rng
with tempfile.TemporaryDirectory() as td:
    path=Path(td)/'policy.npz';a.save(path);loaded,_=Agent.load(path)
    assert loaded.signature()==a.signature()
proof={'scope':'One short real camera-simulator experiment, not the user checkpoint or skill certification',
       'task':'reach','training_seed':41723,'held_out_seed':seed,'camera_config':options,
       'training_episodes':a.episodes,'training_steps':a.steps,'optimizer_updates':a.updates,
       'before_fingerprint':initial.signature(),'after_fingerprint':a.signature(),
       'before':before,'after':after,'random':baseline,
       'comparison':compare_scores(after,before,baseline,'untrained_same_model'),
       'feedback':ledger.snapshot(),'cloud_requests':0,'physical_io_attempts':physical_attempts,
       'physical_motion':False,'scripted_teacher':False,'checkpoint_reload_verified':True,
       'elapsed_seconds':time.monotonic()-start}
(root/'feedback-experiment.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
assert a.updates>0 and a.signature()!=initial.signature()
print(json.dumps(proof),flush=True)
