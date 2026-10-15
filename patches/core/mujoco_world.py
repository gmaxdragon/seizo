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
OBJECT_RADII=np.array([12.,12.,13.])
OBJECT_HALFHEIGHT=np.array([12.,30.,13.])

def rx(a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[1.,0.,0.],[0.,c,-s],[0.,s,c]])

def rz(a):
    c,s=math.cos(a),math.sin(a)
    return np.array([[c,-s,0.],[s,c,0.],[0.,0.,1.]])

def rotation_error(a,b):
    value=(np.einsum('nij,nij->n',a,b)-1.)*.5
    return np.arccos(np.clip(value,-1.,1.))*DEG



class MuJoCoWorld(base.World):
    """MuJoCo CPU contact simulation in independent environments, never hardware."""
    MODEL_ID=MODEL_VERSION

    def __init__(self,n=1,seed=41,task='reach',fault_probability=0.0,xml_text=None):
        self._physics_ready=False
        self.tcp=np.zeros((int(n),3))
        self.object_rotations=np.tile(np.eye(3),(int(n),3,1,1))
        self.goal_rotation=np.tile(np.eye(3),(int(n),1,1))
        self.object_angular_vel=np.zeros((int(n),3,3))
        self.ever_gripped=np.zeros(int(n),bool)
        self.episode_done=np.zeros(int(n),bool)
        self.contacts=[{} for _ in range(int(n))]
        self.physics_failures=np.zeros(int(n),bool)
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
        self.object_gid_map={self.gid[name]:j for j,name in enumerate(OBJECT_GEOMS)}
        self.left_geoms={i for i in range(self.model.ngeom) if (self.model.geom(i).name or '').startswith('left_jaw_')}
        self.right_geoms={i for i in range(self.model.ngeom) if (self.model.geom(i).name or '').startswith('right_jaw_')}
        self.robot_bodies={i for i in range(1,self.model.nbody) if self.model.body(i).name not in OBJECT_NAMES}
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
                self.object_angular_vel[i,j]=d.qvel[self.objvadr[j]+3:self.objvadr[j]+6]
                self.object_rotations[i,j]=d.xmat[self.bid[bname]].reshape(3,3)
            self.tcp[i]=d.site_xpos[self.sid]*1000.

    def reset(self,ids=None):
        super().reset(ids)
        if not self._physics_ready:return
        ids=np.arange(self.n) if ids is None else np.asarray(ids,dtype=int)
        for i in ids:
            d=self.data[int(i)];m=self.model
            mujoco.mj_resetData(m,d)
            self.radius[i]=OBJECT_RADII
            self.objects[i,:,2]=base.FLOOR+OBJECT_HALFHEIGHT
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
                self.objects[i,chosen,2]=base.FLOOR+OBJECT_HALFHEIGHT[chosen]
                delta=self.rng.uniform(-np.pi,np.pi)
                shift=self.rng.uniform(40.,65.)
                self.goal[i]=self.objects[i,chosen]+[math.cos(delta)*shift,math.sin(delta)*shift,0.]
                if task==3:self.goal[i]=self.objects[i,chosen]+[0.,0.,70.]
            # Rotation lessons use a box or bottle-shaped cylinder, not a sphere
            # whose orientation would be ambiguous. Nothing is attached at reset.
            self.object_rotations[i]=np.eye(3)
            if task>=5:
                chosen=int(self.rng.integers(0,2));self.target_obj[i]=chosen
                angle=float(self.rng.choice([0.,90.,-90.]))*RAD
                self.object_rotations[i,chosen]=rz(self.q[i,0]*RAD)@rx(angle)
                self.wrist_goal[i]=float(angle*DEG + self.rng.choice([-90.,90.]))
                self.goal_rotation[i]=rz(self.q[i,0]*RAD)@rx(self.wrist_goal[i]*RAD)
                self.objects[i,chosen,:2]=tcp[:2]+self.rng.uniform(-6,6,2)
                self.objects[i,chosen,2]=base.FLOOR+self.support_height(i,chosen)
                if task==5:
                    self.goal[i]=self.objects[i,chosen]+[0.,0.,55.]
                else:
                    self.goal[i]=self.objects[i,chosen]+[self.rng.uniform(-35.,35.),self.rng.uniform(-35.,35.),0.]
            else:
                self.goal_rotation[i]=rz(self.q[i,0]*RAD)@rx(self.wrist_goal[i]*RAD)
            for j in range(3):
                adr=self.objadr[j]
                d.qpos[adr:adr+3]=self.objects[i,j]/1000.
                mujoco.mju_mat2Quat(d.qpos[adr+3:adr+7],self.object_rotations[i,j].reshape(-1))
            d.qvel[:]=0
            self._set_pose(d,self.q[i]);mujoco.mj_forward(m,d)
            self._copy_from_physics((i,))
            self.pinched[i]=False;self.ever_gripped[i]=False;self.episode_done[i]=False;self.physics_failures[i]=False
            self.contacts[i]={'arm_object':False,'jaw_object':False,'environment':False,'self':False,'pairs':[],'jaw_force_n':0.}
            self.previous_tcp[i]=self.tcp[i]
        self.previous_phi[ids]=self.metrics()[0][ids]

    def support_height(self,i,j):
        """Actual shape half-height above its lowest point, estimated millimetres."""
        r=self.object_rotations[i,j]
        if j==0:return 12.*float(np.abs(r[2]).sum())
        if j==1:
            c=abs(float(r[2,2]));return 30.*c+12.*math.sqrt(max(0.,1.-c*c))
        return 13.

    def floor_clearance(self):
        return np.array([self.objects[i,j,2]-base.FLOOR-self.support_height(i,j)
                         for i,j in enumerate(self.target_obj)])

    def contact_state(self,i):
        """Only positive-force, solver-active contacts are evidence of touch.
        Table/object, arm/object, finger/object and robot/environment are distinct.
        """
        d=self.data[i];m=self.model
        state={'arm_object':False,'jaw_object':False,'environment':False,'self':False,
               'pairs':[],'jaw_force_n':0.,'floor_object_count':0}
        fingers=np.zeros((3,2),bool)
        for k,c in enumerate(d.contact[:d.ncon]):
            if c.efc_address<0:continue
            force=np.zeros(6);mujoco.mj_contactForce(m,d,k,force)
            if not np.isfinite(force).all() or force[0]<=1e-4:continue
            g1,g2=int(c.geom1),int(c.geom2)
            o1,o2=self.object_gid_map.get(g1),self.object_gid_map.get(g2)
            b1,b2=int(m.geom_bodyid[g1]),int(m.geom_bodyid[g2])
            robot1,robot2=b1 in self.robot_bodies,b2 in self.robot_bodies
            j=o1 if o1 is not None else o2
            if j is not None:
                other=g2 if o1 is not None else g1
                if int(m.geom_bodyid[other]) in self.robot_bodies:
                    state['arm_object']=True
                    jaw=other in self.left_geoms or other in self.right_geoms
                    if other in self.left_geoms:fingers[j,0]=True
                    if other in self.right_geoms:fingers[j,1]=True
                    if jaw:state['jaw_object']=True;state['jaw_force_n']+=float(force[0])
                    category='jaw-object' if jaw else 'arm-object'
                elif m.geom(other).name=='desk':
                    state['floor_object_count']+=1;continue
                else:continue
            elif robot1 and robot2:
                state['self']=True;category='robot-self'
            elif robot1 or robot2:
                state['environment']=True;category='robot-environment'
            else:continue
            state['pairs'].append({'a':m.geom(g1).name,'b':m.geom(g2).name,'kind':category,
                                  'normal_n':round(float(force[0]),6),'penetration_mm':round(max(0.,-float(c.dist)*1000.),6)})
        state['pairs']=state['pairs'][:32]
        self.pinched[i]=np.all(fingers,axis=1);self.last_contact[i]=state['arm_object'];self.contacts[i]=state
        return state

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
        lift=np.maximum(0.,self.floor_clearance())
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
        angle_error=rotation_error(self.object_rotations[idx,self.target_obj],self.goal_rotation)
        # Reward object orientation, not merely a turned empty hand. No scripted
        # actions, welding, grasp teleportation, or successful-trial substitution.
        rotate_phi=-reach/75.+held*.5+np.minimum(lift/40.,1.)+self.ever_gripped*(1.-angle_error/90.)
        place_phi=rotate_phi+self.ever_lifted*(1.-np.minimum(objgoal/70.,3.))
        phi=np.where(self.task==5,rotate_phi,phi)
        phi=np.where(self.task==6,place_phi,phi)
        success=distance<18.
        success=np.where(self.task==1,(distance<22.)&(werr<12.)&(gerr<.12),success)
        success=np.where(self.task==2,(objgoal<18.)&(np.abs(self.floor_clearance())<8.),success)
        success=np.where(self.task==3,(lift>60.)&held,success)
        success=np.where(self.task==4,self.ever_lifted&(np.linalg.norm(obj[:,:2]-self.goal[:,:2],axis=1)<20.)&
                         (np.abs(self.floor_clearance())<6.)&(~held)&(np.linalg.norm(self.ov[idx,self.target_obj],axis=1)<40.),success)
        slow=(np.linalg.norm(self.ov[idx,self.target_obj],axis=1)<25.)&(np.linalg.norm(self.object_angular_vel[idx,self.target_obj],axis=1)<.8)
        success=np.where(self.task==5,(lift>25.)&held&(angle_error<12.),success)
        success=np.where(self.task==6,self.ever_lifted&self.ever_gripped&(np.linalg.norm(obj[:,:2]-self.goal[:,:2],axis=1)<20.)&
                         (np.abs(self.floor_clearance())<6.)&(~held)&slow&(angle_error<12.),success)
        return phi,success,dict(distance=distance,object_distance=objgoal,lift=lift,wrist_error=werr,grip=held,object_angle_error=angle_error)

    def observation(self):
        tcp=self.tcp
        idx=np.arange(self.n);obj=self.objects[idx,self.target_obj]
        onehot=np.eye(len(base.TASKS))[self.task]
        normalized_q=(self.q-base.LOW)/(base.HIGH-base.LOW)*2.-1.
        normalized_q[:,3]=base.angular_error(self.q[:,3],0.)/180.
        raw=np.concatenate([
            normalized_q,
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
            self.object_rotations[idx,self.target_obj,:,:2].reshape(self.n,6),
            self.goal_rotation[:,:,:2].reshape(self.n,6),
            self.object_angular_vel[idx,self.target_obj]/10.,
            self.ever_gripped[:,None].astype(float),
        ],axis=1)
        assert raw.shape==(self.n,base.OBS_SIZE),raw.shape
        return np.clip(raw,-5.,5.).astype(np.float32)

    def step(self,actions):
        a=np.asarray(actions,dtype=float)
        if a.shape!=(self.n,5) or not np.isfinite(a).all():raise ValueError('Five finite simulation controls required.')
        a=np.clip(a,-1.,1.)
        active=~self.episode_done
        a=np.where(active[:,None],a,0.)
        self.last_action=a.copy();self.count+=active.astype(int)
        requested=np.clip(self.targetq+a*base.DELTA,base.LOW,base.HIGH)
        # Full axial roll is periodic in simulation. Bound incremental commands
        # and maximum following error instead of falsely limiting travel to 150 deg.
        requested[:,3]=np.clip(self.targetq[:,3]+a[:,3]*base.DELTA[3],self.q[:,3]-60.,self.q[:,3]+60.)
        requested=np.where(active[:,None],requested,self.targetq)
        self.targetq=requested.copy()
        triggered=self.count==self.fault_at
        self.last_contact[:]=False
        for i,d in enumerate(self.data):
            if triggered[i] or not active[i]:continue
            self._command(d,requested[i])
            try:
                for _ in range(SUBSTEPS):mujoco.mj_step(self.model,d)
            except mujoco.FatalError as e:
                raise RuntimeError('MuJoCo failed to integrate a virtual step.') from e
            # Refresh derived body transforms at the final integrated pose.
            mujoco.mj_forward(self.model,d)
            self.contact_state(i)
        self._copy_from_physics(range(self.n))
        self.contact_steps+=self.last_contact.astype(int)
        idx=np.arange(self.n)
        lift=self.floor_clearance()
        self.ever_gripped|=self.pinched[idx,self.target_obj]
        self.ever_lifted|=lift>50.
        phi,success,metrics=self.metrics()
        self.dwell=np.where(success,self.dwell+1,0)
        success=(self.dwell>=4)&(self.count>=8)&(~triggered)
        self.blocked=np.any(np.isclose(self.q[:,:3],base.LOW[:3],atol=.1)|
                            np.isclose(self.q[:,:3],base.HIGH[:3],atol=.1),axis=1)
        reward=np.clip(2*(phi-self.previous_phi),-3.,3.)-.015-.002*np.sum(a*a,1)-self.blocked*.06+success*5.
        reward=np.where(triggered,-.4,reward)
        reward=np.where(active,reward,0.)
        self.previous_phi=phi;self.returns+=reward
        fallen=((self.objects[idx,self.target_obj,2]<-50.)|
                (np.linalg.norm(self.objects[idx,self.target_obj,:2],axis=1)>850.))
        self.physics_failures|=~np.isfinite(self.q).all(axis=1)|~np.isfinite(self.objects).all(axis=(1,2))
        terminated=success|triggered|fallen|self.physics_failures
        truncated=(self.count>=220)&(~terminated)
        self.episode_done|=terminated|truncated
        info=dict(success=success,fault=triggered,fallen=fallen,blocked=self.blocked,
                  **{'return':self.returns.copy(),'steps':self.count.copy(),'task':self.task.copy()},
                  collision=self.last_contact.copy(),contacts_total=self.contact_steps.copy(),invalid_physics=self.physics_failures.copy(),**metrics)
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
        state=self.contact_state(i)
        frame['contacts']=state
        frame['gripper_contact_continues']=bool(state['jaw_object'] and self.targetq[i,4]<self.q[i,4]-.01)
        frame['gripper_object_contact']=bool(state['jaw_object'])
        frame['roll_degrees']=float(self.q[i,3])
        frame['roll_modulo_degrees']=float(self.q[i,3]%360.)
        frame['roll_axis']='longitudinal: wrist toward fingertips'
        frame['object_orientation_error_degrees']=float(self.metrics()[2]['object_angle_error'][i])
        qtarget=np.zeros(4);mujoco.mju_mat2Quat(qtarget,self.goal_rotation[i].reshape(-1))
        frame['target_orientation_wxyz']=qtarget.tolist()
        frame['tool_servo_count']=2
        for k,name in enumerate(OBJECT_NAMES):
            frame['objects'][k]['quaternion_wxyz']=d.xquat[self.bid[name]].tolist()
            frame['objects'][k]['radius']=float(OBJECT_RADII[k])
            frame['objects'][k]['half_height']=float(OBJECT_HALFHEIGHT[k])
            frame['objects'][k]['contact_from_jaws']=bool(self.pinched[i,k])
        
        frame['object_contact']=bool(self.last_contact[i])
        frame['arm_object_contact']=bool(self.last_contact[i])
        frame['robot_actuator_error']=(self.targetq[i]-self.q[i]).tolist()
        return frame
