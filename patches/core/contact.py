"""Seizo analytical collision proxy geometry and dynamic-sphere contact solver.

All coordinates use the application's *estimated* millimetre-like scene units.
This is not an STL-derived rigid-body simulator or a safety-rated digital twin.
The source STL is a merged assembly, without joint frames or inertias. We track
visually corresponding rails, transverse ribs, palm, base and finger proxies.
Only virtual, local NumPy arrays. This module has no robot I/O.
"""
from __future__ import annotations
import numpy as np

LINK_RADIUS=8.0
FINGER_RADIUS=4.5
PENETRATION_SLOP=0.02


def _points(a, x, y, z):
    """Transform wrist-local x,y,z into world using base yaw + wrist twist."""
    ang=(a[:,0]+a[:,3])*(np.pi/180.)
    c=np.cos(ang);s=np.sin(ang)
    return np.stack([x*c-y*s,x*s+y*c,z],axis=-1)


def colliders(q, fk_fn, dims, floor=65.):
    """Return (start,end,radius,names), one capsule per visible rigid feature.

    Descriptions are deliberately approximate, and remain stable for every task.
    Rigid-back structure is fixed with the yaw deck; not an extra controlled axis.
    """
    q=np.atleast_2d(np.asarray(q,dtype=float))
    n=len(q)
    tcp,wrist,elbow=fk_fn(q)
    yaw=q[:,0]*(np.pi/180.)
    u=np.stack([np.cos(yaw),np.sin(yaw),np.zeros(n)],axis=1)
    v=np.stack([-np.sin(yaw),np.cos(yaw),np.zeros(n)],axis=1)
    origin=np.zeros_like(wrist);origin[:,2]=float(dims['shoulder_height'])
    starts=[]; ends=[];radii=[];names=[]
    def add(name,p0,p1,radius):
        starts.append(p0);ends.append(p1);radii.append(radius);names.append(name)
    for side in (-1,1):
        # Two long rails on each link match the visually hollow/parallel assembly.
        add(f'upper_rail_{side}',origin+side*26*v,elbow+side*26*v,LINK_RADIUS)
        add(f'forearm_rail_{side}',elbow+side*27*v,wrist+side*27*v,LINK_RADIUS)
    for fraction,rib_radius in ((0.0,9.),(108./220.,9.),(218./220.,8.)):
        p=elbow+(wrist-elbow)*fraction
        add(f'forearm_cross_rib_{round(fraction*220)}',p-17*v,p+17*v,rib_radius)
    # Shoulder mount and exposed motor covers are rigid, obstructing objects.
    motor=np.zeros((n,3));motor[:,2]=122.
    add('shoulder_motor_a',motor-48*v,motor-48*v+np.array([0.,0.,10.]),20.)
    add('shoulder_motor_b',motor+48*v,motor+48*v+np.array([0.,0.,10.]),20.)
    saddle=np.zeros((n,3));saddle[:,2]=95.
    add('base_tower',saddle,origin,31.)
    # Wrist palm and finger proxies rotate with the wrist actuator.
    def wp(x,y=0.,z=0.):
        return wrist+_points(q,np.full(n,float(x)),np.full(n,float(y)),np.full(n,float(z)))
    add('wrist_camera_housing',wp(3,0,24),wp(39,0,24),12.)
    add('wrist_palm',wp(46,0,0),wp(66,0,0),17.)
    gap=6.+50.*np.clip(q[:,4],0,1)
    for sign in (-1,1):
        y=sign*gap/2
        add(f'jaw_{sign}',wp(103,0,0)+_points(q,np.zeros(n),y,np.zeros(n)),wp(173,0,0)+_points(q,np.zeros(n),y,np.zeros(n)),FINGER_RADIUS)
        # Link bars leading to movable gripper jaws.
        add(f'gripper_link_{sign}',wp(61,sign*10,0),wp(101,0,0)+_points(q,np.zeros(n),y,np.zeros(n)),4.)
    return np.stack(starts,axis=1),np.stack(ends,axis=1),np.asarray(radii,dtype=float),tuple(names)


def solve_capsule_contacts(positions, velocities, starts, ends, radii, obj_radius,
                           previous_starts=None, previous_ends=None, previous_positions=None,
                           dt=.012, iterations=2,
                           exclude=None):
    """Project dynamic object spheres out of moving static/kinematic capsules.

    Positions/velocities: [env,objects,xyz]. Colliders: [env,capsules,xyz].
    Object/capsule normals remove incoming velocity, including link movement;
    remaining sliding is not friction-calibrated.

    exclude is optional boolean [env, objects, capsules], e.g. a verified pinch
    may support contact at a finger instead of being projected out of its grip.
    """
    n,obj,_=positions.shape; k=starts.shape[1]
    r=np.asarray(obj_radius,dtype=float)
    impacts=np.zeros((n,obj),dtype=bool)
    last_depth=np.zeros((n,obj),dtype=float)
    seg=ends-starts
    len2=np.maximum(np.sum(seg*seg,axis=2),1e-8)
    pa=starts[:,None,:,:]; se=seg[:,None,:,:]
    min_sep=r[:,:,None]+radii[None,None,:]
    for _ in range(iterations):
        delta=positions[:,:,None,:]-pa
        t=np.clip(np.sum(delta*se,axis=3)/len2[:,None,:],0.,1.)
        closest=pa+t[:,:,:,None]*se
        dvec=positions[:,:,None,:]-closest
        dist=np.linalg.norm(dvec,axis=3)
        depth=min_sep-dist
        if exclude is not None:depth=np.where(exclude,-1.,depth)
        strongest=np.argmax(depth,axis=2)
        max_depth=np.take_along_axis(depth,strongest[:,:,None],axis=2)[:,:,0]
        active=max_depth>0.
        if not active.any():break
        row=np.arange(n)[:,None];col=np.arange(obj)[None,:]
        selected_dvec=dvec[row,col,strongest]
        length=dist[row,col,strongest]
        # Degenerate exactly-on-rail center: choose a stable escape direction.
        fallback=np.zeros_like(selected_dvec);fallback[...,2]=1.
        normal=np.where((length>1e-8)[:,:,None],selected_dvec/np.maximum(length[:,:,None],1e-8),fallback)
        if previous_positions is not None:
            # Continuous-side check: never project a falling object through a
            # thin rail merely because its center crossed the rail midpoint.
            previous_segment_a=(previous_starts if previous_starts is not None else starts)[row,strongest]
            previous_segment_b=(previous_ends if previous_ends is not None else ends)[row,strongest]
            seg_prev=previous_segment_b-previous_segment_a
            rel_prev=previous_positions-previous_segment_a
            param_prev=np.clip(np.sum(rel_prev*seg_prev,axis=2)/np.maximum(1e-9,np.sum(seg_prev*seg_prev,axis=2)),0,1)
            old_closest=previous_segment_a+param_prev[:,:,None]*seg_prev
            from_previous=previous_positions-old_closest
            previous_distance=np.linalg.norm(from_previous,axis=2)
            old_normal=from_previous/np.maximum(1e-8,previous_distance[:,:,None])
            change_side=(np.sum(from_previous*normal,axis=2)<0.) & (previous_distance>1e-5)
            normal=np.where(change_side[:,:,None],old_normal,normal)
        positions+=np.where(active[:,:,None],normal*(max_depth[:,:,None]+PENETRATION_SLOP),0.)
        relative=velocities.copy()
        if previous_starts is not None and previous_ends is not None:
            param=t[row,col,strongest]
            previous=previous_starts[row,strongest]*(1.-param[:,:,None])+previous_ends[row,strongest]*param[:,:,None]
            current=closest[row,col,strongest]
            relative-=np.where(active[:,:,None],(current-previous)/max(dt,1e-5),0.)
        vn=np.sum(relative*normal,axis=2)
        velocities+=np.where(active[:,:,None]& (vn<0.)[:,:,None], -vn[:,:,None]*normal,0.)
        impacts|=active
        last_depth=np.maximum(last_depth,np.where(active,max_depth,0.))
    return impacts,last_depth
