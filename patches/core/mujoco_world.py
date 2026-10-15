"""Real rigid-body Seizo environment. Requires the free local `mujoco` Python wheel.

Implements the same PPO World interface, but forces, inertia, motor saturation,
friction and true box/cylinder/sphere contact are integrated by MuJoCo.
All geometry/masses/motor ratings remain provisional until the actual machine
is measured. This module contains NO physical robot-control interfaces.
"""
from __future__ import annotations
import math
import numpy as np
import mujoco
from .mjcf import (xml_model, MODEL_VERSION, DT, SUBSTEPS, JOINT_NAMES,
                   ACTUATOR_NAMES, OBJECT_NAMES, OBJECT_GEOMS, FINGER_GEOMS, FLOOR_M)
from . import world as base
from .gripper_geometry import SPEC as GRIPPER, MAX_ANGLE, aperture_mm

RAD=np.pi/180.
DEG=180./np.pi
OBJECT_RADII=np.array([12.,13.,13.])


class MuJoCoWorld(base.World):
    """MuJoCo CPU contact simulation in independent environments, never hardware."""
    MODEL_ID=MODEL_VERSION

    def __init__(self,n=1,seed=41,task='reach',fault_probability=0.0,xml_text=None):
        self._physics_ready=False
        self.tcp=np.zeros((int(n),3))
        super().__init__(n=n,seed=seed,task=task,fault_probability=fault_probability)
        self.model=mujoco.MjModel.from_xml_string(xml_model() if xml_text is None else xml_text)
        self.data=[mujoco.MjData(self.model) for _ in range(self.n)]
        self.jid={name:mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_JOINT,name) for name in JOINT_NAMES}
        self.aid={name:mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_ACTUATOR,name) for name in ACTUATOR_NAMES}
        self.bid={name:mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_BODY,name) for name in OBJECT_NAMES}
        self.gid={name:mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_GEOM,name) for name in (*OBJECT_GEOMS,*FINGER_GEOMS)}
        self.sid=mujoco.mj_name2id(self.model,mujoco.mjtObj.mjOBJ_SITE,'tool_tip')
        self.objadr=np.array([self.model.jnt_qposadr[self.model.joint('free_'+color).id] for color in ('red','green','blue')])
        self.objvadr=np.array([self.model.jnt_dofadr[self.model.joint('free_'+color).id] for color in ('red','green','blue')])
        self.tcp=np.zeros((self.n,3))
        self._physics_ready=True
        self.reset()

    def _set_pose(self,data,q):
        # q uses degrees for angles; forearm is an ABSOLUTE pitch, not elbow-relative.
        angles=(q[0],q[1],q[2]-q[1],q[3])
        for name,v in zip(JOINT_NAMES[:4],angles):
            data.qpos[self.model.jnt_qposadr[self.jid[name]]]=v*RAD
        opening=float(np.clip(q[4],0,1))*MAX_ANGLE
        for name in ('left_finger','right_finger'):
            data.qpos[self.model.jnt_qposadr[self.jid[name]]]=opening
        for name in ('left_parallel','right_parallel'):
            data.qpos[self.model.jnt_qposadr[self.jid[name]]]=-opening
        data.qpos[self.model.jnt_qposadr[self.jid['wrist_level']]]=-q[2]*RAD
        self._command(data,q)

    def _command(self,data,q):
        # Five PHYSICAL actuator commands: 3 steppers, wrist servo, ONE gripper
        # servo coupled to both parallel jaw linkages. No fictitious second gripper motor.
        joint_target=(q[0]*RAD,q[1]*RAD,(q[2]-q[1])*RAD,q[3]*RAD,
                      float(np.clip(q[4],0,1))*MAX_ANGLE)
        for name,value in zip(ACTUATOR_NAMES,joint_target):
            data.ctrl[self.aid[name]]=value

    def _copy_from_physics(self,ids):
        for i in ids:
            d=self.data[int(i)]
            ang=[d.qpos[self.model.jnt_qposadr[self.jid[k]]]*DEG for k in JOINT_NAMES[:4]]
            v=[d.qvel[self.model.jnt_dofadr[self.jid[k]]]*DEG for k in JOINT_NAMES[:4]]
            self.q[i]=[ang[0],ang[1],ang[1]+ang[2],ang[3],
                       np.clip(.5*(d.qpos[self.model.jnt_qposadr[self.jid['left_finger']]]+
                                      d.qpos[self.model.jnt_qposadr[self.jid['right_finger']]])/MAX_ANGLE,0.,1.)]
            self.v[i]=[v[0],v[1],v[1]+v[2],v[3],
                       .5*(d.qvel[self.model.jnt_dofadr[self.jid['left_finger']]]+
                           d.qvel[self.model.jnt_dofadr[self.jid['right_finger']]])/MAX_ANGLE]
            for j,bname in enumerate(OBJECT_NAMES):
                self.objects[i,j]=d.xpos[self.bid[bname]]*1000.
                self.ov[i,j]=d.qvel[self.objvadr[j]:self.objvadr[j]+3]*1000.
            self.tcp[i]=d.site_xpos[self.sid]*1000.

    def reset(self,ids=None):
        super().reset(ids)
        if not self._physics_ready:return
        ids=np.arange(self.n) if ids is None else np.asarray(ids,dtype=int)
        for i in ids:
            d=self.data[int(i)];m=self.model
            mujoco.mj_resetData(m,d)
            self.radius[i]=OBJECT_RADII
            self.objects[i,:,2]=base.FLOOR+OBJECT_RADII
            self.mass[i]=np.array([m.body_mass[self.bid[n]] for n in OBJECT_NAMES])
            self.friction[i]=.95
            self._set_pose(d,self.q[i])
            # Discover actual site position at this pose, without moving hardware.
            mujoco.mj_forward(m,d)
            tcp=d.site_xpos[self.sid]*1000.
            task=int(self.task[i]);chosen=int(self.target_obj[i])
            if task<=1:
                # Goal sampled from a reachable DIFFERENT joint pose, not a teacher action.
                current=self.q[i].copy()
                for _ in range(60):
                    candidate=current.copy()
                    candidate[:4]+=self.rng.uniform(-1.,1.,4)*np.array([28.,20.,20.,35.])
                    candidate=np.clip(candidate,base.LOW,base.HIGH)
                    self._set_pose(d,candidate);mujoco.mj_forward(m,d)
                    goal=d.site_xpos[self.sid]*1000.
                    if np.linalg.norm(goal-tcp)>30. and goal[2]>base.FLOOR+15.:break
                self.goal[i]=goal
                self._set_pose(d,current);mujoco.mj_forward(m,d)
            else:
                # A reachable initial object at the pad/fingers, deliberately ungrasped.
                self.objects[i,chosen,:2]=tcp[:2]+self.rng.uniform(-9,9,2)
                self.objects[i,chosen,2]=base.FLOOR+self.radius[i,chosen]
                delta=self.rng.uniform(-np.pi,np.pi)
                shift=self.rng.uniform(40.,65.)
                self.goal[i]=self.objects[i,chosen]+[math.cos(delta)*shift,math.sin(delta)*shift,0.]
                if task==3:self.goal[i]=self.objects[i,chosen]+[0.,0.,70.]
            for j in range(3):
                adr=self.objadr[j]
                d.qpos[adr:adr+3]=self.objects[i,j]/1000.
                d.qpos[adr+3:adr+7]=[1,0,0,0]
            d.qvel[:]=0
            self._set_pose(d,self.q[i]);mujoco.mj_forward(m,d)
            self._copy_from_physics((i,))
            self.pinched[i]=False
            self.previous_tcp[i]=self.tcp[i]
        self.previous_phi[ids]=self.metrics()[0][ids]

    def metrics(self):
        # MuJoCo site, not an idealized kinematic tip, determines success.
        tcp=self.tcp
        idx=np.arange(self.n)
        obj=self.objects[idx,self.target_obj]
        rad=self.radius[idx,self.target_obj]
        held=self.pinched[idx,self.target_obj]
        distance=np.linalg.norm(tcp-self.goal,axis=1)
        reach=np.linalg.norm(tcp-obj,axis=1)
        objgoal=np.linalg.norm(obj-self.goal,axis=1)
        lift=np.maximum(0.,obj[:,2]-base.FLOOR-rad)
        werr=np.abs(base.angular_error(self.q[:,3],self.wrist_goal))
        gerr=np.abs(self.q[:,4]-self.gap_goal)
        phi=-distance/80.
        phi=np.where(self.task==1,-distance/100.-werr/85.-gerr,phi)
        direction=self.goal-obj;direction[:,2]=0.
        direction/=np.maximum(np.linalg.norm(direction,axis=1)[:,None],1e-6)
        behind=obj-direction*(rad+10.)[:,None]
        approach=np.linalg.norm(tcp-behind,axis=1)
        phi=np.where(self.task==2,-objgoal/45.-.6*approach/80.,phi)
        near=np.exp(-(reach/32.)**2)
        closure=np.maximum(0.,1.-self.q[:,4])
        phi=np.where(self.task==3,-reach/65.+near*closure*.6+held*.6+np.minimum(lift/70.,1.2)*2.,phi)
        phi=np.where(self.task==4,-reach/90.+near*closure*.4+held*.3+np.minimum(lift/55.,1.)+
                     self.ever_lifted*(1.5-np.minimum(objgoal/70.,3.)),phi)
        success=distance<18.
        success=np.where(self.task==1,(distance<22.)&(werr<12.)&(gerr<.12),success)
        success=np.where(self.task==2,(objgoal<18.)&(np.abs(obj[:,2]-base.FLOOR-rad)<8.),success)
        success=np.where(self.task==3,(lift>60.)&held,success)
        success=np.where(self.task==4,self.ever_lifted&(np.linalg.norm(obj[:,:2]-self.goal[:,:2],axis=1)<20.)&
                         (np.abs(obj[:,2]-base.FLOOR-rad)<6.)&(~held)&(np.linalg.norm(self.ov[idx,self.target_obj],axis=1)<40.),success)
        return phi,success,dict(distance=distance,object_distance=objgoal,lift=lift,wrist_error=werr,grip=held)

    def observation(self):
        tcp=self.tcp
        idx=np.arange(self.n);obj=self.objects[idx,self.target_obj]
        onehot=np.eye(5)[self.task]
        raw=np.concatenate([
            (self.q-base.LOW)/(base.HIGH-base.LOW)*2.-1.,
            self.v/np.array([65.,65.,65.,140.,3.]),
            tcp/500.,(self.goal-tcp)/250.,(obj-tcp)/180.,(self.goal-obj)/180.,
            self.ov[idx,self.target_obj]/500.,
            np.stack([np.sin(self.q[:,3]*RAD),np.cos(self.q[:,3]*RAD),
                      np.sin(self.wrist_goal*RAD),np.cos(self.wrist_goal*RAD),self.gap_goal],1),
            self.radius[idx,self.target_obj,None]/20.,
            self.mass[idx,self.target_obj,None]/.04,
            self.friction[idx,self.target_obj,None],
            onehot,self.pinched[idx,self.target_obj,None].astype(float),
            self.ever_lifted[:,None].astype(float),
            (self.objects[:,:,:2]-tcp[:,None,:2]).reshape(self.n,6)/250.,
            self.count[:,None]/220.,self.last_action[:,3:5],
        ],axis=1)
        assert raw.shape==(self.n,base.OBS_SIZE),raw.shape
        return np.clip(raw,-5.,5.).astype(np.float32)

    def step(self,actions):
        a=np.asarray(actions,dtype=float)
        if a.shape!=(self.n,5) or not np.isfinite(a).all():raise ValueError('Five finite simulation controls required.')
        a=np.clip(a,-1.,1.)
        self.last_action=a.copy();self.count+=1
        requested=np.clip(self.targetq+a*base.DELTA,base.LOW,base.HIGH)
        self.targetq=requested.copy()
        triggered=self.count==self.fault_at
        self.last_contact[:]=False
        for i,d in enumerate(self.data):
            if triggered[i]:continue
            self._command(d,requested[i])
            try:
                for _ in range(SUBSTEPS):mujoco.mj_step(self.model,d)
            except mujoco.FatalError as e:
                raise RuntimeError('MuJoCo failed to integrate a virtual step.') from e
            # Refresh derived body transforms at the final integrated pose.
            mujoco.mj_forward(self.model,d)
            ids={self.gid[n]:j for j,n in enumerate(OBJECT_GEOMS)}
            left={g for g in range(self.model.ngeom) if (mujoco.mj_id2name(self.model,mujoco.mjtObj.mjOBJ_GEOM,g) or '').startswith('left_jaw_')}
            right={g for g in range(self.model.ngeom) if (mujoco.mj_id2name(self.model,mujoco.mjtObj.mjOBJ_GEOM,g) or '').startswith('right_jaw_')}
            fingers=np.zeros((3,2),bool)
            for c in d.contact[:d.ncon]:
                g1=int(c.geom1);g2=int(c.geom2)
                j=ids.get(g1,ids.get(g2))
                if j is None:continue
                other=g2 if g1 in ids else g1
                if other in left:fingers[j,0]=True
                if other in right:fingers[j,1]=True
                if other not in ids:self.last_contact[i]=True
            self.pinched[i]=np.all(fingers,axis=1)
        self._copy_from_physics(range(self.n))
        self.contact_steps+=self.last_contact.astype(int)
        idx=np.arange(self.n)
        lift=self.objects[idx,self.target_obj,2]-base.FLOOR-self.radius[idx,self.target_obj]
        self.ever_lifted|=lift>50.
        phi,success,metrics=self.metrics()
        self.dwell=np.where(success,self.dwell+1,0)
        success=(self.dwell>=4)&(self.count>=8)&(~triggered)
        self.blocked=np.any(np.isclose(self.q[:,:3],base.LOW[:3],atol=.1)|
                            np.isclose(self.q[:,:3],base.HIGH[:3],atol=.1),axis=1)
        reward=np.clip(2*(phi-self.previous_phi),-3.,3.)-.015-.002*np.sum(a*a,1)-self.blocked*.06+success*5.
        reward=np.where(triggered,-.4,reward)
        self.previous_phi=phi;self.returns+=reward
        fallen=((self.objects[idx,self.target_obj,2]<-50.)|
                (np.linalg.norm(self.objects[idx,self.target_obj,:2],axis=1)>850.))
        terminated=success|triggered|fallen
        truncated=(self.count>=220)&(~terminated)
        info=dict(success=success,fault=triggered,fallen=fallen,blocked=self.blocked,
                  **{'return':self.returns.copy(),'steps':self.count.copy(),'task':self.task.copy()},
                  collision=self.last_contact.copy(),contacts_total=self.contact_steps.copy(),**metrics)
        return self.observation(),reward.astype(np.float32),terminated,truncated,info

    def frame(self,i=0):
        frame=super().frame(i)
        frame['tool']=self.tcp[i].tolist()
        frame['physics_backend']='MuJoCo 3D rigid bodies, real contacts and bounded motor torque (uncalibrated)'
        frame['collision_model']='MuJoCo: hollow-jaw convex pieces, coupled fixed-length jaw links, bounded gripping force, solid arm proxies; uncalibrated'
        frame['model_id']=MODEL_VERSION
        d=self.data[i];model=self.model
        def matrix(name):
            bid=model.body(name).id
            t=np.eye(4);t[:3,:3]=d.xmat[bid].reshape(3,3);t[:3,3]=d.xpos[bid]*1000.
            return t.T.reshape(-1).tolist()
        frame['rigid_bodies']={group:matrix(name) for group,name in (
            ('wristMount','wrist_mount'),('wrist','wrist_and_palm'),
            ('jawLeft','left_jaw'),('jawRight','right_jaw'))}
        frame['jaw_angles']=[float(d.qpos[model.jnt_qposadr[self.jid[name]]]) for name in ('left_finger','right_finger')]
        frame['gripper_actuator_force_nm']=float(d.actuator_force[self.aid['motor_gripper']])
        frame['gripper_force_limit_nm']=float(model.actuator_forcerange[self.aid['motor_gripper'],1])
        frame['gripper_requested_opening']=float(self.targetq[i,4])
        frame['gripper_gap_mm']=float(aperture_mm(self.q[i,4]))
        frame['gripper_contact_continues']=True
        frame['tool_servo_count']=2
        for k,name in enumerate(OBJECT_NAMES):
            frame['objects'][k]['quaternion_wxyz']=d.xquat[self.bid[name]].tolist()
        
        frame['object_contact']=bool(self.last_contact[i])
        frame['arm_object_contact']=bool(self.last_contact[i])
        frame['robot_actuator_error']=(self.targetq[i]-self.q[i]).tolist()
        return frame
