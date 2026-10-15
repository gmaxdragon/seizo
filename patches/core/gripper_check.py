"""Finite, local, physics-driven mechanism checks. Never a policy or hardware test."""
from __future__ import annotations
from xml.etree import ElementTree as ET
import numpy as np
import mujoco
from .mjcf import xml_model, SUBSTEPS
from .mujoco_world import MuJoCoWorld, RAD


def check_world(mode='open_close'):
    if mode not in ('open_close','wrist','contact'):raise ValueError('Unknown gripper check.')
    q=np.array([0.,65.,-25.,0.,1.])
    root=ET.fromstring(xml_model());eq=root.find('equality')
    # Only this diagnostic fixtures the three arm axes to isolate the two servos.
    for name,angle in zip(('base_yaw','shoulder_pitch','elbow_relative'),(q[0],q[1],q[2]-q[1])):
        ET.SubElement(eq,'joint',name='diagnostic_fix_'+name,joint1=name,polycoef=f'{angle*RAD} 0 0 0 0',solref='.002 1',solimp='.999 .9999 .0001')
    w=MuJoCoWorld(n=1,seed=21,task='orient',xml_text=ET.tostring(root,encoding='unicode'))
    w.q[0]=q;w.targetq[0]=q;d=w.data[0];m=w.model
    w._set_pose(d,q);d.qvel[:]=0;mujoco.mj_forward(m,d)
    if mode=='contact':
        # A fixed test block shows squeezing contact; not a claimed successful grasp.
        wrist=m.body('wrist_and_palm').id
        p=d.xpos[wrist]+d.xmat[wrist].reshape(3,3)@np.array([.169,0.,.001])
        root=ET.fromstring(ET.tostring(root,encoding='unicode'))
        block=root.find(".//body[@name='red_cube']");block.remove(block.find('freejoint'));block.set('pos',' '.join(str(v) for v in p))
        # Keep the freejoint indexing stable: use an equality weld instead of removing it.
        block.insert(0,ET.Element('freejoint',name='free_red'))
        ET.SubElement(root.find('equality'),'weld',name='diagnostic_block_fixture',body1='red_cube',solref='.002 1',solimp='.999 .9999 .0001')
        w=MuJoCoWorld(n=1,seed=21,task='orient',xml_text=ET.tostring(root,encoding='unicode'))
        d=w.data[0];m=w.model;w.q[0]=q;w.targetq[0]=q;w._set_pose(d,q)
        d.qpos[w.objadr[0]:w.objadr[0]+3]=p
    # Distractors remain in the simulation but out of the hand's test volume.
    for j in range(3):
        if mode=='contact' and j==0:continue
        d.qpos[w.objadr[j]:w.objadr[j]+3]=[.35,(j-1)*.12,.065+w.radius[0,j]*.001]
    d.qvel[:]=0;mujoco.mj_forward(m,d);w._copy_from_physics((0,))
    return w,q


def run_check(mode='open_close'):
    w,target=check_world(mode);d=w.data[0];m=w.model;frames=[]
    if mode=='wrist':
        sequence=[('Center',0.,1.,12),('Clockwise',35.,1.,36),('Counterclockwise',-35.,1.,60),('Center',0.,1.,36)]
    else:
        sequence=[('Open',0.,1.,15),('Close and squeeze' if mode=='contact' else 'Close',0.,0.,65),('Open',0.,1.,55)]
    pad_contact_peak=0.;after_contact_steps=0;seen=False
    for label,wrist,opening,steps in sequence:
        for _ in range(steps):
            target[3]+=np.clip(wrist-target[3],-1.5,1.5)
            target[4]+=np.clip(opening-target[4],-.025,.025)
            w.targetq[0]=target;w._command(d,target)
            for _ in range(SUBSTEPS):mujoco.mj_step(m,d)
            mujoco.mj_forward(m,d);w._copy_from_physics((0,));w.count[0]+=1
            force=0.;contact=False
            for c in d.contact[:d.ncon]:
                names={m.geom(int(c.geom1)).name,m.geom(int(c.geom2)).name}
                if 'object_red' in names and any(n and ('jaw_' in n) for n in names):
                    contact=True
            if contact:seen=True
            if seen and opening==0.:after_contact_steps+=1
            pad_contact_peak=max(pad_contact_peak,abs(float(d.actuator_force[w.aid['motor_gripper']])))
            f=w.frame();f['diagnostic']=True;f['diagnostic_phase']=label;f['task_label']='Gripper mechanism check (not AI learning)';f['arm_object_contact']=contact
            if mode=='contact':f['objects'][0]['name']='fixed test block (diagnostic only)'
            frames.append(f)
    return dict(frames=frames,mode=mode,diagnostic=True,diagnostic_message='Mechanical simulation check only. Arm axes fixed. No learning or physical commands.',
                weights_updated=False,physical_motion=False,success=False,fault=False,policy_updates=0,
                contact_seen=seen,continued_closing_steps_after_contact=after_contact_steps,
                peak_virtual_gripper_torque_nm=pad_contact_peak)
