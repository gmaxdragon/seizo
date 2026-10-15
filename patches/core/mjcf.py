"""Documented and explicitly provisional MuJoCo rigid-body model of Seizo.

All units are SI. The model contains ACTUAL movable constrained bodies, motor
position targets with force limits, three free rigid objects, contact/friction,
and gravity. It does NOT claim that STL meshes encode dynamic joints. The STL
assembly is a visual reference only until hinges and masses are measured.

Keep SEIZO_PHYSICAL_MOTION disabled: no Pi, serial, GPIO, or motor imports.
"""
from __future__ import annotations
from xml.etree import ElementTree as ET

MODEL_VERSION='seizo-two-servo-parallel-contact-v5'
DT=0.001
SUBSTEPS=60
JOINT_NAMES=('base_yaw','shoulder_pitch','elbow_relative','wrist_yaw','left_finger','right_finger','left_parallel','right_parallel','wrist_level')
ACTUATOR_NAMES=('motor_base','motor_shoulder','motor_elbow','motor_wrist','motor_gripper')
OBJECT_NAMES=('red_cube','green_cylinder','blue_ball')
OBJECT_GEOMS=('object_red','object_green','object_blue')
FINGER_GEOMS=('left_jaw_contact','right_jaw_contact')
FLOOR_M=.065


# Preserve the unchanged v4 arm-body template; replace its tool mechanism below.
from ._arm_template import xml_model as _legacy_xml


def xml_model():
    """Make linked jaws from the actual displayed mesh; keep only FIVE actuators.

    Internal follower joints are constrained mechanical links, not extra servos.
    The shaft axis is retained from the existing model and remains uncalibrated.
    """
    from .gripper_geometry import SPEC, MAX_ANGLE
    root=ET.fromstring(_legacy_xml())
    root.find('option').set('timestep', str(DT))
    root.find('option').set('iterations','120')
    forearm=root.find(".//body[@name='forearm']")
    wrist=forearm.find("body[@name='wrist_and_palm']")
    forearm.remove(wrist)
    level=ET.SubElement(forearm,'body',name='wrist_mount',pos='0.220 0 0')
    ET.SubElement(level,'joint',name='wrist_level',type='hinge',axis='0 -1 0',range='-2.9 2.9',damping='0.03',armature='0.00005')
    ET.SubElement(level,'inertial',pos='0 0 0',mass='0.025',diaginertia='0.000006 0.000006 0.000006')
    wrist.set('pos','0 0 0');level.append(wrist)
    joint=wrist.find("joint[@name='wrist_yaw']")
    joint.set('axis',' '.join(str(v) for v in SPEC['wrist_axis']))
    joint.set('pos',' '.join(str(v*.001) for v in SPEC['wrist_pivot']))
    wrist.find("site[@name='tool_tip']").set('pos','0.173 0 0.001')
    # The hand is hollow. Convex pieces partition its contour, not its whole hull.
    asset=ET.SubElement(root,'asset')
    contact=root.find('contact');contact.clear()
    # Intended shared-joint intersection only. Never exclude the opposing jaws.
    ET.SubElement(contact,'exclude',body1='forearm',body2='wrist_and_palm')
    root.find(".//geom[@name='fixed_rear_support']").set('pos','-.028 0 .040')
    eq=root.find('equality');eq.clear()
    tendon=root.find('tendon');tendon.clear()
    fixed=ET.SubElement(tendon,'fixed',name='passive_wrist_level')
    for name in ('shoulder_pitch','elbow_relative','wrist_level'):
        ET.SubElement(fixed,'joint',joint=name,coef='1')
    ET.SubElement(eq,'tendon',name='parallel_wrist_support',tendon1='passive_wrist_level',polycoef='0 0 0 0 0',solref='0.003 1',solimp='0.995 0.999 0.0001')
    gripper_tendon=ET.SubElement(tendon,'fixed',name='single_gripper_servo_tendon')
    for label,side in (('left',1),('right',-1)):
        old=wrist.find("body[@name='%s_jaw']"%label);wrist.remove(old)
        a,b,_=SPEC['root'];x,y,_=SPEC['link']
        driver=ET.SubElement(wrist,'body',name=label+'_drive',pos=f'{a*.001} {side*b*.001} 0')
        ET.SubElement(driver,'joint',name=label+'_finger',type='hinge',axis=f'0 0 {side}',range=f'0 {MAX_ANGLE}',damping='0.008',armature='0.000015',frictionloss='0.001',solreflimit='0.003 1',solimplimit='0.995 0.999 0.0001')
        ET.SubElement(driver,'geom',name=label+'_drive_link',type='capsule',fromto=f'0 0 0 {x*.001} {side*y*.001} 0',size='.0024',mass='.006',contype='0',conaffinity='0')
        jaw=ET.SubElement(driver,'body',name=label+'_jaw',pos=f'{x*.001} {side*y*.001} {SPEC["jaw_z"]*.001}')
        ET.SubElement(jaw,'joint',name=label+'_parallel',type='hinge',axis=f'0 0 {side}',range=f'{-MAX_ANGLE} 0',damping='0.004',armature='0.00001',frictionloss='0.001')
        ET.SubElement(jaw,'inertial',pos=f'.035 {-side*.016} .003',mass='.018',diaginertia='.000004 .000011 .000014')
        for k,poly in enumerate(SPEC['convex_pieces']):
            verts=[(px*.001,side*py*.001,z) for z in (0.,SPEC['jaw_thickness']*.001) for px,py in poly]
            name=f'{label}_jaw_piece_{k}'
            ET.SubElement(asset,'mesh',name=name,vertex=' '.join(f'{v:.8g}' for p in verts for v in p))
            ET.SubElement(jaw,'geom',name=name,type='mesh',mesh=name,mass='0',friction='1.0 .008 .001',solref='.004 1',solimp='.98 .995 .0002')
        px,py,pz=SPEC['pad_center'];size=SPEC['pad_halfsize']
        ET.SubElement(jaw,'geom',name=label+'_jaw_contact',type='box',pos=f'{px*.001} {side*py*.001} {pz*.001}',size=' '.join(str(v*.001) for v in size),mass='.001',friction='1.25 .01 .001',solref='.009 1',solimp='.92 .98 .00035',rgba='.98 .37 .085 1')
        ET.SubElement(eq,'joint',name=label+'_parallel_constraint',joint1=label+'_parallel',joint2=label+'_finger',polycoef='0 -1 0 0 0',solref='.003 1',solimp='.995 .999 .0001')
        ET.SubElement(gripper_tendon,'joint',joint=label+'_finger',coef='.5')
    ET.SubElement(eq,'joint',name='mirrored_gripper_jaws',joint1='left_finger',joint2='right_finger',polycoef='0 1 0 0 0',solref='.003 1',solimp='.995 .999 .0001')
    actuator=root.find("actuator/position[@name='motor_gripper']")
    actuator.set('ctrlrange',f'0 {MAX_ANGLE}');actuator.set('kp','0.8');actuator.set('kv','.014');actuator.set('forcerange','-.06 .06')
    # No exclusion between the two opposing jaws. The solver must resist contact.
    return ET.tostring(root,encoding='unicode')


def validate_structure():
    root=ET.fromstring(xml_model())
    names=[x.get('name') for x in root.findall('.//worldbody//joint') if x.get('name')]
    acts=[x.get('name') for x in root.findall('.//actuator/position')]
    assert set(JOINT_NAMES)==set(names)
    assert tuple(acts)==ACTUATOR_NAMES
    assert len(root.findall('.//equality/joint'))==3
    assert not any({x.get('body1'),x.get('body2')}=={'left_jaw','right_jaw'} for x in root.findall('.//contact/exclude'))
    assert len(root.findall('.//freejoint'))==3
    return dict(joints=len(names),actuators=len(acts),free_objects=3,geometries=len(root.findall('.//geom')))
