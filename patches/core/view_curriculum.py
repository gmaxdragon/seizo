"""Explicit curriculum and bounded discovery reward, never a solved controller."""
import math
import numpy as np

STAGES=('Explore with helper views','Fade helper views','Wrist + overhead only')

class ViewSchedule:
    def __init__(self,stage=0,streak=0):
        if int(stage) not in (0,1,2):raise ValueError('Invalid view stage')
        self.stage=int(stage);self.streak=max(0,int(streak))
    def masks(self,rng,mode='auto'):
        if mode not in ('auto','all','two'):raise ValueError('Invalid view mode')
        if mode=='two' or (mode=='auto' and self.stage==2):return np.array([1,1,0,0],bool)
        # Start with everything. In the fading phase use whole-trial helper dropout.
        if mode=='all' or self.stage==0:return np.ones(4,bool)
        return np.array([True,True,bool(rng.random()<.5),bool(rng.random()<.5)])
    def observe_test(self,result):
        # Twenty fresh two-view trials, no invalid-physics successes; twice in a row.
        valid=(result.get('sensor_condition')=='two_mounted_cameras' and
               result.get('trials',0)>=20 and result.get('success_rate',0)>=.70 and
               result.get('invalid_physics',1)==0 and result.get('weights_updated') is False)
        self.streak=self.streak+1 if valid else 0
        if self.streak>=2 and self.stage<2:self.stage+=1;self.streak=0;return True
        return False

class MotionDiscovery:
    """Small once-per-new-cell bonus. Repeated waving cannot earn it indefinitely.

    Simulator truth is allowed only to calculate reward; it is NOT policy input.
    25 new cells maximum per attempt, at most +0.5 total, fading by episode 500.
    A failure, table guard, camera-only change or a held command gets no bonus.
    """
    def reset(self,position,joints,episode):
        self.episode=int(episode);self.last=np.asarray(position,float).copy()
        self.seen={self.key(position,joints)};self.total=0.;self.new_cells=0
    @staticmethod
    def key(position,joints):
        xyz=tuple(np.floor(np.asarray(position)/12).astype(int))
        # Roll and aperture are separate actions, not fictitious extra motors.
        q=np.asarray(joints,float);roll=int(((q[3]+180)%360)//30);opening=int(np.clip(q[4],0,1)*8)
        return xyz+(roll,opening)
    def reward(self,position,joints,previous_joints,invalid=False):
        if invalid:return 0.
        q=np.asarray(joints,float);old=np.asarray(previous_joints,float)
        moved=(np.linalg.norm(np.asarray(position)-self.last)>1.0 or
               abs((q[3]-old[3]+180)%360-180)>1.0 or abs(q[4]-old[4])>.015)
        self.last=np.asarray(position,float).copy();key=self.key(position,q)
        if not moved or key in self.seen or self.new_cells>=25:return 0.
        self.seen.add(key);self.new_cells+=1
        value=.020*max(0.,1.-self.episode/500.)
        self.total+=value
        return value
