"""Empirical wall-clock estimates, never an ETA for acquiring a skill.

Profiles separate training/testing, task, view mix, settings and host class.
Ranges are conservative empirical planning bands, NOT probability guarantees.
No model evaluation, training or network request is done to generate an estimate.
"""
from __future__ import annotations
import hashlib,json,math,os,platform,threading,time
from pathlib import Path
from collections import deque
import numpy as np

class RunTiming:
    def __init__(self,path,clock=time.perf_counter):
        self.path=Path(path);self.clock=clock;self.lock=threading.RLock()
        self.host=hashlib.sha256(json.dumps([platform.system(),platform.machine(),platform.python_version(),os.cpu_count(),np.__version__]).encode()).hexdigest()[:16]
        self.samples={};self.current=None;self.revision=0
        try:
            value=json.loads(self.path.read_text())
            if value.get('schema')=='seizo-timing/v1' and value.get('host')==self.host:
                for key,rows in value.get('samples',{}).items():
                    valid=[float(x) for x in rows if isinstance(x,(int,float)) and math.isfinite(x) and 0<x<86400]
                    self.samples[key]=deque(valid[-40:],maxlen=40)
        except (OSError,ValueError,TypeError,AttributeError):pass

    @staticmethod
    def profile(model,settings):
        return hashlib.sha256(json.dumps([model,settings],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

    @staticmethod
    def key(profile,kind,task):return profile+'|'+kind+'|'+task

    def record(self,key,seconds):
        seconds=float(seconds)
        if not math.isfinite(seconds) or not 0<seconds<86400:return
        with self.lock:
            self.samples.setdefault(key,deque(maxlen=40)).append(seconds);self.revision+=1

    def start(self,kind,plan):
        with self.lock:self.current={'kind':kind,'remaining':dict(plan),'started':self.clock(),'inflight_since':self.clock(),'completed':0,'total':sum(plan.values())}

    def completed(self,key):
        with self.lock:
            if self.current and self.current['remaining'].get(key,0)>0:
                self.current['remaining'][key]-=1;self.current['completed']+=1;self.current['inflight_since']=self.clock()

    def finish(self):
        with self.lock:self.current=None

    def _stats(self,key):
        rows=list(self.samples.get(key,()))
        same=True
        if len(rows)<3 and '|eval_' in key:
            # A related task is a provisional fallback, never called measured for this task.
            family=key.rsplit('|',1)[0]+'|'
            rows=[x for k,v in self.samples.items() if k.startswith(family) for x in v][-40:];same=False
            if len(rows)<3:
                family=key.split('|',1)[0]+'|eval_'
                rows=[x for k,v in self.samples.items() if k.startswith(family) for x in v][-40:]
        if len(rows)<3:return None
        a=np.asarray(rows[-30:],float);weights=np.linspace(.4,1,len(a));mean=float(np.average(a,weights=weights))
        spread=float(np.std(a))/max(mean,1e-8)
        pad=max(.20,min(1.5,spread)) if len(rows)>=10 and same else max(.5,min(2.,spread))
        low=max(.01,min(float(np.quantile(a,.2)),mean*(1-pad*.5)))
        high=max(float(np.quantile(a,.9)),mean*(1+pad))
        return mean,low,high,len(rows),same

    def estimate(self,plan,*,live=False):
        with self.lock:
            seconds=lo=hi=0.;count=0;minimum=1000000;provisional=False;unknown=[]
            for key,n in plan.items():
                if not n:continue
                stats=self._stats(key)
                if stats is None:unknown.append(key.rsplit('|',1)[-1]);continue
                m,l,h,num,exact=stats;seconds+=m*n;lo+=l*n;hi+=h*n;count+=n;minimum=min(minimum,num);provisional|=not exact or num<10
            total=sum(plan.values())
            result={'seconds':None,'range_seconds':None,'state':'calibrating','remaining_trials':total,
                    'basis':'Measured wall time on this computer. Includes rendering; training intervals include updates and periodic saving.',
                    'not_a_skill_eta':True,'range_is_guarantee':False,'unknown_tasks':sorted(set(unknown))}
            if not total:
                result.update(seconds=0.,range_seconds=[0.,0.],state='complete');return result
            if unknown:return result
            # Do not assume that an unusually long in-flight episode is already finished.
            elapsed=0.
            if live and self.current:
                elapsed=max(0.,self.clock()-self.current['inflight_since'])
                seconds=max(seconds-elapsed,.1);lo=max(lo-elapsed,0.);hi=max(hi-elapsed,seconds*1.25)
            result.update(seconds=seconds,range_seconds=[lo,hi],state='provisional' if provisional else 'measured',
                          matching_samples=minimum,estimate_finish_epoch=time.time()+seconds,
                          caveat='Assumes the current task/view mix and computer load. Phase changes, slow drivers and other apps can move the estimate.')
            return result

    def snapshot(self):
        with self.lock:
            if not self.current:return None
            value=self.estimate(self.current['remaining'],live=True)
            value.update(kind=self.current['kind'],elapsed_seconds=max(0,self.clock()-self.current['started']),
                         completed_trials=self.current['completed'],total_trials=self.current['total'])
            return value

    def save(self):
        with self.lock:
            obj={'schema':'seizo-timing/v1','host':self.host,'samples':{k:list(v) for k,v in self.samples.items()}}
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(obj),encoding='utf-8');os.replace(temp,self.path)
