"""Small from-scratch NumPy PPO actor/critic. No downloaded/pretrained weights.

Clipped probability-ratio actor objective, GAE, separate value network, Adam,
advantage normalization and gradient norm clipping. Actions are tanh-squashed
Gaussian draws. Ratios are evaluated in the stored pre-squash coordinates, so
identical change-of-variable terms cancel. Entropy bonus is Gaussian entropy
(a stated approximation to squashed entropy). Independently gradient-tested.
"""
from __future__ import annotations
import copy, hashlib, json, os, tempfile
from pathlib import Path
import numpy as np
from .world import OBS_SIZE, MODEL_ID

class Agent:
    def __init__(self,seed=101,hidden=64):
        self.rng=np.random.default_rng(seed);self.hidden=hidden;self.seed=seed
        self.obs_size=getattr(self,'OBSERVATION_SIZE',OBS_SIZE)
        self.model_id=getattr(self,'POLICY_MODEL_ID',MODEL_ID)
        self.p={};self.m={};self.v={};self.t=0;self.updates=0;self.steps=0;self.episodes=0
        for prefix,lastscale in [('p',.01),('v',1.)]:
            self.p[prefix+'1']=self.rng.normal(0,np.sqrt(2/self.obs_size),(self.obs_size,hidden)).astype(np.float32)
            self.p[prefix+'b1']=np.zeros(hidden,np.float32)
            self.p[prefix+'2']=self.rng.normal(0,np.sqrt(2/hidden),(hidden,hidden)).astype(np.float32)
            self.p[prefix+'b2']=np.zeros(hidden,np.float32)
            out=5 if prefix=='p' else 1
            self.p[prefix+'3']=self.rng.normal(0,lastscale/np.sqrt(hidden),(hidden,out)).astype(np.float32)
            self.p[prefix+'b3']=np.zeros(out,np.float32)
        self.p['logstd']=np.full(5,-.35,np.float32)
        for k,p in self.p.items():self.m[k]=np.zeros_like(p);self.v[k]=np.zeros_like(p)

    def _forward(self,x,prefix):
        p=self.p;h1=np.tanh(x@p[prefix+'1']+p[prefix+'b1']);h2=np.tanh(h1@p[prefix+'2']+p[prefix+'b2'])
        return h2@p[prefix+'3']+p[prefix+'b3'],(x,h1,h2)

    def forward(self,x):
        x=np.asarray(x,dtype=np.float32);mu,_=self._forward(x,'p');val,_=self._forward(x,'v')
        return mu,val[:,0]

    def act(self,obs,deterministic=False,rng=None):
        mu,val=self.forward(obs);z=mu if deterministic else mu+np.exp(self.p['logstd'])*(rng or self.rng).standard_normal(mu.shape)
        logp=self.logprob(z,mu)
        return np.tanh(z).astype(np.float32),z.astype(np.float32),logp,val

    def logprob(self,z,mu):
        l=self.p['logstd'];return (-.5*((z-mu)*np.exp(-l))**2-l-.5*np.log(2*np.pi)).sum(1)

    def _back(self,grad,cache,prefix,out):
        x,h1,h2=cache;p=self.p
        out[prefix+'3']=h2.T@grad;out[prefix+'b3']=grad.sum(0)
        g=(grad@p[prefix+'3'].T)*(1.-h2*h2)
        out[prefix+'2']=h1.T@g;out[prefix+'b2']=g.sum(0)
        g=(g@p[prefix+'2'].T)*(1.-h1*h1)
        out[prefix+'1']=x.T@g;out[prefix+'b1']=g.sum(0)

    def loss_grads(self,obs,z,oldlog,adv,returns,entropy=.003):
        n=len(obs);mu,pc=self._forward(obs,'p');values,vc=self._forward(obs,'v');values=values[:,0]
        lp=self.logprob(z,mu);ratio=np.exp(np.clip(lp-oldlog,-15,15));clipped=np.clip(ratio,.8,1.2)
        active=(((adv>=0)&(ratio<=1.2))|((adv<0)&(ratio>=.8))) & (np.abs(lp-oldlog)<15.)
        dlp=-adv*ratio*active/n;diff=z-mu;invvar=np.exp(-2*self.p['logstd'])
        grads={};self._back(dlp[:,None]*diff*invvar,pc,'p',grads)
        grads['logstd']=(dlp[:,None]*(diff*diff*invvar-1.)).sum(0)-entropy
        self._back(((values-returns)*.5/n)[:,None],vc,'v',grads)
        ent=float((self.p['logstd']+.5*np.log(2*np.pi*np.e)).sum())
        loss=float(-np.minimum(ratio*adv,clipped*adv).mean()+.25*np.mean((values-returns)**2)-entropy*ent)
        return loss,grads,{'policy_loss':float(-np.minimum(ratio*adv,clipped*adv).mean()),
            'value_loss':float(np.mean((values-returns)**2)), 'entropy':ent,
            'approx_kl':float(np.mean((ratio-1)-(lp-oldlog))),'clip_fraction':float(np.mean(np.abs(ratio-1)>.2))}

    def update(self,batch,epochs=4,lr=3e-4,minibatch=256,stop=None):
        obs,z,oldlog,adv,ret=batch
        adv=(adv-adv.mean())/(adv.std()+1e-8)
        stats=[]
        for _ in range(epochs):
            for ids in np.array_split(self.rng.permutation(len(obs)),max(1,int(np.ceil(len(obs)/minibatch)))):
                if stop and stop():return stats
                _,g,s=self.loss_grads(obs[ids],z[ids],oldlog[ids],adv[ids],ret[ids])
                if not all(np.isfinite(x).all() for x in g.values()):raise FloatingPointError('Non-finite gradient. Policy update stopped.')
                norm=np.sqrt(sum(float(np.sum(x*x)) for x in g.values()));scale=min(1.,.75/(norm+1e-8))
                self.t+=1
                for k,p in self.p.items():
                    grad=(g[k]*scale).astype(np.float32);self.m[k]=.9*self.m[k]+.1*grad;self.v[k]=.999*self.v[k]+.001*grad*grad
                    p-=lr*(self.m[k]/(1-.9**self.t))/(np.sqrt(self.v[k]/(1-.999**self.t))+1e-8)
                self.p['logstd'][:]=np.clip(self.p['logstd'],-2.8,.4)
                self.updates+=1;stats.append(s)
            if stats and stats[-1]['approx_kl']>.045:break
        return stats

    def clone(self):return copy.deepcopy(self)

    def signature(self):
        h=hashlib.sha256()
        for k in sorted(self.p):h.update(k.encode());h.update(self.p[k].tobytes())
        return h.hexdigest()

    def save(self,path,metadata=None):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        meta={'model_id':self.model_id,'obs_size':self.obs_size,'hidden':self.hidden,'seed':self.seed,'t':self.t,
              'updates':self.updates,'steps':self.steps,'episodes':self.episodes,'rng':self.rng.bit_generator.state,
              'extra':metadata or {},'fingerprint':self.signature()}
        data={'meta':np.array(json.dumps(meta))}
        for prefix,group in [('p',self.p),('m',self.m),('v',self.v)]:
            for k,v in group.items():data[prefix+'/'+k]=v
        fd,tmp=tempfile.mkstemp(prefix='.policy-',suffix='.npz',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as f:np.savez_compressed(f,**data);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    @classmethod
    def load(cls,path):
        with np.load(path,allow_pickle=False) as z:
            meta=json.loads(str(z['meta']))
            if meta.get('model_id')!=getattr(cls,'POLICY_MODEL_ID',MODEL_ID) or meta.get('obs_size')!=getattr(cls,'OBSERVATION_SIZE',OBS_SIZE):raise ValueError('Incompatible policy. Weights from another physics engine cannot be used for this one.')
            if meta.get('hidden')!=64:raise ValueError('Unrecognized network size.')
            a=cls(meta['seed'],meta['hidden'])
            for prefix,group in [('p',a.p),('m',a.m),('v',a.v)]:
                for k,v in group.items():
                    x=z[prefix+'/'+k]
                    if x.shape!=v.shape or not np.isfinite(x).all():raise ValueError('Invalid policy weights.')
                    group[k]=x.astype(np.float32)
            for k in ('t','updates','steps','episodes'):setattr(a,k,int(meta[k]))
            a.rng.bit_generator.state=meta['rng']
            if a.signature()!=meta['fingerprint']:raise ValueError('Policy fingerprint check failed.')
        return a,meta.get('extra',{})


def gae(rewards,values,next_values,terminated,done,gamma=.99,lam=.95):
    adv=np.zeros_like(rewards,dtype=np.float32);last=np.zeros(rewards.shape[1],np.float32)
    for t in reversed(range(len(rewards))):
        delta=rewards[t]+gamma*next_values[t]*(~terminated[t])-values[t]
        last=delta+gamma*lam*(~done[t])*last;adv[t]=last
    return adv,adv+values


def rollout(agent,world,length=96,on_episode=None,on_frame=None,stop=None):
    rows=[];completed=[]
    for t in range(length):
        if stop and stop():break
        if on_frame and world.count[0]==0:on_frame(world,None)
        obs=world.observation();actions,z,lp,val=agent.act(obs)
        after,reward,term,trunc,info=world.step(actions);nv=agent.forward(after)[1];done=term|trunc
        agent.steps+=world.n
        rows.append((obs,z,lp,val,reward,nv,term,done))
        if on_frame:on_frame(world,info)
        ids=np.where(done)[0]
        for i in ids:
            if not info['fault'][i]: # completed faulted episodes still counted; no fabricated success
                pass
            agent.episodes+=1
            result={k:bool(info[k][i]) for k in ('success','fault','fallen')}
            result['safety_abort']=bool(info.get('invalid_physics',np.zeros(world.n,bool))[i])
            result.update({'task':int(info['task'][i]),'steps':int(info['steps'][i]),
                           'return':float(info['return'][i]),'episode':agent.episodes})
            completed.append(result)
            if on_episode:on_episode(result)
        world.reset(ids)
    if not rows:return None,completed
    fields=[np.stack([r[i] for r in rows]) for i in range(8)]
    obs,z,lp,val,reward,nv,term,done=fields;advantages,returns=gae(reward,val,nv,term,done)
    return (obs.reshape(-1,obs.shape[-1]),z.reshape(-1,5),lp.ravel(),advantages.ravel(),returns.ravel()),completed
