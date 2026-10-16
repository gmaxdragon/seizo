"""Non-destructive end/save, persisted settings and measured time estimates.

The v9 learner and checkpoint input layout are unchanged. Nothing here sends
real-motor commands, starts a cloud job, or changes Windows power-plan settings.
"""
from __future__ import annotations
import copy,json,os,threading,time
from pathlib import Path
from .view_runner import ViewRunner
from .runner import TASKS,atomic_json
from .run_timing import RunTiming

BUSY=('training','stopping','evaluating','watching')
DEFAULT_UI={'speed':220,'eval_trials':1,'source':'current','watch_fault':False,
            'hide_previews':False,'keep_awake':False,'task':'curriculum','episodes':1000,'compute':'cad'}

def checked_ui(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT_UI):raise ValueError('Unknown session setting')
    v=dict(DEFAULT_UI);v.update(value)
    if type(v['speed'])is not int or v['speed'] not in (100,220,450):raise ValueError('Invalid playback speed')
    if type(v['eval_trials'])is not int or v['eval_trials'] not in (1,5,20,100):raise ValueError('Invalid trial count')
    if type(v['episodes'])is not int or not 1<=v['episodes']<=1000000:raise ValueError('Invalid episode budget')
    if v['task'] not in TASKS+('curriculum','all') or v['compute'] not in ('cad','fast'):raise ValueError('Invalid task/load')
    if v['source'] not in ('current','untrained','best'):raise ValueError('Invalid policy selection')
    for name in ('watch_fault','hide_previews','keep_awake'):
        if type(v[name]) is not bool:raise ValueError('Invalid on/off setting')
    return v

class SessionRunner(ViewRunner):
    def __init__(self,folder):
        self.session_lock=threading.RLock();self.ui=dict(DEFAULT_UI);self.end_state=None
        self._end_worker=None;self._watching=threading.Event();self._power_quit=threading.Event();self.power_status='Not requested'
        self._train_last_time=None;self._train_profile=None;self._eval_profile=None
        super().__init__(folder)
        from .camera_world import validate_config
        self.camera_config=validate_config(self.camera_config)
        self.ui.update({k:self.config[k] for k in ('task','episodes','compute')})
        try:self.ui=checked_ui(json.loads((self.folder/'session_settings.json').read_text()))
        except (OSError,ValueError,TypeError):pass
        self.timing=RunTiming(self.folder/'timing_history.json')
        self._power_thread=threading.Thread(target=self._power_loop,daemon=True);self._power_thread.start()

    def _profile(self,kind,config=None):
        cfg=config or self.config
        settings={'camera':self.camera_config,'kind':kind,
                  'view': 'two' if kind=='test' else [self.agent.view_mode,self.agent.views.stage],
                  'compute':cfg['compute'] if kind=='train' else None,
                  'stage':self.stage if kind=='train' and cfg['task']=='curriculum' else None}
        return self.timing.profile(self.model_id,settings)

    def _train_key(self,config=None):
        cfg=config or self.config
        return self.timing.key(self._profile('train',cfg),'train',cfg['task'])

    def _eval_plan(self,task,trials):
        profile=self._profile('test');names=TASKS if task=='all' else (task,)
        plan={self.timing.key(profile,'eval_'+label,name):trials for name in names for label in ('policy','random','reference')}
        plan[self.timing.key(profile,'eval_fault','reach')]=max(5,trials//2)
        return plan

    def estimate_run(self,kind,episodes=1000,task='curriculum',trials=1,compute='cad'):
        if kind not in ('train','test'):raise ValueError('Unknown estimate type')
        if type(episodes)is not int or not 1<=episodes<=1000000:raise ValueError('Invalid episode budget')
        if type(trials)is not int or trials not in (1,5,20,100):raise ValueError('Invalid evaluation count')
        if task not in TASKS+('curriculum','all') or compute not in ('cad','fast'):raise ValueError('Invalid run settings')
        cfg={**self.config,'episodes':episodes,'task':task,'compute':compute}
        if kind=='train':
            remaining=episodes
            if self.status=='paused' and all(cfg[k]==self.config[k] for k in ('episodes','task')) and self.target>self.agent.episodes:
                remaining=self.target-self.agent.episodes
            result=self.timing.estimate({self._train_key(cfg):remaining})
        else:result=self.timing.estimate(self._eval_plan('all',trials))
        result['kind']=kind;return result

    def _reject_while_ending(self):
        if self.end_state and self.end_state['state'] in ('requested','saving'):
            raise ValueError('End run is still saving. Wait for Saved and verified.')

    def start(self,config):
        self._reject_while_ending();self.end_state=None
        # Created in the training worker after validation, not before an invalid start.
        return super().start(config)

    def _train(self):
        self._train_last_time=time.perf_counter()
        self.timing.start('train',{self._train_key():max(0,self.target-self.agent.episodes)})
        try:return super()._train()
        finally:self.timing.finish();self.timing.save()

    def record_training_episode(self,item):
        now=time.perf_counter()
        if self._train_last_time is not None:
            key=self._train_key();self.timing.record(key,now-self._train_last_time)
            with self.timing.lock:
                if self.timing.current:
                    oldkey=next(iter(self.timing.current['remaining']),key)
                    if oldkey!=key:
                        self.timing.current['remaining']={key:max(1,self.target-self.agent.episodes+1)}
                    self.timing.completed(key)
        self._train_last_time=now

    def record_trial_time(self,task,random_policy,seconds,fault_probability=0.,label=None):
        key=self.timing.key(self._profile('test'),'eval_'+(label or ('fault' if fault_probability else ('random' if random_policy else 'policy'))),task)
        self.timing.record(key,seconds)
        if self.status in ('evaluating','stopping'):
            self.timing.completed(key)

    def begin_evaluation(self,task='all',trials=20,_inline=False):
        if _inline and self.stop_event.is_set():return {'ok':False,'cancelled':True}
        if not _inline:self._reject_while_ending()
        if self.status in BUSY:raise ValueError('End the current run before testing')
        if task not in TASKS+('all',) or type(trials)is not int or not 1<=trials<=100:raise ValueError('Invalid test setting')
        self.timing.start('test',self._eval_plan(task,trials));self.end_state=None
        try:return super().begin_evaluation(task,trials,_inline=_inline)
        except Exception:self.timing.finish();raise

    def trial(self,*args,**kwargs):
        self._reject_while_ending();self._watching.set()
        try:return super().trial(*args,**kwargs)
        finally:self._watching.clear()

    def set_session(self,value):
        v=checked_ui(value)
        with self.session_lock:
            atomic_json(self.folder/'session_settings.json',v)
            if checked_ui(json.loads((self.folder/'session_settings.json').read_text()))!=v:raise RuntimeError('Settings did not reload correctly')
            self.ui=v
        return {'ok':True,'settings_saved':True,'settings':dict(v)}

    def end_run(self,settings=None):
        """Request cancellation BEFORE any checkpoint or model lock is acquired."""
        self.stop_event.set()
        self.generation+=1
        with self.session_lock:
            if settings is not None:self.set_session(settings)
            if self._end_worker and self._end_worker.is_alive():
                return {'ok':True,'state':'requested','save_complete':False,'tab_remains_open':True}
            self.end_state={'state':'requested','requested_at':time.time(),'message':'Cancellation requested. Waiting for the current render/update to finish safely.'}
            worker=self.thread
            def finish():
                try:
                    if worker and worker is not threading.current_thread():worker.join()
                    while self._watching.wait(.05):
                        if not self._watching.is_set():break
                        time.sleep(.02)
                    self.end_state['state']='saving'
                    with self.lock:
                        if not (self.save_verified and self.saved_fingerprint==self.agent.signature()):self.save()
                        self.timing.finish();self.timing.save()
                        if self.status!='error':self.status='paused' if self.agent.steps else 'ready'
                    self.end_state.update(state='saved',saved_at=time.time(),message='Saved and verified. The tab stays open. Train / resume continues this budget with these settings.',
                                          request_to_save_seconds=time.time()-self.end_state['requested_at'])
                except Exception as e:
                    self.end_state.update(state='error',message='Saving failed: '+str(e));self.error=str(e)
            self._end_worker=threading.Thread(target=finish,daemon=True);self._end_worker.start()
        return {'ok':True,'state':'requested','save_complete':False,'tab_remains_open':True}

    def save(self):
        super().save()
        if hasattr(self,'timing'):self.timing.save()

    def snapshot(self):
        result=super().snapshot()
        result['session_settings']=dict(self.ui);result['end_run']=copy.deepcopy(self.end_state)
        result['eta']=self.timing.snapshot() if result['status'] in BUSY else None
        result['background']={'local':True,'computer_must_be_awake':True,'screen_can_be_off':True,
                              'power_request':self.power_status,'cloud_job_started':False}
        return result

    def _power_loop(self):
        """Opt-in, mains-only sleep request, from one owning thread; display may turn off."""
        if os.name!='nt':
            self.power_status='Windows-only sleep request. Other systems use their own power settings.';return
        try:
            import ctypes
            from ctypes import wintypes
            class Power(ctypes.Structure):
                _fields_=[('ac',wintypes.BYTE),('flags',wintypes.BYTE),('percent',wintypes.BYTE),('reserved',wintypes.BYTE),('life',wintypes.DWORD),('full',wintypes.DWORD)]
            k=ctypes.WinDLL('kernel32',use_last_error=True)
            k.SetThreadExecutionState.argtypes=[wintypes.DWORD];k.SetThreadExecutionState.restype=wintypes.DWORD
            k.GetSystemPowerStatus.argtypes=[ctypes.POINTER(Power)];k.GetSystemPowerStatus.restype=wintypes.BOOL
            on=False
            try:
                while not self._power_quit.is_set():
                    power=Power();mains=bool(k.GetSystemPowerStatus(ctypes.byref(power))) and power.ac==1
                    want=bool(self.ui.get('keep_awake')) and self.status in BUSY and mains
                    if want!=on:
                        success=k.SetThreadExecutionState(0x80000000 | (1 if want else 0))
                        if success:on=want
                        else:self.power_status='Windows declined sleep-prevention request'
                    if on:self.power_status='Sleep prevention requested while plugged in. Screen may turn off; shutdown/lid sleep is not blocked.'
                    elif not mains and self.ui.get('keep_awake'):self.power_status='Not preventing sleep on battery'
                    else:self.power_status='No sleep prevention request'
                    self._power_quit.wait(1.)
            finally:k.SetThreadExecutionState(0x80000000)
        except Exception as e:self.power_status='Sleep prevention unavailable: '+type(e).__name__

    def shutdown(self):
        try:
            super().shutdown()
            if self._end_worker:self._end_worker.join(timeout=25)
        finally:
            self._power_quit.set();self._power_thread.join(timeout=3)
