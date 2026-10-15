"""V9 observation boundary. Four RGB slots, optional helper slots explicitly masked.

No poses, contact flags, depth or exact geometry enter either neural network.
Missing helpers are zero in both current and previous images, not stale memories.
"""
import numpy as np
from .camera_observation import png
WIDTH,HEIGHT=384,288
POOL_W,POOL_H=48,36
NAMES=('overhead','wrist','side','front')
IMAGE_VALUES=4*2*POOL_W*POOL_H*3
OBS_SIZE=IMAGE_VALUES+7+3+3+5+8
POLICY_ID='seizo-detailed-view-curriculum-v9'
CONTRACT={'policy_id':POLICY_ID,'camera_names':list(NAMES),'images':[HEIGHT,WIDTH,3],
 'pooled_images':[POOL_H,POOL_W,3],'history_frames':2,
 'actor_inputs':['current/previous RGB','known task/object instruction','requested roll/opening',
                 'previous requested action','view availability/age'],
 'forbidden_inputs':['true joint/object pose','depth','segmentation','contact flags','exact target coordinates','camera extrinsics'],
 'test_condition':'wrist and overhead only; helper slots masked',
 'preprocessing':'fixed image pooling; no pretrained vision weights',
 'simulation_only':True,'physical_validation':False}

def encode(current,previous,task,target_class,desired_roll,desired_opening,last_action,available,ages):
    current=np.asarray(current);previous=np.asarray(previous)
    expected=(4,HEIGHT,WIDTH,3)
    if current.shape!=expected or previous.shape!=expected or current.dtype!=np.uint8 or previous.dtype!=np.uint8:
        raise ValueError('Four named RGB slots are required')
    available=np.asarray(available,bool);ages=np.asarray(ages,float);act=np.asarray(last_action,float)
    if available.shape!=(4,) or ages.shape!=(4,) or act.shape!=(5,) or not np.isfinite(act).all():
        raise ValueError('Invalid view metadata or previous command')
    if not 0<=int(task)<7 or not 0<=int(target_class)<3:raise ValueError('Unknown instruction')
    def pool(x):
        y=x.reshape(4,POOL_H,HEIGHT//POOL_H,POOL_W,WIDTH//POOL_W,3).mean(axis=(2,4))/127.5-1.
        y[~available]=0
        return y.ravel()
    a=float(desired_roll)*np.pi/180
    instruction=np.r_[np.eye(7)[int(task)],np.eye(3)[int(target_class)],
                      np.sin(a),np.cos(a),float(desired_opening),np.clip(act,-1,1),
                      available.astype(float),np.clip(ages/5.,0,1)]
    out=np.r_[pool(current),pool(previous),instruction].astype(np.float32)
    if out.shape!=(OBS_SIZE,) or not np.isfinite(out).all():raise ValueError('Invalid camera-only input')
    return out
