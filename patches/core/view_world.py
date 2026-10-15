"""Detailed image observations with temporary helper cameras. Simulation only."""
from __future__ import annotations
import base64,copy,functools,threading
from xml.etree import ElementTree as ET
import numpy as np
import mujoco
from .camera_world import CameraWorld,camera_xml,look_quat
from .mujoco_world import MuJoCoWorld
from .detailed_scene import add_details,update_details
from .view_observation import WIDTH,HEIGHT,NAMES,OBS_SIZE,POLICY_ID,CONTRACT,encode,png
from .view_curriculum import ViewSchedule,MotionDiscovery
from . import world as base

@functools.lru_cache(maxsize=2)
def _xml(mount):
    root=ET.fromstring(camera_xml({'wrist_mount':mount}))
    root=add_details(root)
    wb=root.find('worldbody')
    for name,pos in [('side','.35 -.60 .45'),('front','.80 .10 .40')]:
        ET.SubElement(wb,'camera',name=name,pos=pos,fovy='60')
    root.find('visual/global').set('offwidth',str(WIDTH));root.find('visual/global').set('offheight',str(HEIGHT))
    quality=root.find('visual/quality');quality.set('shadowsize','1024');quality.set('offsamples','2')
    light=root.find(".//light[@name='camera_light']")
    light.set('castshadow','true');light.set('ambient','.28 .28 .28');light.set('diffuse','.8 .8 .8')
    return ET.tostring(root,encoding='unicode')

@functools.lru_cache(maxsize=2)
def _compiled(xml):return mujoco.MjModel.from_xml_string(xml)

class ViewWorld(CameraWorld):
    MODEL_ID=POLICY_ID;observation_contract=CONTRACT
    xml_factory=staticmethod(lambda config:_xml(config['wrist_mount']))
    def _compile_model(self,xml):return copy.copy(_compiled(xml))

    def __init__(self,n=1,seed=41,task='reach',fault_probability=0.,camera_config=None,
                 view_mode='auto',view_stage=0,learning_enabled=False,learning_episode=0):
        if view_mode not in ('auto','all','two'):raise ValueError('Unknown view mode')
        self.view_mode=view_mode;self.view_schedule=ViewSchedule(view_stage)
        self.learning_enabled=bool(learning_enabled);self.learning_episode=int(learning_episode)
        self._views_ready=False;self._resets=0
        self._view_masks=np.ones((int(n),4),bool)
        self.discoveries=[MotionDiscovery() for _ in range(int(n))]
        self.last_discovery=np.zeros(int(n));self.last_task_reward=np.zeros(int(n))
        super().__init__(n,seed,task,fault_probability,camera_config)
        self._camids=[self.model.camera(name).id for name in NAMES]
        self._current=np.zeros((self.n,4,HEIGHT,WIDTH,3),np.uint8);self._previous=self._current.copy()
        self._ages=np.zeros((self.n,4),int);self._available=np.ones((self.n,4),bool)
        self._views_ready=True;self.reset()

    def _sample(self,i):
        super()._sample(i)
        r=self.camera_rng;s=self.scene_settings[i];scale={'fixed':0.,'nearby':1.,'varied':2.}[self.camera_config['profile']]
        # Approximate the existing rear overhead mount and the modeled wrist lens.
        s['overhead_pos']=[-.12+float(r.uniform(-.025,.025))*scale,
                          self.camera_config['overhead_side_m'],
                          self.camera_config['overhead_height_m']+self.floor_heights[i]/1000.]
        s['overhead_target']=[.27,0,.12];s['overhead_fovy']=55+float(r.uniform(-3,3))*scale
        s['wrist_local_pos']=(np.array([.034,0,.045])+r.uniform(-1,1,3)*.003*scale).tolist()
        s['wrist_local_target']=(np.array([.173,0,-.045])+r.uniform(-1,1,3)*.006*scale).tolist()
        s['wrist_fovy']=77+float(r.uniform(-4,4))*scale
        s['side_pos']=[.32,-.65,.42];s['front_pos']=[.78,.15,.38]
        s['helper_target']=[.27,0,.16];s['helper_fovy']=58.
        s['brightness']=1+float(r.uniform(-.07,.07))*scale;s['noise_std']=.7*scale
        s['view_stage']=self.view_schedule.stage;s['view_mode']=self.view_mode
        self._view_masks[i]=self.view_schedule.masks(r,self.view_mode)
        # Some unassisted attempts from early training avoid dependence on helpers.
        # First attempt sees all four; the setting is stable for the entire attempt.
        if self.view_mode=='auto' and self.view_schedule.stage==0 and self._packet_serial[i]>0 and r.random()<.20:
            self._view_masks[i]=[1,1,0,0]
        s['policy_camera_names']=[name for name,ok in zip(NAMES,self._view_masks[i]) if ok]

    def reset(self,ids=None):
        super().reset(ids)
        if self._views_ready:
            ix=range(self.n) if ids is None else ids
            for i in ix:
                self.discoveries[i].reset(self.tcp[i],self.q[i],self.learning_episode)
                self.last_discovery[i]=0.;self.last_task_reward[i]=0.
            self._resets+=1

    def prepare_learning(self,episode,stage):
        self.learning_episode=int(episode);self.view_schedule.stage=int(stage)
        self.learning_enabled=True

    def _render(self,i):
        if self._cached[i] is not None:return
        if self._renderer is None:
            try:self._renderer=mujoco.Renderer(self.model,height=HEIGHT,width=WIDTH)
            except Exception as e:raise RuntimeError('Detailed camera rendering failed. Training is blocked, not replaced with hidden state. '+str(e)) from e
            self._render_thread=threading.get_ident()
        if self._render_thread!=threading.get_ident():raise RuntimeError('Renderer used from wrong thread')
        m,d=self.model,self.data[i];s=self.scene_settings[i]
        self._prepare_environment(i)
        d.mocap_pos[self._goal_mocap]=self.goal[i]/1000.
        positions=[s['overhead_pos'],s['wrist_local_pos'],s['side_pos'],s['front_pos']]
        targets=[s['overhead_target'],s['wrist_local_target'],s['helper_target'],s['helper_target']]
        fov=[s['overhead_fovy'],s['wrist_fovy'],s['helper_fovy'],s['helper_fovy']]
        for cid,p,t,f in zip(self._camids,positions,targets,fov):
            m.cam_pos[cid]=p;m.cam_quat[cid]=look_quat(p,t);m.cam_fovy[cid]=f
        update_details(self,i);mujoco.mj_forward(m,d)
        option=mujoco.MjvOption();option.geomgroup[1]=0;option.geomgroup[3]=1
        images=np.zeros_like(self._current[i]);available=self._view_masks[i].copy()
        previous=self._current[i].copy()
        for k,cid in enumerate(self._camids):
            if not available[k]:continue
            self._renderer.update_scene(d,camera=int(cid),scene_option=option)
            im=self._renderer.render().copy().astype(np.float32)*s['brightness']
            if s['noise_std']:im+=self.camera_rng.normal(0,s['noise_std'],im.shape)
            images[k]=np.clip(im,0,255).astype(np.uint8)
        self._ages[i]=0
        if self.camera_config['frame_faults']:
            for k in range(2):
                if self.camera_rng.random()<.015:
                    images[k]=0;available[k]=False;self._ages[i,k]=5
        self._available[i]=available
        self._previous[i]=previous if self.count[i]>0 else images
        self._current[i]=images;self._packet_serial[i]+=1
        self._cached[i]=encode(images,self._previous[i],int(self.task[i]),int(self.target_obj[i]),
            float(self.wrist_goal[i]),float(self.gap_goal[i]),self._previous_action[i],available,self._ages[i])

    def observation(self):
        if not self._views_ready:return np.zeros((self.n,OBS_SIZE),np.float32)
        for i in range(self.n):self._render(i)
        return np.stack(self._cached).copy()

    def step(self,actions):
        self.observation();a=np.asarray(actions,float)
        if a.shape!=(self.n,5) or not np.isfinite(a).all():raise ValueError('Five finite requested controls required')
        for i in np.where(np.all(~self._available[:,:2],axis=1))[0]:
            self.episode_done[i]=True;self.physics_failures[i]=True;self.guard_reason[i]='both mounted cameras unavailable'
        oldq=self.q.copy();self._cached=[None]*self.n;self._previous_action=a.copy()
        obs,reward,terminated,truncated,info=MuJoCoWorld.step(self,a)
        self.last_task_reward=reward.copy();self.last_discovery[:]=0
        if self.learning_enabled:
            for i in range(self.n):
                if np.linalg.norm(a[i])>.05:
                    self.last_discovery[i]=self.discoveries[i].reward(self.tcp[i],self.q[i],oldq[i],
                        invalid=bool(self.physics_failures[i] or info['fault'][i] or info['fallen'][i]))
            reward=reward+self.last_discovery.astype(np.float32);self.returns+=self.last_discovery
        info['discovery_bonus']=self.last_discovery.copy();info['task_reward']=self.last_task_reward.copy()
        info['return']=self.returns.copy()
        return obs,reward,terminated,truncated,info

    def frame(self,i=0):
        f=MuJoCoWorld.frame(self,i);self._render(i)
        c={'source':'Detailed simulated views; estimated mounts, not Pi video',
           'policy_input':'RGB only, instructions, prior requests and view validity',
           'valid':self._available[i].tolist(),'age_frames':self._ages[i].tolist(),
           'policy_camera_names':[name for name,ok in zip(NAMES,self._view_masks[i]) if ok],
           'settings':self.scene_settings[i],'sequence':int(self._packet_serial[i]),
           'resolution':[WIDTH,HEIGHT],'helper_views_temporary':True}
        for k,name in enumerate(NAMES):c[name]=base64.b64encode(png(self._current[i,k])).decode()
        f.update(cameras=c,observation_mode='masked_rgb_views',model_id=POLICY_ID,
            base_height_offset_mm=float(self.floor_heights[i]-base.FLOOR),
            table_clearance_mm=round(self.table_clearance(i)*1000,3),safety_abort=self.guard_reason[i],
            camera_mount_is_measured=False,discovery_bonus=float(self.last_discovery[i]),
            task_reward=float(self.last_task_reward[i]),discovery_cells=self.discoveries[i].new_cells,
            discovery_reward_is_skill=False)
        return f
