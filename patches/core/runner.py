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
    _BACKEND_LABEL=f'MuJoCo {_mujoco.__version__}: axial roll, linked jaws, forces and contact; NOT physically calibrated'
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



def evaluate(agent,task,n=20,seed=810017,random_policy=False,stop=None,fault_probability=0.0,
             world_factory=World,world_options=None,on_trial=None,on_timing=None):
    """Frozen policy. Camera cases run sequentially to bound GPU/CPU memory."""
    if task not in TASKS or type(n) is not int or not 1<=n<=200:raise ValueError('Invalid evaluation task/count.')
    signature=agent.signature();records=[]
    for trial in range(n):
        if stop and stop():raise InterruptedError('Evaluation stopped; no partial pass claimed.')
        trial_started=time.perf_counter()
        w=world_factory(n=1,seed=seed+trial*97,task=task,fault_probability=fault_probability,**(world_options or {}))
        rng=np.random.default_rng(seed+trial*97+10)
        try:
            for _ in range(220):
                if stop and stop():raise InterruptedError('Evaluation stopped; no partial pass claimed.')
                a=rng.uniform(-1,1,(1,5)) if random_policy else agent.act(w.observation(),deterministic=True)[0]
                _,_,term,trunc,info=w.step(a)
                if term[0] or trunc[0]:
                    records.append({key:np.asarray(value)[0].item() for key,value in info.items()
                                    if np.asarray(value).ndim==1})
                    break
            else:raise RuntimeError('Unfinished evaluation trial')
        finally:
            if hasattr(w,'close'):w.close()
        if on_timing:on_timing(task,random_policy,time.perf_counter()-trial_started,fault_probability)
        if on_trial:on_trial(trial+1,n)
    assert signature==agent.signature(),'Evaluation altered neural weights'
    k=sum(int(r['success']) for r in records);faults=sum(int(r['fault']) for r in records)
    rate=k/n;z=1.96;den=1+z*z/n
    mid=(rate+z*z/(2*n))/den;half=z*((rate*(1-rate)/n+z*z/(4*n*n))**.5)/den
    return {'task':task,'trials':n,'successes':k,'failures':n-k-faults,'success_rate':rate,
        'success_interval_95':[max(0.,mid-half),min(1.,mid+half)],
        'mean_return':float(np.mean([r['return'] for r in records])),
        'mean_moves':float(np.mean([r['steps'] for r in records])),
        'mean_error_mm':float(np.mean([r['object_distance' if TASKS.index(task)>=2 else 'distance'] for r in records])),
        'mean_object_angle_error_degrees':float(np.mean([r.get('object_angle_error',0.) for r in records])),
        'max_lift_mm':float(max(r['lift'] for r in records)), 'seed':seed,'faults':faults,
        'invalid_physics':sum(int(r.get('invalid_physics',False)) for r in records),
        'observation_mode':'two_rgb_cameras' if getattr(world_factory,'image_policy',False) else 'privileged_simulator_state',
        'input_source':'simulated_overhead_and_wrist_rgb' if getattr(world_factory,'image_policy',False) else 'simulator_state',
        'sensor_condition':('two_mounted_cameras' if (world_options or {}).get('view_mode')=='two' else 'training_view_setting'),
        'weights_updated':False,'physical_motion':False}


class Runner:
    def __init__(self,folder,agent_factory=Agent,world_factory=World):
        self.Agent=agent_factory;self.World=world_factory
        self.is_camera=bool(getattr(world_factory,'image_policy',False))
        self.model_id=getattr(agent_factory,'POLICY_MODEL_ID',MODEL_ID)
        self.camera_config={}
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None
        self.status='ready';self.error='';self.agent=self.Agent();self.initial=self.Agent()
        self.stage=0;self.history=[];self.validation=None;self.last_evaluation=None;self.last_trace=None
        self.counts=[{'attempts':0,'successes':0,'safety_aborts':0} for _ in TASKS];self.recent=deque(maxlen=100)
        self.config={'episodes':1000,'task':'curriculum','compute':'cad','fault_probability':0.0}
        self.target=1000;self.started=time.monotonic();self.start_episodes=0;self.start_steps=0
        self.preview_frame=None;self.preview_serial=0
        self.last_saved=None;self.saved_fingerprint=None;self.save_verified=False;self.latest_stats={};self.validation_serial=0;self.promotions=0
        self.evaluation_progress=None;self.last_run=None
        self.trace_seq=0;self.watch_trace=[];self.generation=0;self.best_scores={};self.initial_hash=self.agent.signature()
        path=self.folder/'policy.npz'
        if path.exists():
            try:
                self.agent,extra=self.Agent.load(path)
                self.stage=int(extra.get('stage',0));self.config.update(extra.get('config',{}));self.camera_config=extra.get('camera_config',{})
                self.target=int(extra.get('target',self.agent.episodes+1000));self.counts=extra.get('counts',self.counts)
                self.history=extra.get('history',[]) [-200:];self.validation=extra.get('validation');self.initial_hash=extra.get('initial_hash',self.initial_hash)
                self.best_scores=extra.get('best_scores',{});self.initial=self.Agent(self.agent.seed)
                self.status='paused';self.last_saved=path.stat().st_mtime;self.saved_fingerprint=self.agent.signature();self.save_verified=True
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

        report=self.folder/'evaluation.json'
        if report.exists():
            try:
                saved=json.loads(report.read_text())
                if saved.get('model_id')==self.model_id:self.last_evaluation=saved
            except (ValueError,OSError):pass

    def snapshot(self):
        with self.lock:
            elapsed=max(.1,time.monotonic()-self.started);epdiff=self.agent.episodes-self.start_episodes
            eps=epdiff/elapsed if self.status=='training' else None
            return {'status':self.status,'error':self.error,'episodes':self.agent.episodes,'moves':self.agent.steps,
                'updates':self.agent.updates,'parameters':int(sum(p.size for p in self.agent.p.values())),
                'target_episodes':self.target,'config':dict(self.config),'episodes_per_second':eps,
                'estimated_seconds_remaining':max(0,self.target-self.agent.episodes)/eps if eps and epdiff>=20 else None,
                'task':self.config['task'],'lesson':TASK_LABELS[TASKS.index(self.config['task'])] if self.config['task'] in TASKS else ('All seven tasks' if self.config['task']=='all' else TASK_LABELS[self.stage]), 'stage':self.stage,
                'counts':copy.deepcopy(self.counts),'recent_success_rate':sum(self.recent)/len(self.recent) if self.recent else None,
                'last_saved':self.last_saved,'save_verified':self.save_verified and self.saved_fingerprint==self.agent.signature(),'saved_fingerprint':self.saved_fingerprint,
                'observation_mode':'two_rgb_cameras' if self.is_camera else 'privileged_simulator_state',
                'input_source':'simulated_overhead_and_wrist_rgb' if self.is_camera else 'simulator_state',
                'uses_real_cameras':False,
                'camera_config':dict(self.camera_config),'observation_contract':getattr(self.World,'observation_contract',None),
                'live_camera':({'serial':self.preview_serial,'cameras':copy.deepcopy(self.preview_frame.get('cameras')),
                                'safety_abort':self.preview_frame.get('safety_abort')} if self.preview_frame else None),
                'checkpoint_name':str(self.folder/'policy.npz'),'skill_evidence':self.skill_evidence(),'trace':copy.deepcopy(self.last_trace),
                'validation':copy.deepcopy(self.validation),'evaluation':copy.deepcopy(self.last_evaluation),
                'history':copy.deepcopy(self.history[-100:]),'stats':copy.deepcopy(self.latest_stats),
                'evaluation_progress':copy.deepcopy(self.evaluation_progress),
                'parameters_changed_from_initial':sum(int(np.count_nonzero(self.agent.p[k]!=self.initial.p[k])) for k in self.agent.p),
                'weights_changed_from_initial':self.agent.signature()!=self.initial_hash,
                'last_run':copy.deepcopy(self.last_run),
                'initial_fingerprint':self.initial_hash,'policy_fingerprint':self.agent.signature(),'best_scores':dict(self.best_scores),
                'physics':_BACKEND_LABEL,
                'physical_motion':False,'cloud_training_calls':0,'model_id':self.model_id}

    def save(self):
        with self.lock:
            self.agent.save(self.folder/'policy.npz',{'stage':self.stage,'config':self.config,'target':self.target,
                'counts':self.counts,'history':self.history[-200:],'validation':self.validation,'initial_hash':self.initial_hash,'best_scores':self.best_scores,'camera_config':self.camera_config})
            loaded,_=self.Agent.load(self.folder/'policy.npz')
            same=loaded.signature()==self.agent.signature()
            same=same and all(np.array_equal(loaded.m[k],self.agent.m[k]) and np.array_equal(loaded.v[k],self.agent.v[k]) for k in self.agent.p)
            same=same and (loaded.t,loaded.updates,loaded.steps,loaded.episodes)==(self.agent.t,self.agent.updates,self.agent.steps,self.agent.episodes)
            same=same and loaded.rng.bit_generator.state==self.agent.rng.bit_generator.state
            if not same:raise RuntimeError('Checkpoint weights, optimizer or counters did not reload correctly')
            self.last_saved=time.time();self.saved_fingerprint=loaded.signature();self.save_verified=True
            atomic_json(self.folder/'last_save_receipt.json',{'saved_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                'model_id':self.model_id,'fingerprint':self.saved_fingerprint,'updates':self.agent.updates,
                'episodes':self.agent.episodes,'moves':self.agent.steps,'verified_by_reload':True})

    def start(self,config):
        if not isinstance(config,dict) or set(config)-{'episodes','task','compute','fault_probability'}:raise ValueError('Invalid training setting')
        cfg=dict(self.config);cfg.update(config)
        if type(cfg['episodes']) is not int or not 1<=cfg['episodes']<=1000000:raise ValueError('Episode budget must be 1 to 1,000,000.')
        if cfg['task'] not in TASKS+('curriculum','all'):raise ValueError('Unknown task')
        if cfg['compute'] not in ('cad','fast'):raise ValueError('Unknown computer-load mode')
        if not 0<=float(cfg['fault_probability'])<=.25:raise ValueError('Fault rate must be 0 to 25%.')
        with self.lock:
            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop the current operation first.')
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
        env=None
        try:
            env=self.World(n=getattr(self.World,'training_envs',(2 if MODEL_ID==MODEL_VERSION else 8)),seed=int(self.agent.rng.integers(1,2**30)),task=self.config['task'],fault_probability=self.config['fault_probability'],**self.world_options())
            env.stage=self.stage;env.reset();trace=[env.frame()];last_save=time.monotonic();next_eval=self.agent.steps+16000
            with self.lock:self.preview_frame=trace[0];self.preview_serial+=1
            start_hash=self.agent.signature();start_updates=self.agent.updates
            if not (self.folder/'initial_policy.npz').exists():self.initial.save(self.folder/'initial_policy.npz')
            def complete(item):
                with self.lock:
                    c=self.counts[item['task']];c['attempts']+=1;c['successes']+=int(item['success']);self.recent.append(int(item['success']));c['safety_aborts']=c.get('safety_aborts',0)+int(item.get('safety_abort',False))
                if hasattr(self,'record_training_episode'):self.record_training_episode(item)
            def frame(world,info):
                nonlocal trace
                if info is None:
                    trace=[world.frame()]
                    with self.lock:self.preview_frame=trace[0];self.preview_serial+=1
                    return
                trace.append(world.frame())
                if len(trace)%8==0:
                    with self.lock:self.preview_frame=trace[-1];self.preview_serial+=1
                terminal=info['success'][0] or info['fault'][0] or info['fallen'][0] or info['steps'][0]>=220 or bool(info.get('invalid_physics',[False])[0])
                if terminal:
                    self.trace_seq+=1
                    with self.lock:
                        self.last_trace={'id':self.trace_seq,'source':'training exploration','episode':self.agent.episodes+1,
                            'frames':trace,'success':bool(info['success'][0]),'fault':bool(info['fault'][0]),
                            'safety_abort':trace[-1].get('safety_abort',''),'weights_updated':False}
                        self.preview_frame=trace[-1];self.preview_serial+=1
                    trace=[]
            def stopped():return self.stop_event.is_set() or self.agent.episodes>=self.target
            while not stopped():
                started=time.monotonic()
                if hasattr(self,'prepare_training_world'):self.prepare_training_world(env)
                batch,completed=rollout(self.agent,env,96,on_episode=complete,on_frame=frame,stop=stopped)
                if batch is not None and len(batch[0])>1:
                    # Finish this bounded PPO update before checkpointing, unless user stopped.
                    with self.lock:
                        stats=self.agent.update(batch,epochs=4,stop=self.stop_event.is_set)
                        if stats:self.latest_stats=stats[-1]
                if time.monotonic()-last_save>25:self.save();last_save=time.monotonic()
                if self.agent.steps>=next_eval and not stopped():
                    clone=self.agent.clone();task=TASKS[self.stage] if self.config['task']=='curriculum' else (self.config['task'] if self.config['task'] in TASKS else 'reach')
                    val=evaluate(clone,task,getattr(self,'validation_trials',5 if self.is_camera else 24),seed=812321+int(self.agent.steps//16000)*91,stop=self.stop_event.is_set,world_factory=self.World,world_options=self.evaluation_options(),on_timing=getattr(self,'record_trial_time',None))
                    if hasattr(self,'after_validation'):self.after_validation(val,env)
                    with self.lock:
                        self.validation=val
                        self.history.append({'episodes':self.agent.episodes,'moves':self.agent.steps,**val});self.history=self.history[-200:]
                        # Training curriculum changes only after a held-out validation result.
                        if self.config['task']=='curriculum' and val['success_rate']>=.7:
                            self.promotions+=1
                            if self.promotions>=2 and self.stage<len(TASKS)-1:
                                self.stage+=1;self.promotions=0;env.stage=self.stage
                                # Broaden exploration for a newly introduced skill.
                                # Learned means are kept; no target action is injected.
                                self.agent.p['logstd'][:]=np.maximum(self.agent.p['logstd'],-.35)
                        else:self.promotions=0
                        if task not in self.best_scores or val['success_rate']>self.best_scores[task]:
                            self.best_scores[task]=val['success_rate'];self.agent.save(self.folder/('best_'+task+'.npz'),{'validation':val})
                    self.save();next_eval=self.agent.steps+16000
                if self.config['compute']=='cad':self.stop_event.wait(min(.5,(time.monotonic()-started)*.45))
            with self.lock:
                self.last_run={'before_fingerprint':start_hash,'after_fingerprint':self.agent.signature(),
                               'optimizer_updates':self.agent.updates-start_updates,
                               'movements':self.agent.steps-self.start_steps,'episodes':self.agent.episodes-self.start_episodes,
                               'weights_updated':start_hash!=self.agent.signature(),'cloud_requests':0}
            self.save()
            with self.lock:self.status='paused' if self.stop_event.is_set() else 'complete'
        except InterruptedError:
            if env is not None:
                with self.lock:self.last_run={'before_fingerprint':start_hash,'after_fingerprint':self.agent.signature(),
                    'optimizer_updates':self.agent.updates-start_updates,'movements':self.agent.steps-self.start_steps,
                    'episodes':self.agent.episodes-self.start_episodes,'weights_updated':start_hash!=self.agent.signature(),
                    'cloud_requests':0,'stopped_during_validation':True}
            self.save()
            with self.lock:self.status='paused'
        except Exception as e:
            with self.lock:self.error=str(e);self.status='error'
            (self.folder/'last_error.txt').write_text(traceback.format_exc())
        finally:
            if env is not None and hasattr(env,'close'):env.close()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            self.generation+=1
            if self.status in ('training','evaluating','watching'):self.status='stopping'
            else:self.save()
        return {'ok':True,'physical_motion':False}

    def shutdown(self):
        self.stop()
        if self.thread:self.thread.join(timeout=25)
        if self.thread and self.thread.is_alive():raise RuntimeError('Training is still saving. Do not delete the data folder.')
        if self.status!='error':self.save()

    def reset(self):
        with self.lock:
            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop and wait for Saved before resetting.')
            archive=self.folder/('backup-'+str(time.time_ns()));archive.mkdir()
            for p in list(self.folder.glob('*.npz'))+list(self.folder.glob('evaluation.json')):
                p.replace(archive/p.name)
            self.agent=self.Agent();self.initial=self.Agent();self.initial_hash=self.agent.signature();self.stage=0
            self.counts=[{'attempts':0,'successes':0,'safety_aborts':0} for _ in TASKS];self.history=[];self.last_trace=None;self.validation=None;self.last_evaluation=None
            self.recent.clear();self.best_scores={};self.promotions=0;self.latest_stats={};self.target=self.config['episodes'];self.status='ready';self.error='';self.save()
        return {'ok':True,'backup':archive.name,'episodes':0}


    def trial(self,task='reach',source='current',fault=False,seed=None):
        if task not in TASKS:raise ValueError('Unknown task')
        if seed is not None and (type(seed) is not int or not 0<=seed<2**31):raise ValueError('Invalid scenario seed')
        with self.lock:
            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop and save before watching a test.')
            if self.status=='error':raise ValueError(self.error)
            if source not in ('current','untrained','best'):raise ValueError('Unknown policy')
            agent=self.initial.clone() if source=='untrained' else self.agent.clone()
            if source=='best':
                path=self.folder/('best_'+task+'.npz')
                if not path.exists():raise ValueError('No evaluated checkpoint for this task yet.')
                agent,_=self.Agent.load(path)
            self.stop_event.clear();self.status='watching'
        if seed is not None and (type(seed) is not int or not 0<=seed<2**31):raise ValueError('Invalid scenario seed')
        seed=seed if seed is not None else secrets.randbelow(2**30)
        w=None
        try:
            w=self.World(1,seed,task,fault_probability=1. if fault else 0.,**self.world_options())
            if fault:w.fault_at[0]=3
            frames=[w.frame()];success=False;failed=False;signature=agent.signature();rng=np.random.default_rng(seed+1)
            with self.lock:self.preview_frame=frames[0];self.preview_serial+=1
            for _ in range(220):
                if self.stop_event.is_set():raise InterruptedError('Watch test cancelled, not a pass.')
                actions=agent.act(w.observation(),deterministic=agent.updates>0,rng=rng)[0]
                _,_,term,trunc,info=w.step(actions);frames.append(w.frame())
                if len(frames)%8==0:
                    with self.lock:self.preview_frame=frames[-1];self.preview_serial+=1
                if term[0] or trunc[0]:success=bool(info['success'][0]);failed=bool(info['fault'][0]);break
            assert signature==agent.signature()
            return {'frames':frames,'success':success,'fault':failed,'source':source,'seed':seed,
                    'task':task,'policy_updates':agent.updates,'policy_fingerprint':signature,'weights_updated':False,
                    'observation_mode':'two_rgb_cameras' if self.is_camera else 'privileged_simulator_state',
                    'physical_motion':False,'episode_moves':len(frames)-1}
        finally:
            if w is not None and hasattr(w,'close'):w.close()
            try:
                self.save()
                with self.lock:self.status='paused' if self.agent.steps else 'ready'
            except Exception as e:
                with self.lock:self.status='error';self.error='Save failed: '+str(e)
                raise

    def experience_summary(self):
        """A small local empirical memory. Never API keys, photos, device addresses or commands."""
        path=self.folder/'experience.json'
        if path.exists():
            try:
                data=json.loads(path.read_text())
                if data.get('model_id')==self.model_id and data.get('policy_fingerprint')==self.agent.signature():return data
            except (OSError,ValueError,AttributeError):pass
        return {'schema':'seizo-experience/v1','model_id':self.model_id,'policy_fingerprint':self.agent.signature(),
                'training_episodes':self.agent.episodes,'optimizer_updates':self.agent.updates,
                'evaluation_available':False,'message':'No current frozen evaluation. Run Test all tasks before requesting AI advice.',
                'physical_validation':False,'cloud_model_finetuned':False}

    def begin_evaluation(self,task='all',trials=20):
        minimum=1 if self.is_camera else 5
        if task not in TASKS+('all',) or type(trials)is not int or not minimum<=trials<=100:
            raise ValueError(f'Choose {minimum} to 100 trials per task.')
        with self.lock:
            if self.status in ('training','stopping','evaluating','watching'):raise ValueError('Stop and save before evaluation.')
            current=self.agent.clone();initial=self.initial.clone();self.status='evaluating';self.last_evaluation=None;before=current.signature()
            self.stop_event.clear();self.error='';self.evaluation_progress={'phase':'Starting','completed':0,'total':len(TASKS) if task=='all' else 1}
        def run():
            try:
                seed=secrets.randbelow(2**30);rows=[];names=TASKS if task=='all' else (task,)
                for index,name in enumerate(names):
                    for label in ('policy','random'):
                        with self.lock:self.evaluation_progress={'phase':name+' / '+label,'completed':index,'total':len(names)}
                        value=evaluate(current if label=='policy' else initial,name,trials,seed+index*1000,
                                       random_policy=(label=='random'),stop=self.stop_event.is_set,world_factory=self.World,world_options=self.evaluation_options(),on_trial=self._eval_trial,on_timing=getattr(self,'record_trial_time',None))
                        if label=='policy':now=value
                        else:baseline=value
                    rows.append({'current':now,'random_actions':baseline})
                # Fault exercise stays separate from clean task scores.
                faults=evaluate(current,'reach',max(5,trials//2),seed+9000,stop=self.stop_event.is_set,fault_probability=1.,world_factory=self.World,world_options=self.evaluation_options(),on_timing=getattr(self,'record_trial_time',None))
                def combine(key):
                    vals=[r[key] for r in rows];n=sum(v['trials'] for v in vals);passed=sum(v['successes'] for v in vals)
                    return {'task':task,'trials':n,'successes':passed,'success_rate':passed/n,
                            'mean_error_mm':float(np.mean([v['mean_error_mm'] for v in vals]))}
                from .proposal_policy import runtime_contract
                result={'proposal_contract_sha256':runtime_contract(self.camera_config) if self.is_camera else None,
                        'model_id':self.model_id,'observation_mode':'two_rgb_cameras' if self.is_camera else 'privileged_simulator_state','current':combine('current'),'random_actions':combine('random_actions'),'by_task':rows,'fault_test':faults,
                        'fingerprint_unchanged':before==current.signature(),'policy_fingerprint':before,'episodes_at_test':current.episodes,
                        'weights_updated':False,'physical_motion':False,'camera_config':dict(self.camera_config),
                        'note':'Fresh paired physics scenarios; faults scored separately. Finite sample, not hardware certification.'}
                memory={'schema':'seizo-experience/v1','model_id':self.model_id,'policy_fingerprint':before,'evaluation_available':True,
                        'training_episodes':current.episodes,'optimizer_updates':current.updates,
                        'evaluated_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                        'tasks':[{'task':r['current']['task'],'trials':trials,'successes':r['current']['successes'],
                                  'random_successes':r['random_actions']['successes'],
                                  'success_interval_95':r['current']['success_interval_95'],
                                  'mean_error_mm':r['current']['mean_error_mm'],
                                  'mean_orientation_error_degrees':r['current']['mean_object_angle_error_degrees']}
                                 for r in rows],
                        'physical_validation':False,'cloud_model_finetuned':False}
                with self.lock:
                    self.last_evaluation=result;self.evaluation_progress={'phase':'Complete','completed':len(names),'total':len(names)}
                    self.status='paused' if self.agent.steps else 'ready'
                atomic_json(self.folder/'evaluation.json',result);atomic_json(self.folder/'experience.json',memory)
                self.save()
            except InterruptedError:
                try:
                    self.save()
                    with self.lock:self.status='paused' if self.agent.steps else 'ready';self.evaluation_progress={'phase':'Stopped, not complete','completed':len(rows),'total':len(names)}
                except Exception as e:
                    with self.lock:self.status='error';self.error='Save failed: '+str(e)
            except Exception as e:
                with self.lock:self.status='error';self.error=str(e)
                (self.folder/'last_error.txt').write_text(traceback.format_exc())
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start();return {'ok':True,'cloud_requests':0}

    def evaluation_options(self):
        return self.world_options()

    def world_options(self):
        return {'camera_config':self.camera_config} if self.is_camera else {}

    def set_cameras(self,config):
        from .camera_world import validate_config
        value=validate_config(config)
        with self.lock:
            if self.status in ('training','stopping','evaluating','watching'):
                raise ValueError('STOP & save before changing the camera setup')
            self.camera_config=value
            self.save()
        return {'ok':True,'camera_config':dict(value),'physical_motion':False}

    def camera_preview(self,resample=False):
        if not self.is_camera:raise ValueError('Camera mode is not selected')
        with self.lock:
            active=self.status in ('training','stopping','evaluating','watching')
            if active:
                if resample:raise ValueError('Stop before sampling another camera setup')
                if self.preview_frame:return copy.deepcopy(self.preview_frame)
                raise ValueError('The first camera frame is being captured. Retry shortly.')
        w=self.World(1,secrets.randbelow(2**30),'reach',**self.world_options())
        try:
            value=w.frame()
            with self.lock:self.preview_frame=value;self.preview_serial+=1
            return value
        finally:w.close()

    def _eval_trial(self,completed,total):
        with self.lock:
            if self.evaluation_progress is not None:
                self.evaluation_progress['trial']=completed
                self.evaluation_progress['trials_this_task']=total

    def skill_evidence(self):
        result=[]
        evidence=self.last_evaluation
        match=bool(evidence and evidence.get('policy_fingerprint')==self.agent.signature()
                   and (not self.is_camera or evidence.get('camera_config',{})==self.camera_config))
        rows={r['current']['task']:r['current'] for r in (evidence or {}).get('by_task',[])}
        for task in TASKS:
            row=rows.get(task)
            result.append({'task':task,'status':'not evaluated' if row is None else ('current evaluation' if match else 'old evaluation, policy or camera setup changed'),
                           'successes':row.get('successes') if row else None,'trials':row.get('trials') if row else None,
                           'mastery_claim':False})
        return result
