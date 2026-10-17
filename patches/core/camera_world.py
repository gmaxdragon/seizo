"""Two *rendered RGB* camera observations over the existing rigid-body environment.

Actor/critic inputs are generated only by camera_observation.encode. Exact
simulation state remains available to the physics solver, reward/evaluation
code, deterministic table guard, and human debug view, NOT the neural input.
"""
from __future__ import annotations
import base64, math, threading
from xml.etree import ElementTree as ET
import numpy as np
import mujoco
from .mujoco_world import MuJoCoWorld
from .mjcf import xml_model, SUBSTEPS
from . import world as base
from .camera_observation import WIDTH,HEIGHT,OBS_SIZE,POLICY_ID,CONTRACT,encode,png

PROFILES=('fixed','nearby','varied')
DEFAULT_CONFIG={'profile':'nearby','overhead_height_m':.65,'overhead_side_m':-.10,
                'wrist_mount':'before_roll','frame_faults':False,'framing':'workspace','wrist_height_m':.075}
CONFIG_LIMITS={'overhead_height_m':(.45,1.4),'overhead_side_m':(-.6,.6),'wrist_height_m':(.045,.11)}
def validate_config(value=None):
    c=dict(DEFAULT_CONFIG)
    if value:
        if not isinstance(value,dict) or set(value)-set(c):raise ValueError('Unknown camera setting')
        c.update(value)
    if c['framing'] not in ('workspace','full'):raise ValueError('Unknown camera framing')
    if c['profile'] not in PROFILES:raise ValueError('Unknown camera-variation profile')
    if c['wrist_mount'] not in ('before_roll','with_roll'):raise ValueError('Unknown wrist-camera mount')
    if type(c['frame_faults']) is not bool:raise ValueError('Frame faults must be on/off')
    for k,(lo,hi) in CONFIG_LIMITS.items():
        if isinstance(c[k],bool) or not np.isfinite(float(c[k])) or not lo<=float(c[k])<=hi:
            raise ValueError(f'{k} is outside the documented simulation range')
        c[k]=float(c[k])
    return c

def look_quat(position,target,up=(0,0,1)):
    p=np.asarray(position,float);target=np.asarray(target,float)
    z=p-target;z/=np.linalg.norm(z)
    u=np.asarray(up,float)
    if abs(np.dot(z,u))>.97:u=np.array([0.,1.,0.])
    x=np.cross(u,z);x/=np.linalg.norm(x);y=np.cross(z,x)
    quat=np.zeros(4);mujoco.mju_mat2Quat(quat,np.column_stack([x,y,z]).reshape(-1))
    return quat

def camera_xml(config):
    root=ET.fromstring(xml_model());wb=root.find('worldbody')
    # Simple rendering of the *physics* assembly, not a synthetic photo/video.
    ET.SubElement(wb,'light',name='camera_light',pos='.3 -.3 1.2',dir='0 0 -1',
                  diffuse='.75 .75 .75',ambient='.35 .35 .35',castshadow='false')
    ET.SubElement(wb,'camera',name='overhead',pos='-.20 -.18 .865',fovy='76')
    parent=root.find(".//body[@name='%s']"%('wrist_mount' if config['wrist_mount']=='before_roll' else 'wrist_and_palm'))
    ET.SubElement(parent,'camera',name='wrist',pos='.015 -.040 .045',fovy='85')
    # A requested destination is a visible marker, not a true XYZ actor input.
    goal=ET.SubElement(wb,'body',name='requested_goal_marker',mocap='true',pos='.40 0 .16')
    ET.SubElement(goal,'geom',name='goal_marker',type='sphere',size='.010',rgba='1 .15 .75 1',
                  contype='0',conaffinity='0',group='2')
    hand=root.find(".//body[@name='wrist_and_palm']")
    # Only the 7 mm projection was supplied by the user. Width/length are estimates.
    for name,sign in [('rear_upper_tab',1),('rear_lower_tab',-1)]:
        ET.SubElement(hand,'geom',name=name,type='box',pos=f'.050 0 {sign*.0175}',
                      size='.010 .013 .0035',mass='.003',rgba='.86 .86 .82 1')
    visual=root.find('visual')
    if visual is None:visual=ET.SubElement(root,'visual')
    ET.SubElement(visual,'global',offwidth=str(WIDTH),offheight=str(HEIGHT))
    ET.SubElement(visual,'quality',shadowsize='256',offsamples='0')
    return ET.tostring(root,encoding='unicode')

class CameraWorld(MuJoCoWorld):
    xml_factory=staticmethod(camera_xml)
    MODEL_ID=POLICY_ID
    image_policy=True
    training_envs=1
    observation_contract=CONTRACT

    def __init__(self,n=1,seed=41,task='reach',fault_probability=0.,camera_config=None):
        if not 1<=int(n)<=2:raise ValueError('Camera batches are limited to two environments; evaluations are chunked.')
        self.camera_config=validate_config(camera_config)
        self.camera_rng=np.random.default_rng(seed+7933)
        self.floor_heights=np.full(int(n),base.FLOOR)
        self.scene_settings=[None]*int(n);self.guard_reason=['']*int(n)
        # Reject unsafe simulated actions while allowing bounded exploration.
        self.consecutive_guard_rejections=np.zeros(int(n),dtype=np.int32)
        self._camera_ready=False;self._renderer=None;self._render_thread=None
        self._cached=[None]*int(n);self._current=np.zeros((int(n),2,HEIGHT,WIDTH,3),np.uint8)
        self._previous=self._current.copy()
        self._ages=np.zeros((int(n),2),int);self._available=np.ones((int(n),2),bool)
        self._packet_serial=np.zeros(int(n),int);self._previous_action=np.zeros((int(n),5))
        super().__init__(n=n,seed=seed,task=task,fault_probability=fault_probability,
                         xml_text=self.xml_factory(self.camera_config))
        self._camera_ready=True
        self._camids=[self.model.camera(name).id for name in ('overhead','wrist')]
        self._goal_mocap=int(self.model.body_mocapid[self.model.body('requested_goal_marker').id])
        self._hand_geoms=[]
        for gid in range(self.model.ngeom):
            body=int(self.model.geom_bodyid[gid])
            while body:
                if self.model.body(body).name in ('wrist_and_palm','wrist_mount'):
                    if int(self.model.geom_contype[gid]):self._hand_geoms.append(gid)
                    break
                body=int(self.model.body_parentid[body])
        self.reset()

    def _sample(self,i):
        c=self.camera_config;scale={'fixed':0.,'nearby':1.,'varied':2.}[c['profile']]
        r=self.camera_rng
        self.floor_heights[i]=base.FLOOR+float(r.uniform(-4,4))*scale
        # Camera height is above the support plane, not the room's absolute floor.
        overhead=np.array([-.10,c['overhead_side_m'],c['overhead_height_m']+self.floor_heights[i]/1000.])
        overhead+=r.uniform(-1,1,3)*[.07,.08,.08]*scale
        target=np.array([.27,0,.15])+r.uniform(-1,1,3)*[.035,.04,.025]*scale
        wrist=np.array([.015,-.040,.045])+r.uniform(-1,1,3)*.008*scale
        wrist_target=np.array([.169,0,-.006])+r.uniform(-1,1,3)*.012*scale
        floor_colors=np.array([[.24,.18,.13],[.06,.10,.16],[.43,.43,.41]])
        color=floor_colors[int(r.integers(3))] if scale else floor_colors[0]
        self.scene_settings[i]={'overhead_pos':overhead.tolist(),'overhead_target':target.tolist(),
             'wrist_local_pos':wrist.tolist(),'wrist_local_target':wrist_target.tolist(),
             'overhead_fovy':float(62+r.uniform(-5,5)*scale),
             'wrist_fovy':float(85+r.uniform(-7,7)*scale),'floor_rgb':color.tolist(),
             'brightness':float(1+r.uniform(-.12,.12)*scale),'noise_std':float(1.5*scale),
             'floor_height_mm':float(self.floor_heights[i]),'profile':c['profile'],
             'mount':c['wrist_mount'],'measured':False}

    def reset(self,ids=None):
        ids=np.arange(self.n) if ids is None else np.asarray(ids,int)
        if not len(ids):return
        for i in ids:
            self._sample(int(i));self.guard_reason[int(i)]=''
            self.consecutive_guard_rejections[int(i)]=0
            self._cached[int(i)]=None;self._current[int(i)]=0;self._previous[int(i)]=0
            self._ages[int(i)]=0;self._available[int(i)]=True;self._previous_action[int(i)]=0
        super().reset(ids)
        if self._camera_ready:
            # Reject unsafe initial poses. This is reset sampling, never a teacher action.
            for i in ids:
                d=self.data[int(i)]
                for _ in range(20):
                    self._prepare_environment(int(i));mujoco.mj_forward(self.model,d)
                    if self.table_clearance(int(i))>=.030:break
                    q=self.q[int(i)].copy();q[1]=min(90,q[1]+4);q[2]=min(10,q[2]+3)
                    self.q[int(i)]=q;self.targetq[int(i)]=q;self._set_pose(d,q)
                else:raise RuntimeError('No safe initial hand pose could be sampled')
                # Sample non-penetrating object positions; this happens only at reset.
                for _ in range(40):
                    mujoco.mj_forward(self.model,d)
                    bad=set()
                    for contact in d.contact[:d.ncon]:
                        if contact.dist<-.0003:
                            for gid in (int(contact.geom1),int(contact.geom2)):
                                if gid in self.object_gid_map:bad.add(self.object_gid_map[gid])
                    if not bad:break
                    for j in bad:
                        d.qpos[self.objadr[j]:self.objadr[j]+2]=[self.rng.uniform(.25,.53),self.rng.uniform(-.18,.18)]
                else:raise RuntimeError('A collision-free object start could not be sampled')
                self._copy_from_physics((int(i),))
                if int(self.task[i])<=1:
                    # Sample a goal from a different, table-clear hand pose.
                    # This is goal construction at reset, not a teacher action.
                    current=self.q[int(i)].copy()
                    accepted_goal=None
                    for _ in range(80):
                        candidate=current.copy()
                        candidate[:4]+=self.rng.uniform(-1.,1.,4)*[25.,18.,18.,40.]
                        candidate=np.clip(candidate,base.LOW,base.HIGH)
                        self._set_pose(d,candidate);mujoco.mj_forward(self.model,d)
                        goal=d.site_xpos[self.sid]*1000.
                        if self.table_clearance(int(i))>=.012 and np.linalg.norm(goal-self.tcp[int(i)])>25.:
                            accepted_goal=goal.copy()
                            if int(self.task[i])==1:self.wrist_goal[int(i)]=candidate[3]
                            break
                    self._set_pose(d,current);mujoco.mj_forward(self.model,d)
                    if accepted_goal is None:raise RuntimeError('A table-clear camera-learning target could not be sampled')
                    self.goal[int(i)]=accepted_goal
                    self._copy_from_physics((int(i),))
                self.previous_phi[int(i)]=self.metrics()[0][int(i)]

    def _prepare_environment(self,i):
        super()._prepare_environment(i)
        self.model.body_pos[self.model.body('base_foot').id,2]=(self.floor_heights[i]-base.FLOOR)/1000.

    def table_clearance(self,i):
        """Exact support function of collision geoms, not TCP-only clearance."""
        m=self.model;d=self.data[i];low=float('inf')
        for gid in self._hand_geoms:
            zrow=d.geom_xmat[gid].reshape(3,3)[2];size=m.geom_size[gid];typ=int(m.geom_type[gid])
            if typ==int(mujoco.mjtGeom.mjGEOM_MESH):
                mid=int(m.geom_dataid[gid]);start=int(m.mesh_vertadr[mid]);n=int(m.mesh_vertnum[mid])
                lower=float(np.min(m.mesh_vert[start:start+n]@zrow))
            elif typ==int(mujoco.mjtGeom.mjGEOM_BOX):lower=-float(np.abs(zrow)@size)
            elif typ==int(mujoco.mjtGeom.mjGEOM_CAPSULE):lower=-float(size[0]+abs(zrow[2])*size[1])
            elif typ==int(mujoco.mjtGeom.mjGEOM_CYLINDER):
                lower=-float(size[0]*np.linalg.norm(zrow[:2])+abs(zrow[2])*size[1])
            else:lower=-float(size[0])
            low=min(low,float(d.geom_xpos[gid,2])+lower)
        return low-self.floor_heights[i]/1000.

    def _integrate(self,i):
        if not self._camera_ready:return super()._integrate(i)
        m=self.model;d=self.data[i]
        # Roll an unsafe simulator command back to the last accepted state.
        # Penalize the command via ViewWorld.step, permitting more exploration.
        # Repeated rejected commands terminate after 12 failures.
        state_spec=int(mujoco.mjtState.mjSTATE_INTEGRATION)
        before=np.empty(mujoco.mj_stateSize(m,state_spec))
        mujoco.mj_getState(m,d,before,state_spec)
        for _ in range(SUBSTEPS):
            mujoco.mj_step(m,d);mujoco.mj_forward(m,d)
            reason=''
            if self.table_clearance(i)<.0015:reason='table-clearance guard'
            for c in d.contact[:d.ncon]:
                g1,g2=int(c.geom1),int(c.geom2)
                if c.dist<-.001 and ((g1 in self.object_gid_map and int(m.geom_bodyid[g2]) in self.robot_bodies)
                                    or (g2 in self.object_gid_map and int(m.geom_bodyid[g1]) in self.robot_bodies)):
                    reason='excess penetration guard';break
            if reason:
                mujoco.mj_setState(m,d,before,state_spec);mujoco.mj_forward(m,d)
                self.targetq[i]=self.q[i].copy();self._command(d,self.targetq[i])
                self.consecutive_guard_rejections[i]+=1
                self.guard_reason[i]=reason
                if self.consecutive_guard_rejections[i]>=12:
                    self.physics_failures[i]=True
                return
        self.consecutive_guard_rejections[i]=0
        self.guard_reason[i]=''

    def _render(self,i):
        if self._cached[i] is not None:return
        if self._renderer is None:
            try:self._renderer=mujoco.Renderer(self.model,height=HEIGHT,width=WIDTH)
            except Exception as e:
                raise RuntimeError('The two camera images could not render. Vision training is blocked, not replaced with hidden coordinates. '+str(e)) from e
            self._render_thread=threading.get_ident()
        if self._render_thread!=threading.get_ident():raise RuntimeError('Camera renderer must stay on its owning thread')
        m=self.model;d=self.data[i];spec=self.scene_settings[i];self._prepare_environment(i)
        m.geom_rgba[m.geom('desk').id,:3]=spec['floor_rgb']
        d.mocap_pos[self._goal_mocap]=self.goal[i]/1000.
        m.geom_rgba[m.geom('goal_marker').id]=[1.,.15,.75,1.]
        for cid,p,t,fovy in zip(self._camids,[spec['overhead_pos'],spec['wrist_local_pos']],
                               [spec['overhead_target'],spec['wrist_local_target']],
                               [spec['overhead_fovy'],spec['wrist_fovy']]):
            m.cam_pos[cid]=p;m.cam_quat[cid]=look_quat(p,t);m.cam_fovy[cid]=fovy
        mujoco.mj_forward(m,d)
        previous=self._current[i].copy();images=[]
        for cid in self._camids:
            self._renderer.update_scene(d,camera=int(cid))
            im=self._renderer.render().copy().astype(np.float32)
            im*=spec['brightness']
            if spec['noise_std']:im+=self.camera_rng.normal(0,spec['noise_std'],im.shape)
            images.append(np.clip(im,0,255).astype(np.uint8))
        images=np.stack(images)
        self._available[i]=True;self._ages[i]=0
        if self.camera_config['frame_faults']:
            for k in range(2):
                if self.camera_rng.random()<.015:
                    images[k]=previous[k];self._available[i,k]=False;self._ages[i,k]=5
        self._previous[i]=previous if self.count[i]>0 else images
        self._current[i]=images
        self._packet_serial[i]+=1
        self._cached[i]=encode(images,self._previous[i],int(self.task[i]),int(self.target_obj[i]),
              float(self.wrist_goal[i]),float(self.gap_goal[i]),self._previous_action[i],
              self._available[i],self._ages[i])

    def observation(self):
        if not self._camera_ready:return np.zeros((self.n,OBS_SIZE),np.float32)
        for i in range(self.n):self._render(i)
        return np.stack(self._cached).copy()

    def step(self,actions):
        # Driver availability is known, unlike actual joint positions.
        self.observation()
        unsafe=np.all(~self._available,axis=1)
        for i in np.where(unsafe)[0]:
            self.episode_done[i]=True;self.physics_failures[i]=True;self.guard_reason[i]='both camera frames unavailable'
        self._cached=[None]*self.n;self._previous_action=np.asarray(actions,float).copy()
        return super().step(actions)

    def frame(self,i=0):
        f=super().frame(i);self._render(i)
        f['cameras']={'source':'simulated RGB, not Pi video','policy_input':'only these RGB frames, their previous frames and task instructions',
            'overhead':base64.b64encode(png(self._current[i,0])).decode(),
            'wrist':base64.b64encode(png(self._current[i,1])).decode(),
            'valid':self._available[i].tolist(),'age_frames':self._ages[i].tolist(),
            'settings':self.scene_settings[i],'sequence':int(self._packet_serial[i])}
        f['observation_mode']='two_rgb_cameras'
        f['base_height_offset_mm']=float(self.floor_heights[i]-base.FLOOR)
        f['model_id']=POLICY_ID
        f['table_clearance_mm']=round(self.table_clearance(i)*1000,3)
        f['safety_abort']=self.guard_reason[i]
        f['camera_mount_is_measured']=False
        return f

    def close(self):
        if self._renderer is not None:
            self._renderer.close();self._renderer=None
