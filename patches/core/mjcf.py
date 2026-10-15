"""Documented and explicitly provisional MuJoCo rigid-body model of Seizo.

All units are SI. The model contains ACTUAL movable constrained bodies, motor
position targets with force limits, three free rigid objects, contact/friction,
and gravity. It does NOT claim that STL meshes encode dynamic joints. The STL
assembly is a visual reference only until hinges and masses are measured.

Keep SEIZO_PHYSICAL_MOTION disabled: no Pi, serial, GPIO, or motor imports.
"""
from __future__ import annotations
from xml.etree import ElementTree as ET

MODEL_VERSION='seizo-five-control-mujoco-rigid-v4'
DT=0.002
SUBSTEPS=30
JOINT_NAMES=('base_yaw','shoulder_pitch','elbow_relative','wrist_yaw','left_finger','right_finger')
ACTUATOR_NAMES=('motor_base','motor_shoulder','motor_elbow','motor_wrist','motor_left_jaw','motor_right_jaw')
OBJECT_NAMES=('red_cube','green_cylinder','blue_ball')
OBJECT_GEOMS=('object_red','object_green','object_blue')
FINGER_GEOMS=('left_jaw_contact','right_jaw_contact')
FLOOR_M=.065


def xml_model():
    """Build MuJoCo XML. Primarily convex geometric approximations, never STL hulls."""
    return '''<mujoco model="Seizo MK2 Plus provisional dynamics">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.002" gravity="0 0 -9.81" integrator="implicitfast" solver="Newton" iterations="90" cone="elliptic">
    <flag nativeccd="enable"/>
  </option>
  <default>
    <joint damping="0.10" armature="0.0002" frictionloss="0.012"/>
    <geom solref="0.008 1" solimp="0.93 0.97 0.001" friction="0.95 0.006 0.0005" condim="4"/>
  </default>
  <worldbody>
    <geom name="desk" type="plane" pos="0 0 0.065" size="2 2 0.01" rgba="0.69 0.75 0.79 1" friction="0.9 0.02 0.001"/>
    <body name="base_foot" pos="0 0 0">
      <geom type="cylinder" name="stationary_base" pos="0 0 0.028" size="0.074 0.025" rgba="0.5 0.3 0.8 1"/>
      <body name="turntable" pos="0 0 0.065">
        <joint name="base_yaw" axis="0 0 1" type="hinge" range="-1.0472 1.0472" damping="0.16" armature="0.001"/>
        <geom name="yaw_deck" type="cylinder" pos="0 0 0.008" size="0.058 0.008" density="1100"/>
        <geom name="fixed_rear_support" type="box" pos="-0.028 0 0.030" size="0.020 0.033 0.035" density="900"/>
        <body name="upper_arm" pos="0 0 0.070">
          <joint name="shoulder_pitch" type="hinge" axis="0 -1 0" range="0.436332 1.658063" damping="0.32" armature="0.004"/>
          <geom name="upper_left_rail" type="capsule" fromto="0 -0.026 0 0.145 -0.026 0" size="0.009" density="950"/>
          <geom name="upper_right_rail" type="capsule" fromto="0 0.026 0 0.145 0.026 0" size="0.009" density="950"/>
          <geom name="upper_crossbar" type="capsule" fromto="0.142 -0.027 0 0.142 0.027 0" size="0.009" density="950"/>
          <body name="forearm" pos="0.145 0 0">
            <joint name="elbow_relative" type="hinge" axis="0 -1 0" range="-2.792527 -0.174533" damping="0.25" armature="0.002"/>
            <geom name="forearm_left_rail" type="capsule" fromto="0 -0.027 0 0.220 -0.027 0" size="0.008" density="950"/>
            <geom name="forearm_right_rail" type="capsule" fromto="0 0.027 0 0.220 0.027 0" size="0.008" density="950"/>
            <geom name="forearm_crossbar_start" type="capsule" fromto="0 -0.03 0 0 0.03 0" size="0.009" density="950"/>
            <geom name="forearm_crossbar_mid" type="capsule" fromto="0.108 -0.03 0 0.108 0.03 0" size="0.009" density="950"/>
            <geom name="forearm_crossbar_end" type="capsule" fromto="0.218 -0.03 0 0.218 0.03 0" size="0.008" density="950"/>
            <body name="wrist_and_palm" pos="0.220 0 0">
              <joint name="wrist_yaw" type="hinge" axis="0 0 1" range="-1.308997 1.308997" damping="0.04" armature="0.00015"/>
              <geom name="wrist_housing" type="box" pos="0.020 0 0.012" size="0.023 0.026 0.018" density="950"/>
              <geom name="palm" type="box" pos="0.063 0 0" size="0.024 0.021 0.010" density="950"/>
              <site name="tool_tip" pos="0.173 0 0" size="0.004" rgba="1 0 0 1"/>
              <body name="left_jaw" pos="0.103 0.003 0">
                <joint name="left_finger" type="slide" axis="0 1 0" range="0 0.025" damping="0.15" frictionloss="0.05"/>
                <geom name="left_jaw_contact" type="capsule" fromto="0 0 0 0.070 0 0" size="0.0045" density="950" friction="1.3 0.02 0.003"/>
              </body>
              <body name="right_jaw" pos="0.103 -0.003 0">
                <joint name="right_finger" type="slide" axis="0 -1 0" range="0 0.025" damping="0.15" frictionloss="0.05"/>
                <geom name="right_jaw_contact" type="capsule" fromto="0 0 0 0.070 0 0" size="0.0045" density="950" friction="1.3 0.02 0.003"/>
              </body>
            </body>
          </body>
        </body>
      </body>
    </body>
    <body name="red_cube" pos="0.38 -0.10 0.077">
      <freejoint name="free_red"/>
      <geom name="object_red" type="box" size="0.012 0.012 0.012" density="4000" rgba="0.9 0.2 0.2 1"/>
    </body>
    <body name="green_cylinder" pos="0.38 0 0.078">
      <freejoint name="free_green"/>
      <geom name="object_green" type="cylinder" size="0.012 0.013" density="2500" rgba="0.2 0.85 0.4 1"/>
    </body>
    <body name="blue_ball" pos="0.38 0.10 0.078">
      <freejoint name="free_blue"/>
      <geom name="object_blue" type="sphere" size="0.013" density="3000" rgba="0.2 0.35 0.9 1"/>
    </body>
  </worldbody>
  <contact>
    <exclude body1="left_jaw" body2="right_jaw"/>
  </contact>
  <actuator>
    <position name="motor_base" joint="base_yaw" kp="12" ctrllimited="true" ctrlrange="-1.0472 1.0472" forcelimited="true" forcerange="-1.6 1.6"/>
    <position name="motor_shoulder" joint="shoulder_pitch" kp="14" ctrllimited="true" ctrlrange="0.436332 1.658063" forcelimited="true" forcerange="-2.4 2.4"/>
    <position name="motor_elbow" joint="elbow_relative" kp="10" ctrllimited="true" ctrlrange="-2.792527 -0.174533" forcelimited="true" forcerange="-1.8 1.8"/>
    <position name="motor_wrist" joint="wrist_yaw" kp="3.5" ctrllimited="true" ctrlrange="-1.308997 1.308997" forcelimited="true" forcerange="-0.28 0.28"/>
    <position name="motor_left_jaw" joint="left_finger" kp="260" ctrllimited="true" ctrlrange="0 0.025" forcelimited="true" forcerange="-8 8"/>
    <position name="motor_right_jaw" joint="right_finger" kp="260" ctrllimited="true" ctrlrange="0 0.025" forcelimited="true" forcerange="-8 8"/>
  </actuator>
</mujoco>'''


def validate_structure():
    """Structure check works even where MuJoCo wheels cannot be downloaded."""
    root=ET.fromstring(xml_model())
    names=[x.get('name') for x in root.findall('.//joint') if x.get('name')]
    actuators=[x.get('name') for x in root.findall('.//actuator/position')]
    free=[x.get('name') for x in root.findall('.//freejoint')]
    geom={x.get('name') for x in root.findall('.//geom')}
    assert set(JOINT_NAMES)==set(names), (JOINT_NAMES,names)
    assert set(ACTUATOR_NAMES)==set(actuators)
    assert free==['free_red','free_green','free_blue']
    assert set(FINGER_GEOMS+OBJECT_GEOMS).issubset(geom)
    assert all(x.get('forcelimited')=='true' for x in root.findall('.//actuator/position'))
    return dict(joints=len(names),actuators=len(actuators),free_objects=len(free),geometries=len(root.findall('.//geom')))
