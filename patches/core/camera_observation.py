"""Strict actor input boundary. Only RGB frames, frame status and known instructions.

This module cannot access MuJoCo data, poses, contacts, object coordinates,
depth, segmentation, rewards, or camera extrinsics. Average pooling is fixed
image preprocessing, NOT a pretrained visual encoder.
"""
from __future__ import annotations
import base64, struct, zlib
import numpy as np
WIDTH=128
HEIGHT=96
POOL_W=16
POOL_H=12
IMAGE_VALUES=2*2*POOL_W*POOL_H*3  # two cameras, current and previous images
OBS_SIZE=IMAGE_VALUES+7+3+3+5+4  # task, object class, requested roll/aperture, own action, camera age/validity
POLICY_ID='seizo-two-rgb-camera-policy-v8'
CONTRACT={
 'policy_id':POLICY_ID,'camera_names':['overhead','wrist'],'source':'simulated_rgb_only',
 'training_and_evaluation_same_input':True,'uses_real_cameras':False,
 'images':[HEIGHT,WIDTH,3],'pooled_images':[POOL_H,POOL_W,3],'history_frames':2,
 'actor_inputs':['current RGB','previous RGB','task instruction','target object class',
                 'requested roll and aperture','previous requested action','camera validity and age'],
 'forbidden_inputs':['true joint position','true object pose','depth','segmentation',
                     'contact flags','camera extrinsics','exact target coordinates'],
 'preprocessing':'fixed average pooling, not learned object detection',
 'simulation_only':True,'physical_validation':False
}

def png(rgb):
    rgb=np.ascontiguousarray(rgb,dtype=np.uint8)
    h,w,c=rgb.shape
    if c!=3:raise ValueError('RGB required')
    def chunk(tag,data):
        return struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data)&0xffffffff)
    raw=b''.join(b'\0'+row.tobytes() for row in rgb)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,3))+chunk(b'IEND',b'')

def encode(current,previous,task,target_class,desired_roll,desired_opening,last_action,available,ages):
    """Inputs are explicit and audited. No **kwargs or simulator object accepted."""
    try:
        current=np.asarray(current,dtype=np.uint8);previous=np.asarray(previous,dtype=np.uint8)
    except (TypeError,ValueError) as e:raise ValueError('Two RGB image arrays are required') from e
    if current.shape!=(2,HEIGHT,WIDTH,3) or previous.shape!=current.shape:
        raise ValueError('Exactly the overhead and wrist RGB frames are required')
    if not 0<=int(task)<7 or not 0<=int(target_class)<3:raise ValueError('Unknown instruction')
    def pool(x):
        return x.reshape(2,POOL_H,HEIGHT//POOL_H,POOL_W,WIDTH//POOL_W,3).mean(axis=(2,4)).reshape(-1)/127.5-1.
    action=np.asarray(last_action,float)
    if action.shape!=(5,) or not np.isfinite(action).all():raise ValueError('Invalid previous requested action')
    roll=float(desired_roll)*np.pi/180
    instruction=np.r_[np.eye(7)[int(task)],np.eye(3)[int(target_class)],
                      np.sin(roll),np.cos(roll),float(desired_opening),
                      np.clip(action,-1,1),np.asarray(available,float),np.minimum(np.asarray(ages,float)/5,1)]
    result=np.r_[pool(current),pool(previous),instruction].astype(np.float32)
    if result.shape!=(OBS_SIZE,) or not np.isfinite(result).all():raise ValueError('Invalid camera-only observation')
    return result
