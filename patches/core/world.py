"""Five-control, multi-task offline arm environment.

This is an explicitly APPROXIMATE kinematic/contact simulator, not MuJoCo and not
calibrated hardware. It adds bounded servo lag, dynamic objects, gravity, floor
friction and a capped spring/friction grasp surrogate. No IK/controller knows
how to solve tasks. Objects are never teleported/attached to the tool during a
step. Only reset() changes the starting layout. No hardware or network imports.
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
from .contact import colliders, solve_capsule_contacts, FINGER_RADIUS

SPEC=json.loads((Path(__file__).resolve().parents[1]/'web/assets/kinematics.json').read_text())
D=SPEC['dimensions']; MODEL_ID='seizo-five-control-capsule-v3'
TASKS=('reach','orient','push','lift','place')
TASK_LABELS=('Reach an object','Aim wrist + set gripper','Push to the pad','Grip and lift','Lift and place')
ACTION_LABELS=('base','shoulder','forearm','wrist','gripper')
LOW=np.array([-60.,25.,-65.,-75.,0.]); HIGH=np.array([60.,95.,15.,75.,1.])
DELTA=np.array([3.0,3.0,3.0,7.,.16]); DEG=np.pi/180
DT=.06; FLOOR=65.; TCP_X=173.; WRIST_ORIGIN=26.; TCP_Z=1.
OBS_SIZE=49


def fk(q):
    q=np.atleast_2d(q); a=q[:,0]*DEG;b=q[:,1]*DEG;c=q[:,2]*DEG;t=q[:,3]*DEG
    elbow=np.stack([D['upper']*np.cos(b),np.zeros(len(q)),D['shoulder_height']+D['upper']*np.sin(b)],1)
    w=elbow+np.stack([D['forearm']*np.cos(c),np.zeros(len(q)),D['forearm']*np.sin(c)],1)
    xy=np.stack([w[:,0]+WRIST_ORIGIN+(TCP_X-WRIST_ORIGIN)*np.cos(t),(TCP_X-WRIST_ORIGIN)*np.sin(t)],1)
    tcp=np.stack([xy[:,0]*np.cos(a)-xy[:,1]*np.sin(a),xy[:,0]*np.sin(a)+xy[:,1]*np.cos(a),w[:,2]+TCP_Z],1)
    def rot(p):return np.stack([p[:,0]*np.cos(a)-p[:,1]*np.sin(a),p[:,0]*np.sin(a)+p[:,1]*np.cos(a),p[:,2]],1)
    return tcp,rot(w),rot(elbow)


def angular_error(a,b):return (a-b+180.)%360.-180.


class World:
    def __init__(self,n=8,seed=41,task='reach',fault_probability=0.0):
        if task not in TASKS+('all','curriculum'):raise ValueError('Unknown task')
        self.n=int(n); self.rng=np.random.default_rng(seed); self.task_setting=task
        self.stage=0; self.difficulty=.5; self.fault_probability=float(fault_probability)
        self.q=np.zeros((n,5)); self.v=np.zeros((n,5)); self.targetq=np.zeros((n,5))
        self.objects=np.zeros((n,3,3)); self.ov=np.zeros_like(self.objects)
        self.radius=np.zeros((n,3));self.mass=np.zeros((n,3));self.friction=np.zeros((n,3))
        self.target_obj=np.zeros(n,dtype=int);self.task=np.zeros(n,dtype=int)
        self.goal=np.zeros((n,3));self.wrist_goal=np.zeros(n);self.gap_goal=np.zeros(n)
        self.pinched=np.zeros((n,3),dtype=bool);self.offset=np.zeros_like(self.objects)
        self.ever_lifted=np.zeros(n,dtype=bool);self.dwell=np.zeros(n,dtype=int)
        self.count=np.zeros(n,dtype=int);self.returns=np.zeros(n);self.previous_phi=np.zeros(n)
        self.fault_at=np.full(n,-1,dtype=int);self.fault_kind=np.zeros(n,dtype=int)
        self.last_action=np.zeros((n,5));self.previous_tcp=np.zeros((n,3));self.blocked=np.zeros(n,dtype=bool)
        self.contact_steps=np.zeros(n,dtype=int);self.last_contact=np.zeros(n,dtype=bool)
        self.reset(np.arange(n))

    def reset(self,ids=None):
        ids=np.arange(self.n) if ids is None else np.asarray(ids,dtype=int);m=len(ids)
        if not m:return
        r=self.rng
        if self.task_setting in TASKS:self.task[ids]=TASKS.index(self.task_setting)
        elif self.task_setting=='all':self.task[ids]=r.integers(0,5,m)
        else:
            self.task[ids]=self.stage
            review=r.random(m)<.2
            if self.stage>0:self.task[ids[review]]=r.integers(0,self.stage,int(review.sum()))
        q=np.stack([r.uniform(-25,25,m),r.uniform(45,70,m),r.uniform(-48,-15,m),r.uniform(-35,35,m),r.uniform(.35,.9,m)],1)
        self.q[ids]=q;self.targetq[ids]=q;self.v[ids]=0
        self.target_obj[ids]=r.integers(0,3,m)
        self.radius[ids]=r.uniform(10.,15.,(m,3));self.mass[ids]=r.uniform(.015,.04,(m,3));self.friction[ids]=r.uniform(.7,1.1,(m,3))
        # Three different, independently movable shapes. Their footprint contact
        # proxies are circles; the visual shape is not an exact collision mesh.
        self.objects[ids,:,0]=r.uniform(315.,405.,(m,3))
        self.objects[ids,:,1]=np.array([-105.,0.,105.])[None,:]+r.uniform(-15.,15.,(m,3))
        self.objects[ids,:,2]=FLOOR+self.radius[ids]
        self.ov[ids]=0;self.pinched[ids]=False;self.offset[ids]=0
        self.ever_lifted[ids]=False;self.dwell[ids]=0;self.count[ids]=0;self.returns[ids]=0
        self.last_action[ids]=0;self.blocked[ids]=False;self.contact_steps[ids]=0;self.last_contact[ids]=False
        for i in ids:
            task=self.task[i];o=self.target_obj[i]
            if task<=1:
                # Sample the target independently of actions and reject starts
                # already at the target. A valid workspace is not a movement
                # teacher: there is no IK solution passed to the policy.
                for attempt in range(100):
                    gq=self.q[i:i+1].copy()
                    span=np.array([30.,22.,22.,30.,0.])*(.45+.55*self.difficulty)
                    gq[0]+=r.uniform(-1,1,5)*span
                    gq=np.clip(gq,LOW,HIGH)
                    goal= fk(gq)[0][0]
                    if goal[2]>FLOOR+18. and np.linalg.norm(goal-fk(self.q[i])[0][0])>30.:
                        break
                else:
                    # Deterministic reset fallback is only a target layout.
                    gq=np.array([[0.,60.,-20.,0.,.7]])
                    goal=fk(gq)[0][0]
                self.goal[i]=goal
                self.objects[i,o]=[goal[0],goal[1],FLOOR+self.radius[i,o]]
            else:
                # Start above the selected object with an open, empty gripper.
                # This samples an easier initial distribution for manipulation;
                # no corrective action, example trajectory or grasp is supplied.
                shoulder=r.uniform(43,62)
                height=FLOOR+self.radius[i,o]+r.uniform(15.,27.)
                sine=(height-TCP_Z-D['shoulder_height']-D['upper']*np.sin(shoulder*DEG))/D['forearm']
                forearm=np.arcsin(np.clip(sine,-.99,.99))/DEG
                self.q[i]=[r.uniform(-18,18),shoulder,forearm,r.uniform(-12,12),.9]
                tcp=fk(self.q[i])[0][0]
                self.objects[i,o,:2]=tcp[:2]+r.uniform(-16,16,2)
                self.targetq[i]=self.q[i]
                self.goal[i]=self.objects[i,o]
                angle=r.uniform(-np.pi,np.pi);distance=r.uniform(45.,75.)
                self.goal[i,:2]+=np.array([np.cos(angle),np.sin(angle)])*distance
                if task==3:self.goal[i]=self.objects[i,o]+[0.,0.,70.]
            # Keep distractors out of the selected object's initial footprint.
            for j in range(3):
                if j==o:continue
                if np.linalg.norm(self.objects[i,j,:2]-self.objects[i,o,:2])<self.radius[i,j]+self.radius[i,o]+8.:
                    self.objects[i,j,1]=self.objects[i,o,1]+(j-o)*65.
            self.wrist_goal[i]=r.uniform(-60,60)
            self.gap_goal[i]=r.uniform(.08,.94)
        self.previous_tcp[ids]=fk(self.q[ids])[0]
        self.previous_phi[ids]=self.metrics()[0][ids]
        use=r.random(m)<self.fault_probability
        self.fault_at[ids]=np.where(use,r.integers(15,75,m),-1)
        self.fault_kind[ids]=r.integers(1,5,m)

    def metrics(self):
        tcp,_,_=fk(self.q);idx=np.arange(self.n);obj=self.objects[idx,self.target_obj]
        rad=self.radius[idx,self.target_obj];grip=self.pinched[idx,self.target_obj]
        d=np.linalg.norm(tcp-self.goal,axis=1)
        reach=np.linalg.norm(tcp-obj,axis=1)
        objgoal=np.linalg.norm(obj-self.goal,axis=1)
        lift=np.maximum(0.,obj[:,2]-FLOOR-rad)
        werr=np.abs(angular_error(self.q[:,3],self.wrist_goal));gerr=np.abs(self.q[:,4]-self.gap_goal)
        phi=-d/80.
        phi=np.where(self.task==1,-d/100.-werr/85.-gerr,phi)
        direction=self.goal-obj;direction[:,2]=0.
        direction/=np.maximum(np.linalg.norm(direction,axis=1)[:,None],1e-6)
        behind=obj-direction*(rad+10.)[:,None]
        approach=np.linalg.norm(tcp-behind,axis=1)
        # Reward shaping grades approach and actual object progress; it never
        # supplies a joint action or an inverse-kinematics solution.
        phi=np.where(self.task==2,-objgoal/45.-.6*approach/80.,phi)
        near=np.exp(-(reach/32.)**2)
        closure=np.maximum(0.,1.-self.q[:,4])
        phi=np.where(self.task==3,-reach/65.+near*closure*.6+grip*.6+np.minimum(lift/70.,1.2)*2.,phi)
        phi=np.where(self.task==4,-reach/90.+near*closure*.4+grip*.3+np.minimum(lift/55.,1.)+self.ever_lifted*(1.5-np.minimum(objgoal/70.,3.)),phi)
        success=(d<18.)
        success=np.where(self.task==1,(d<22.)&(werr<12.)&(gerr<.12),success)
        success=np.where(self.task==2,(objgoal<18.)&(np.abs(obj[:,2]-FLOOR-rad)<8.),success)
        success=np.where(self.task==3,(lift>60.)&grip,success)
        success=np.where(self.task==4,self.ever_lifted&(np.linalg.norm(obj[:,:2]-self.goal[:,:2],axis=1)<20.)&
                         (np.abs(obj[:,2]-FLOOR-rad)<6.)&(~grip)&(np.linalg.norm(self.ov[idx,self.target_obj],axis=1)<40.),success)
        return phi,success,{'distance':d,'object_distance':objgoal,'lift':lift,'wrist_error':werr,'grip':grip}

    def observation(self):
        tcp,w,e=fk(self.q);idx=np.arange(self.n);obj=self.objects[idx,self.target_obj]
        onehot=np.eye(5)[self.task]
        raw=np.concatenate([
            (self.q-LOW)/(HIGH-LOW)*2.-1.,self.v/np.array([65.,65.,65.,140.,3.]),
            tcp/500.,(self.goal-tcp)/250.,(obj-tcp)/180.,(self.goal-obj)/180.,
            self.ov[idx,self.target_obj]/500.,
            np.stack([np.sin(self.q[:,3]*DEG),np.cos(self.q[:,3]*DEG),np.sin(self.wrist_goal*DEG),np.cos(self.wrist_goal*DEG),self.gap_goal],1),
            self.radius[idx,self.target_obj,None]/20.,self.mass[idx,self.target_obj,None]/.04,self.friction[idx,self.target_obj,None],
            onehot,self.pinched[idx,self.target_obj,None].astype(float),self.ever_lifted[:,None].astype(float),
            (self.objects[:,:,:2]-tcp[:,None,:2]).reshape(self.n,6)/250.,
            self.count[:,None]/220., self.last_action[:,3:5],
        ],axis=1)
        assert raw.shape[1]==OBS_SIZE,(raw.shape,OBS_SIZE)
        return np.clip(raw,-5.,5.).astype(np.float32)

    def step(self,actions):
        a=np.asarray(actions,dtype=float)
        if a.shape!=(self.n,5) or not np.isfinite(a).all():raise ValueError('Five finite virtual control values required.')
        a=np.clip(a,-1.,1.);self.last_action=a.copy();self.count+=1
        before=self.q.copy();oldtcp=fk(self.q)[0]
        request=np.clip(self.q+a*DELTA,LOW,HIGH)
        self.targetq=request.copy()
        # Explicit low-level velocity/lag model, not known task actions.
        desired=(request-self.q)/DT;self.v=.2*self.v+.8*desired
        self.q=np.clip(self.q+self.v*DT,LOW,HIGH)
        tcp,wrist,elbow=fk(self.q)
        blocked=(tcp[:,2]<FLOOR+4.)|(wrist[:,2]<30.)|(elbow[:,2]<30.)|(np.linalg.norm(wrist[:,:2],axis=1)<85.)
        self.q[blocked,:3]=before[blocked,:3];self.v[blocked,:3]=0
        tcp=fk(self.q)[0];self.blocked=blocked
        triggered=(self.count==self.fault_at)
        # Fault injection checks the supervisor, NOT learned safety.
        self.q[triggered]=before[triggered];self.targetq[triggered]=before[triggered];self.v[triggered]=0;tcp=fk(self.q)[0]
        terminal_fault=triggered
        self._object_step(tcp,(tcp-oldtcp)/DT,old_q=before)
        idx=np.arange(self.n);lift=self.objects[idx,self.target_obj,2]-FLOOR-self.radius[idx,self.target_obj]
        self.ever_lifted|=lift>50.
        phi,success,metrics=self.metrics()
        self.dwell=np.where(success,self.dwell+1,0)
        done_success=(self.dwell>=4)&(self.count>=8)&(~terminal_fault)
        reward=np.clip(2.*(phi-self.previous_phi),-3.,3.)-.015-.002*np.sum(a*a,1)-blocked*.06+done_success*5.
        reward=np.where(terminal_fault,-.4,reward);self.previous_phi=phi;self.returns+=reward
        terminated=done_success|terminal_fault
        truncated=(self.count>=220)&(~terminated)
        fallen=(self.objects[idx,self.target_obj,2]<-50.)|(np.linalg.norm(self.objects[idx,self.target_obj,:2],axis=1)>850.)
        terminated|=fallen
        info={'success':done_success,'fault':terminal_fault,'fallen':fallen,'blocked':blocked,
              'return':self.returns.copy(),'steps':self.count.copy(),'task':self.task.copy(),
              'collision':self.last_contact.copy(),'contacts_total':self.contact_steps.copy(),**metrics}
        return self.observation(),reward.astype(np.float32),terminated,truncated,info

    def _object_step(self,tcp,tcpv,old_q=None):
        """Advance physical proxies: arm/palm/finger contacts, floor, object pairs.

        Uncalibrated, kinematic arm. Objects cannot tunnel through the modeled
        capsule volumes, but STL triangle-level physics and correct force/torque
        still require independently measured joint geometry and inertias.
        """
        old_q=np.asarray(self.q if old_q is None else old_q,dtype=float)
        before_a,before_b,cr,names=colliders(old_q,fk,D,FLOOR)
        after_a,after_b,_,_=colliders(self.q,fk,D,FLOOR)
        # Adaptive substeps reduce missed contacts when an object falls quickly.
        speed=float(np.max(np.linalg.norm(self.ov,axis=2)))
        slices=min(24,max(5,int(np.ceil(speed*DT/6.))))
        dt=DT/slices
        n=self.n;rad=self.radius
        self.last_contact[:]=False
        for tick in range(slices):
            # Interpolate moving colliders for each time slice so arm motion
            # cannot instantly jump through a dynamic object.
            f0=tick/slices;f1=(tick+1.)/slices
            pa=before_a+(after_a-before_a)*f0;pb=before_b+(after_b-before_b)*f0
            ca=before_a+(after_a-before_a)*f1;cb=before_b+(after_b-before_b)*f1
            worldtcp=tcp # current tool pose, with velocity acting through grasp
            yaw=(self.q[:,0]+self.q[:,3])*DEG;c=np.cos(yaw);ss=np.sin(yaw)
            rel=self.objects-worldtcp[:,None,:]
            lx=rel[:,:,0]*c[:,None]+rel[:,:,1]*ss[:,None]
            ly=-rel[:,:,0]*ss[:,None]+rel[:,:,1]*c[:,None]
            requested=6.+50.*self.targetq[:,4]
            # A grasp requires an object within the actual finger span AND
            # closure into both jaws, rather than contact with an invisible
            # sphere centered at the tool tip.
            in_jaws=(lx>-71.)&(lx<7.)&(np.abs(ly)<np.minimum(rad*.6,8.))&(np.abs(rel[:,:,2])<rad+FINGER_RADIUS)
            closing=requested[:,None]<=2.*(rad+FINGER_RADIUS)+1.
            new=in_jaws&closing&(~self.pinched)
            self.offset[new]=rel[new]
            self.pinched|=new
            release=(requested[:,None]>2.*(rad+FINGER_RADIUS)+6.)|(np.linalg.norm(rel-self.offset,axis=2)>42.)
            self.pinched&=~release
            # A held object keeps the jaws a real distance apart. The rendered
            # aperture uses precisely the same value as these collision proxies.
            widths=np.where(self.pinched,(2.*(rad+FINGER_RADIUS)-6.)/50.,0.).max(axis=1)
            self.q[:,4]=np.maximum(self.q[:,4],widths)
            self.q[:,4]=np.minimum(self.q[:,4],1.)
            if np.any(self.q[:,4]>(6.+50.*self.targetq[:,4]-6.)/50.+.05):
                # Avoid stale finger locations after a solid object blocks jaw
                # closure. The rigid colliders must follow the rendered jaws.
                after_a,after_b,_,_=colliders(self.q,fk,D,FLOOR)
            # This is a velocity-limited compliant grasp, not teleporting.
            compression=np.maximum(0.,2.*(rad+FINGER_RADIUS)-requested[:,None])
            normal_force=np.minimum(4.,.07*compression+.04)*self.friction
            correction=worldtcp[:,None,:]+self.offset-self.objects
            spring=.055*correction+.0009*(tcpv[:,None,:]-self.ov)
            magnitude=np.linalg.norm(spring,axis=2)
            grip_force=spring*np.minimum(1.,normal_force/np.maximum(1e-9,magnitude))[:,:,None]
            # Held objects receive finite force; unsupported ones fall.
            acceleration=np.where(self.pinched[:,:,None],grip_force/self.mass[:,:,None]*1000.,0.)
            acceleration[:,:,2]-=9810.
            self.ov+=np.clip(acceleration,-15000.,15000.)*dt
            self.ov*=.995
            previous_objects=self.objects.copy()
            self.objects+=self.ov*dt
            # Cap collisions against real visible link proxies. During a
            # validated grip only the two contacting jaws are excluded from
            # repulsion, not the whole forearm/palm.
            omit=np.zeros((n,3,len(cr)),dtype=bool)
            for j,name in enumerate(names):
                if name.startswith('jaw_'):omit[:,:,j]=self.pinched
            touched,_=solve_capsule_contacts(self.objects,self.ov,ca,cb,cr,rad,pa,pb,previous_objects,dt,2,omit)
            self.last_contact|=touched.any(axis=1)
            # Floor is another solid collider, including while an object is
            # being held; no penetration below its support surface.
            floor=FLOOR+rad;hit=self.objects[:,:,2]<floor
            self.objects[:,:,2]=np.maximum(self.objects[:,:,2],floor)
            self.ov[:,:,2]=np.where(hit,np.maximum(0.,-self.ov[:,:,2]*.04),self.ov[:,:,2])
            self.ov[:,:,:2]*=np.where(hit,np.maximum(0.,1.-self.friction*dt*18.),1.)[:,:,None]
            # Dynamic spheres interact with one another. Spheres are
            # conservative object proxies, not exact cube/cylinder meshes.
            for i,j in ((0,1),(0,2),(1,2)):
                delta=self.objects[:,j]-self.objects[:,i]
                dd=np.linalg.norm(delta,axis=1)
                depth=np.maximum(0.,rad[:,i]+rad[:,j]-dd)
                axis=delta/np.maximum(dd[:,None],1e-6)
                axis=np.where((dd>1e-6)[:,None],axis,np.array([1.,0.,0.]))
                shift=axis*(depth*.5)[:,None]
                self.objects[:,i]-=shift;self.objects[:,j]+=shift
                # Remove approaching relative velocity along contact normal.
                relative=np.sum((self.ov[:,j]-self.ov[:,i])*axis,axis=1)
                kick=np.where(depth>0.,np.maximum(0.,-relative)*.5,0.)
                self.ov[:,i]-=kick[:,None]*axis
                self.ov[:,j]+=kick[:,None]*axis
        self.contact_steps+=self.last_contact.astype(int)

    def frame(self,i=0):
        tcp,w,e=fk(self.q[i]);phi,s,m=self.metrics()
        return {'pose':dict(zip(ACTION_LABELS,map(float,self.q[i]))),
            'tool':tcp[0].tolist(),'goal':self.goal[i].tolist(),'task':TASKS[int(self.task[i])],
            'task_label':TASK_LABELS[int(self.task[i])], 'selected_object':int(self.target_obj[i]),
            'objects':[{'shape':shape,'name':name,'position':self.objects[i,j].tolist(),
                        'radius':float(self.radius[i,j]),'mass_kg':float(self.mass[i,j]),
                        'pinched':bool(self.pinched[i,j])} for j,(shape,name) in enumerate(zip(('box','cylinder','sphere'),('red cube','green cylinder','blue ball')))],
            'wrist_goal':float(self.wrist_goal[i]),'gap_goal':float(self.gap_goal[i]),
            'step':int(self.count[i]),'reward_total':float(self.returns[i]),'lift_mm':float(m['lift'][i]),
            'action':self.last_action[i].tolist(),'floor_z':FLOOR,
            'physical_motion':False,'model_id':MODEL_ID,
            'arm_object_contact':bool(self.last_contact[i]),'collision_steps':int(self.contact_steps[i]),
            'collision_model':'16 solid arm capsules including rear support, ribs, palm and articulated fingers; estimated geometry'}