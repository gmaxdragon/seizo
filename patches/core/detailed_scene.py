"""Render the shipped detailed arm meshes, without changing collision/actuator physics.

The source asset is built from model.js + gripper_rig.js, not a generated picture.
Visual-only mocap frames follow the same linkage transforms used by the human
viewport. The tool follows actual MuJoCo body transforms, not commanded angles.
Textures are procedural materials, not a reconstruction of the user's room.
"""
from __future__ import annotations
import functools, json, math, gzip
from pathlib import Path
from collections import defaultdict
from xml.etree import ElementTree as ET
import numpy as np
import mujoco

ASSETS=Path(__file__).resolve().parents[1]/'web/assets'

@functools.lru_cache(maxsize=1)
def source():
    spec=json.loads((ASSETS/'camera_parts.json').read_text())
    meshes=json.loads(gzip.decompress((ASSETS/'camera_lod.json.gz').read_bytes()))
    return spec,meshes

def t(x=0.,y=0.,z=0.):
    a=np.eye(4);a[:3,3]=[x,y,z];return a

def rot(axis,angle):
    a=np.eye(4);c,s=math.cos(angle),math.sin(angle)
    if axis==0:a[1:3,1:3]=[[c,-s],[s,c]]
    elif axis==1:a[np.ix_([0,2],[0,2])]=[[c,s],[-s,c]]
    else:a[:2,:2]=[[c,-s],[s,c]]
    return a

def pnt(a,p):return a[:3,:3]@p+a[:3,3]

def body_matrix(model,data,name):
    b=model.body(name).id;a=np.eye(4);a[:3,:3]=data.xmat[b].reshape(3,3);a[:3,3]=data.xpos[b]*1000;return a

@functools.lru_cache(maxsize=1)
def fragments():
    """Merge static local meshes by rigid group/material, retaining hollow surfaces."""
    spec,meshes=source();buckets=defaultdict(list)
    for part in spec['parts']:
        # The white marker paper is behind the camera. It is a visual estimate.
        key=(part['group'],tuple(part['color']),float(part.get('rough',.5)),float(part.get('metal',0)))
        shape=meshes[part['geometry']];a=np.array(part['local']).reshape(4,4).T
        localpoints=np.array(shape['p'],float).reshape(-1,3)
        if part.get('dynamic')=='bar':localpoints[:,0]*=math.hypot(46,31)/60.
        points=localpoints@a[:3,:3].T+a[:3,3]
        normals=np.array(shape['n'],float).reshape(-1,3)@np.linalg.inv(a[:3,:3])
        normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
        # Mirrored jaw triangle winding must agree with transformed normals.
        if np.linalg.det(a[:3,:3])<0:
            points=points.reshape(-1,3,3)[:,[0,2,1]].reshape(-1,3)
            normals=normals.reshape(-1,3,3)[:,[0,2,1]].reshape(-1,3)
        buckets[key].append((points*.001,normals))
    asset=ET.Element('asset');wb=ET.Element('worldbody');bodies={}
    for index,((group,color,rough,metal),values) in enumerate(buckets.items()):
        if group not in bodies:bodies[group]=ET.SubElement(wb,'body',name='visual_'+group,mocap='true',pos='0 0 0')
        points=np.concatenate([p for p,_ in values]);normals=np.concatenate([n for _,n in values])
        name='detail_'+str(index)
        # OBJ supports separate normals and is supplied as in-memory asset bytes.
        # XML explicit vertices include normals and one index per triangle vertex.
        ET.SubElement(asset,'mesh',name=name,vertex=' '.join(f'{v:.7g}' for v in points.ravel()),
            normal=' '.join(f'{v:.6g}' for v in normals.ravel()),
            face=' '.join(str(v) for v in range(len(points))),inertia='shell',maxhullvert='32')
        material=name+'_mat'
        ET.SubElement(asset,'material',name=material,rgba=' '.join(str(x) for x in (*color,1)),
            specular=str(.12+.45*metal),shininess=str(max(.05,1-rough)))
        ET.SubElement(bodies[group],'geom',name=name,type='mesh',mesh=name,material=material,
            contype='0',conaffinity='0',mass='0',group='3')
    return ET.tostring(asset,encoding='unicode'),ET.tostring(wb,encoding='unicode')

def add_details(root):
    asset=root.find('asset')
    if asset is None:asset=ET.SubElement(root,'asset')
    a,w=fragments();asset.extend(ET.fromstring(a));root.find('worldbody').extend(ET.fromstring(w))
    root.find('compiler').set('inertiagrouprange','0 2')
    # Hide approximate robot collision bodies, never disable their collisions.
    for body in root.find('worldbody').iter('body'):
        if body.get('name','').startswith(('visual_','requested_')):continue
        if body.get('name') in ('red_cube','green_cylinder','blue_ball'):continue
        for geom in body.findall('geom'):geom.set('group','1')
    root.find(".//geom[@name='desk']").set('group','1')
    # The familiar brown boards and navy mat are procedural surface materials.
    for name,filename in [('wood','room_wood.png'),('fabric','room_fabric.png')]:
        ET.SubElement(asset,'texture',name=name,type='2d',file=str(ASSETS/filename))
        ET.SubElement(asset,'material',name=name,texture=name,texrepeat='4 4',texuniform='true',specular='.08',shininess='.1')
    ET.SubElement(asset,'texture',name='room_background',type='skybox',builtin='gradient',rgb1='.62 .62 .59',rgb2='.30 .31 .30',width='256',height='1536')
    wb=root.find('worldbody')
    ET.SubElement(wb,'light',name='soft_fill',pos='.1 .4 1.4',dir='0 0 -1',diffuse='.35 .35 .35',ambient='.18 .18 .18',castshadow='false')
    ET.SubElement(wb,'geom',name='visual_room_floor',type='plane',pos='0 0 -.010',size='2 2 .01',
        material='wood',group='3',contype='0',conaffinity='0')
    ET.SubElement(wb,'geom',name='visual_navy_mat',type='box',pos='-.11 .05 -.006',size='.25 .30 .004',
        material='fabric',group='3',contype='0',conaffinity='0')
    ET.SubElement(wb,'geom',name='visual_work_surface',type='box',pos='.390 0 .0325',size='.25 .27 .0325',
        material='wood',group='3',contype='0',conaffinity='0')
    # No extra physical wall or camera tower is introduced.
    return root

def update_details(world,i):
    m=world.model;d=world.data[i];q=world.q[i];base=rot(2,q[0]*math.pi/180)
    a,b=q[1]*math.pi/180,q[2]*math.pi/180
    e=[145*math.cos(a),0,135+145*math.sin(a)]
    dz=float(world.floor_heights[i]-65)
    g={'base':np.eye(4),'yaw':base,
       'jointGearA':base@t(0,-40,135)@rot(1,-a),'jointGearB':base@t(0,40,135)@rot(1,-b),
       'pinionA':base@t(26,-41,111)@rot(1,a*3),'pinionB':base@t(26,41,111)@rot(1,b*3),
       'upper':base@t(0,0,135)@rot(1,-a),'upperTie':base@t(0,0,162)@rot(1,-a),
       'shoulderLevel':base@t(0,0,135),'elbowLevel':base@t(*e),
       'forearm':base@t(*e)@rot(1,-b),'forearmTie':base@t(e[0],0,e[2]+30)@rot(1,-b)}
    for value in g.values():value[2,3]+=dz
    for name,body in [('wristMount','wrist_mount'),('wrist','wrist_and_palm'),('jawLeft','left_jaw'),('jawRight','right_jaw')]:
        g[name]=body_matrix(m,d,body)
    spec,_=source()
    for part in spec['parts']:
        if part.get('dynamic')=='bar':
            side=part['side'];primary=part['primary']
            A=pnt(g['wrist'],[53,side*12,0] if primary else [64,side*3,0])
            B=pnt(g['jawLeft' if side>0 else 'jawRight'],[0,0,2] if primary else [11,-side*9,2])
            u=B-A;length=np.linalg.norm(u);u/=max(length,1e-9)
            # Parallel linkage has a fixed length. Small solver compliance is retained.
            v=np.cross(g['wrist'][:3,2],u);v/=max(np.linalg.norm(v),1e-9);n=np.cross(u,v)
            value=np.eye(4);value[:3,:3]=np.column_stack([u,v,n]);value[:3,3]=(A+B)/2
            g[part['group']]=value
        elif part.get('dynamic')=='gear':
            angle=float(d.qpos[m.joint('left_finger' if part['side']>0 else 'right_finger').qposadr[0]])
            side=part['side'];g[part['group']]=g['wrist']@t(53,side*11,0)@rot(2,side*angle)@t(-53,-side*11,0)
    if not hasattr(world,'_detail_ids'):
        world._detail_ids={name:int(m.body_mocapid[m.body('visual_'+name).id]) for name in g}
    quat=np.empty(4)
    for name,value in g.items():
        mid=world._detail_ids[name];d.mocap_pos[mid]=value[:3,3]*.001
        mujoco.mju_mat2Quat(quat,np.ascontiguousarray(value[:3,:3]).ravel());d.mocap_quat[mid]=quat
    m.geom_pos[m.geom('visual_work_surface').id,2]=world.floor_heights[i]/2000.
    m.geom_size[m.geom('visual_work_surface').id,2]=world.floor_heights[i]/2000.
