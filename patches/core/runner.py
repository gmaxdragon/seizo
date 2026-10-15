"""Local training lifecycle and honest, separately counted evaluation."""
from __future__ import annotations
import copy,json,os,secrets,threading,time,traceback
from pathlib import Path
from collections import deque
import numpy as np
from . import world as _approx_world
from .world import TASKS,TASK_LABELS
from .mjcf import MODEL_VERSION

# MuJoCo is an optional, downloaded-once CPU physics engine. A missing wheel
# is NEVER described as full physics. Check the status.physics field to know
# precisely which backend and joint model is active.
_backend_preference=os.environ.get('SEIZO_PHYSICS_ENGINE','auto').strip().lower()
if _backend_preference not in ('auto','mujoco','capsule'):
    raise ValueError('SEIZO_PHYSICS_ENGINE must be auto, mujoco, or capsule.')
try:
    if _backend_preference=='capsule':raise ImportError('Fast capsule mode selected')
    import mujoco as _mujoco
    from .mujoco_world import MuJoCoWorld as World
    _BACKEND_LABEL='MuJoCo full rigid body: joint inertia, force-limited motors, gravity and 3D shape contact; NOT calibrated'
    _approx_world.MODEL_ID=MODEL_VERSION
    MODEL_ID=MODEL_VERSION
except ImportError:
    if _backend_preference=='mujoco':
        raise RuntimeError('Realistic physics requested but MuJoCo is missing. Install once with: python -m pip install mujoco')
    World=_approx_world.World
    MODEL_ID=_approx_world.MODEL_ID
    _BACKEND_LABEL='Fast approximate contact solver (MuJoCo unavailable or fast mode requested)'
from .ppo import Agent,rollout


def atomic_json(path,obj):
    path=Path(path);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8');os.replace(tmp,path)


def evaluate(agent,task,n=24,seed=810017,random_policy=False):
    world=World(n=n,seed=seed,task=task);rng=np.random.default_rng(seed+10)
    done=np.zeros(n,bool);success=np.zeros(n,bool);ret=np.zeros(n);length=np.zeros(n,int);faults=np.zeros(n,bool)
    error=np.zeros(n);max_lift=np.zeros(n)
    for _ in range(220):
        action=rng.uniform(-1,1,(n,5)) if random_policy else agent.act(world.observation(),deterministic=True)[0]
        _,_,term,trunc,info=world.step(action);new=(~done)&(term|trunc)
        max_lift=np.where(~done,np.maximum(max_lift,info['lift']),max_lift)
        success[new]=info['success'][new];ret[new]=info['return'][new];length[new]=info['steps'][new]
        error[new]=info['object_distance' if TASKS.index(task)>=2 else 'distance'][new]
        faults[new]=info['fault'][new];done|=term|trunc
        if done.all():break
    return {'task':task,'trials':n,'successes':int(success.sum()),'success_rate':float(success.mean()),
        'mean_return':float(ret.mean()),'mean_moves':float(length.mean()),'mean_error_mm':float(error.mean()),
        'max_lift_mm':float(max_lift.max()),'seed':seed,'faults':int(faults.sum()),'weights_updated':False}


class Runner:
    def __init__(self,folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None
        self.status='ready';self.error='';self.agent=Agent();self.initial=Agent()
        self.stage=0;self.history=[];self.validation=None;self.last_evaluation=None;self.last_trace=None
        self.counts=[{'attempts':0,'successes':0} for _ in TASKS];self.recent=deque(maxlen=100)
        self.config={'episodes':1000000,'task':'curriculum','compute':'cad','fault_probability':0.0}
        self.target=1000000;self.started=time.monotonic();self.start_episodes=0;self.start_steps=0
        self.last_saved=None;self.latest_stats={};self.validation_serial=0;self.promotions=0
        self.trace_seq=0;self.watch_trace=[];self.generation=0;self.best_scores={};self.initial_hash=self.agent.signature()
        path=self.folder/'policy.npz'
        if path.exists():
            try:
                self.agent,extra=Agent.load(path)
                self.stage=int(extra.get('stage',0));self.config.update(extra.get('config',{}))
                self.target=int(extra.get('target',self.agent.episodes+1000000));self.counts=extra.get('counts',self.counts)
                self.history=extra.get('history',[]) [-200:];self.validation=extra.get('validation');self.initial_hash=extra.get('initial_hash',self.initial_hash)
                self.best_scores=extra.get('best_scores',{});self.initial=Agent(self.agent.seed)
                self.status='paused';self.last_saved=path.stat().st_mtime
            except ValueError as e:
                # The previous model had missing rigid-contact geometry; old
                # weights must not be silently reused or represented as valid.
                # Keep the exact old bytes, including any best checkpoints.
                if 'Incompatible policy.' in str(e):
                    backup=self.folder/('legacy_physics_checkpoint_'+time.strftime('%Y%m%d_%H%M%S'))
                    backup.mkdir(exist_ok=True)
                    for item in [path,*self.folder.glob('best_*.npz'),self.folder/'initial_policy.npz']:
                        if item.is_file():
                            os.replace(item,backup/item.name)
                    self.status='ready'
                    self.error='Policy from a different physics engine archived under '+backup.name+'. New physics requires new training.'
                else:
                    self.status='error';self.error='Saved policy was not loaded: '+str(e)
            except Exception as e:self.status='error';self.error='Saved policy was not loaded: '+str(e)

    def snapshot(self):
        with self.lock:
            elapsed=max(.1,time.monotonic()-self.started);epdiff=self.agent.episodes-self.start_episodes
            eps=epdiff/elapsed if self.status=='training' else None
            return {'status':self.status,'error':self.error,'episodes':self.agent.episodes,'moves':self.agent.steps,
                'updates':self.agent.updates,'parameters':int(sum(p.size for p in self.agent.p.values())),
                'target_episodes':self.target,'config':dict(self.config),'episodes_per_second':eps,
                'estimated_seconds_remaining':max(0,self.target-self.agent.episodes)/eps if eps and epdiff>=20 else None,
                'task':self.config['task'],'lesson':TASK_LABELS[TASKS.index(self.config['task'])] if self.config['task'] in TASKS else ('All five tasks' if self.config['task']=='all' else TASK_LABELS[self.stage]), 'stage':self.stage,
                'counts':copy.deepcopy(self.counts),'recent_success_rate':sum(self.recent)/len(self.recent) if self.recent else None,
                'last_saved':self.last_saved,'trace':copy.deepcopy(self.last_trace),
                'validation':copy.deepcopy(self.validation),'evaluation':copy.deepcopy(self.last_evaluation),
                'history':copy.deepcopy(self.history[-100:]),'stats':copy.deepcopy(self.latest_stats),
                'initial_fingerprint':self.initial_hash,'policy_fingerprint':self.agent.signature(),'best_scores':dict(self.best_scores),
                'physics':_BACKEND_LABEL,
                'physical_motion':False,'cloud_training_calls':0,'model_id':MODEL_ID}

    def save(self):
        with self.lock:
            self.agent.save(self.folder/'policy.npz',{'stage':self.stage,'config':self.config,'target':self.target,
                'counts':self.counts,'history':self.history[-200:],'validation':self.validation,'initial_hash':self.initial_hash,'best_scores':self.best_scores})
            self.last_saved=time.time()

    def start(self,config):
        if not isinstance(config,dict) or set(config)-{'episodes','task','compute','fault_probability'}:raise ValueError('Invalid training setting')
        cfg=dict(self.config);cfg.update(config)
        if type(cfg['episodes']) is not int or not 1<=cfg['episodes']<=1000000:raise ValueError('Episode budget must be 1 to 1,000,000.')
        if cfg['task'] not in TASKS+('curriculum','all'):raise ValueError('Unknown task')
        if cfg['compute'] not in ('cad','fast'):raise ValueError('Unknown computer-load mode')
        if not 0<=float(cfg['fault_probability'])<=.25:raise ValueError('Fault rate must be 0 to 25%.')
        with self.lock:
            if self.status in ('training','stopping','evaluating'):raise ValueError('Stop the current operation first.')
            if self.status=='error':raise ValueError(self.error+' Use a new empty data folder, do not overwrite your saved data.')
            resume=self.status=='paused' and all(cfg[k]==self.config[k] for k in ('episodes','task')) and self.target>self.agent.episodes
            if cfg['task']!=self.config['task']:
                self.agent.p['logstd'][:]=np.maximum(self.agent.p['logstd'],-.35)
            self.config=cfg;self.last_trace=None;self.last_evaluation=None
            if not resume:self.target=self.agent.episodes+cfg['episodes']
            self.stop_event.clear();self.status='training';self.error='';self.generation+=1
            self.started=time.monotonic();self.start_steps=self.agent.steps;self.start_episodes=self.agent.episodes
            self.thread=threading.Thread(target=self._train,daemon=True);self.thread.start()
        return {'ok':True,'resumed':resume,'target_episodes':self.target,'algorithm':'NumPy neural PPO','physical_motion':False}

    def _train(self):
        env=World(n=(2 if MODEL_ID==MODEL_VERSION else 8),seed=int(self.agent.rng.integers(1,2**30)),task=self.config['task'],fault_probability=self.config['fault_probability'])
        env.stage=self.stage;env.reset();trace=[env.frame()];last_save=time.monotonic();next_eval=self.agent.steps+40000
        try:
            if not (self.folder/'initial_policy.npz').exists():self.initial.save(self.folder/'initial_policy.npz')
            def complete(item):
                with self.lock:
                    c=self.counts[item['task']];c['attempts']+=1;c['successes']+=int(item['success']);self.recent.append(int(item['success']))
            def frame(world,info):
                nonlocal trace
                if info is None:
                    trace=[world.frame()];return
                trace.append(world.frame())
                terminal=info['success'][0] or info['fault'][0] or info['fallen'][0] or info['steps'][0]>=220
                if terminal:
                    self.trace_seq+=1
                    with self.lock:self.last_trace={'id':self.trace_seq,'source':'training exploration','episode':self.agent.episodes+1,
                        'frames':trace,'success':bool(info['success'][0]),'fault':bool(info['fault'][0]),'weights_updated':False}
                    trace=[]
            def stopped():return self.stop_event.is_set() or self.agent.episodes>=self.target
            while not stopped():
                started=time.monotonic()
                batch,completed=rollout(self.agent,env,96,on_episode=complete,on_frame=frame,stop=stopped)
                if batch is not None and len(batch[0])>1:
                    # Finish this bounded PPO update before checkpointing, unless user stopped.
                    with self.lock:
                        stats=self.agent.update(batch,epochs=4,stop=self.stop_event.is_set)
                        if stats:self.latest_stats=stats[-1]
                if time.monotonic()-last_save>25:self.save();last_save=time.monotonic()
                if self.agent.steps>=next_eval and not stopped():
                    clone=self.agent.clone();task=TASKS[self.stage] if self.config['task']=='curriculum' else (self.config['task'] if self.config['task'] in TASKS else 'reach')
                    val=evaluate(clone,task,24,seed=812321)
                    with self.lock:
                        self.validation=val
                        self.history.append({'episodes':self.agent.episodes,'moves':self.agent.steps,**val});self.history=self.history[-200:]
                        # Training curriculum changes only after a held-out validation result.
                        if self.config['task']=='curriculum' and val['success_rate']>=.7:
                            self.promotions+=1
                            if self.promotions>=2 and self.stage<4:
                                self.stage+=1;self.promotions=0;env.stage=self.stage
                                # Broaden exploration for a newly introduced skill.
                                # Learned means are kept; no target action is injected.
                                self.agent.p['logstd'][:]=np.maximum(self.agent.p['logstd'],-.35)
                        else:self.promotions=0
                        if task not in self.best_scores or val['success_rate']>self.best_scores[task]:
                            self.best_scores[task]=val['success_rate'];self.agent.save(self.folder/('best_'+task+'.npz'),{'validation':val})
                    self.save();next_eval=self.agent.steps+40000
                if self.config['compute']=='cad':self.stop_event.wait(min(.5,(time.monotonic()-started)*.45))
            self.save()
            with self.lock:self.status='paused' if self.stop_event.is_set() else 'complete'
        except Exception as e:
            with self.lock:self.error=str(e);self.status='error'
            (self.folder/'last_error.txt').write_text(traceback.format_exc())

    def stop(self):
        self.stop_event.set()
        with self.lock:
            self.generation+=1
            if self.status=='training':self.status='stopping'
        return {'ok':True,'physical_motion':False}

    def shutdown(self):
        self.stop()
        if self.thread:self.thread.join(timeout=25)
        if self.thread and self.thread.is_alive():raise RuntimeError('Training is still saving. Do not delete the data folder.')
        if self.status!='error':self.save()

    def reset(self):
        with self.lock:
            if self.status in ('training','stopping','evaluating'):raise ValueError('Stop and wait for Saved before resetting.')
            archive=self.folder/('backup-'+str(time.time_ns()));archive.mkdir()
            for p in list(self.folder.glob('*.npz'))+list(self.folder.glob('evaluation.json')):
                p.replace(archive/p.name)
            self.agent=Agent();self.initial=Agent();self.initial_hash=self.agent.signature();self.stage=0
            self.counts=[{'attempts':0,'successes':0} for _ in TASKS];self.history=[];self.last_trace=None;self.validation=None;self.last_evaluation=None
            self.recent.clear();self.best_scores={};self.promotions=0;self.latest_stats={};self.target=self.config['episodes'];self.status='ready';self.error='';self.save()
        return {'ok':True,'backup':archive.name,'episodes':0}

    def trial(self,task='reach',source='current',fault=False,seed=None):
        if task not in TASKS:raise ValueError('Unknown task')
        with self.lock:
            if self.status in ('training','stopping','evaluating'):raise ValueError('Stop and save first, then watch a frozen policy test.')
            if self.status=='error':raise ValueError(self.error)
            if source not in ('current','untrained','best'):raise ValueError('Unknown policy')
            agent=self.initial.clone() if source=='untrained' else self.agent.clone()
            if source=='best':
                path=self.folder/('best_'+task+'.npz')
                if not path.exists():raise ValueError('No validated best checkpoint for this task yet.')
                agent,_=Agent.load(path)
        if seed is not None and (type(seed) is not int or not 0<=seed<2**31):raise ValueError('Invalid scenario seed')
        seed=seed if seed is not None else secrets.randbelow(2**30)
        w=World(1,seed,task,fault_probability=1. if fault else 0.)
        if fault:w.fault_at[0]=3 # Force a watch-test fault before any task can finish.
        frames=[w.frame()];success=False;failed=False;signature=agent.signature();rng=np.random.default_rng(seed+1)
        for _ in range(220):
            actions=agent.act(w.observation(),deterministic=agent.updates>0,rng=rng)[0]
            _,_,term,trunc,info=w.step(actions);frames.append(w.frame())
            if term[0] or trunc[0]:success=bool(info['success'][0]);failed=bool(info['fault'][0]);break
        assert signature==agent.signature()
        return {'frames':frames,'success':success,'fault':failed,'source':source,'seed':seed,
                'task':task,'policy_updates':agent.updates,'policy_fingerprint':signature,'weights_updated':False,
                'physical_motion':False,'episode_moves':len(frames)-1}

    def begin_evaluation(self,task):
        if task not in TASKS+('all',):raise ValueError('Unknown task')
        with self.lock:
            if self.status in ('training','stopping','evaluating'):raise ValueError('Stop and save before evaluation.')
            current=self.agent.clone();initial=self.initial.clone();self.status='evaluating';before=current.signature()
        def run():
            try:
                seed=secrets.randbelow(2**30);rows=[]
                for index,name in enumerate(TASKS if task=='all' else (task,)):
                    now=evaluate(current,name,40,seed+index*1000)
                    baseline=evaluate(initial,name,40,seed+index*1000,random_policy=True)
                    rows.append({'current':now,'random_actions':baseline})
                if len(rows)==1:result=dict(rows[0])
                else:
                    def combine(key):
                        vals=[r[key] for r in rows];n=sum(v['trials'] for v in vals);success=sum(v['successes'] for v in vals)
                        return {'task':'all','trials':n,'successes':success,'success_rate':success/n,'mean_error_mm':None}
                    result={'current':combine('current'),'random_actions':combine('random_actions'),'by_task':rows}
                result.update({'fingerprint_unchanged':before==current.signature(),'policy_fingerprint':before,'episodes_at_test':self.agent.episodes,
                    'weights_updated':False,'note':'Fresh sampled simulation scenarios, never used in gradient updates. Not physical validation.'})
                with self.lock:self.last_evaluation=result;self.status='paused' if self.agent.steps else 'ready'
                atomic_json(self.folder/'evaluation.json',result)
            except Exception as e:
                with self.lock:self.status='error';self.error=str(e)
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return {'ok':True}
