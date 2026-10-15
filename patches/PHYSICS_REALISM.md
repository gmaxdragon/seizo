# Seizo realistic physics (v4, provisional)

The **PEAC** Railway website is a different project and is not modified by this work.
Seizo is local-only: no Railway compute, Raspberry Pi, GPIO, serial, or robot motor control.

## Two honest simulation backends

1. **MuJoCo** (preferred when installed): physically integrated *rigid bodies*,
   gravity, joint inertia, motor force limits, joint damping, friction, sliding
   gripper fingers driven by one coupled gripper servo, force-based contact; the red cube, green cylinder and
   blue ball have their correct primitive collision shapes. Physics advances
   at 2 ms internal substeps. An RL movement command spans 30 substeps.
2. **Approximate** (if MuJoCo installation fails or user chooses fast mode):
   existing capsule/sphere proxy environment. It is substantially faster but
   not equivalent to MuJoCo. The app displays which backend it uses.

The starter offers a one-time `mujoco` Python-wheel install. To request explicit
fallback launch with `SEIZO_PHYSICS_ENGINE=capsule`; to demand full physics
set `SEIZO_PHYSICS_ENGINE=mujoco`. `auto` uses full physics when available.

## Incomplete calibration (must not exaggerate)

- The uploaded **Mk2 Plus Addons (6).stl** is a merged triangle assembly, not a
  rigged MuJoCo URDF/MJCF: it does **not** contain joint frames, inertial tensors,
  material friction, stepper torque curves, or independent link objects.
- The **Mk2 Plus Addons (7).stl** consists of gripper jaw pieces, not the final
  modified gripper's servo gear train. The full custom gripper link is still needed.
- The 3D mesh shown on screen is the previous photo-based approximation. MuJoCo's
  rigid geoms are authoritative for contact, but true CAD-scale visual-vs-physics
  registration and calibration are not complete.
- The model's 0.145 m upper link, 0.220 m forearm, 0.135 m shoulder height,
  gripper geometry, mass estimates, torque limits and joint axes are **provisional**.
  Real wrist/gripper axes and gripping linkage have not been measured.
- Nominal properties such as plastic mass and friction are estimates. Real motors
  have gearing, backlash, torque-vs-speed and power limits not reproduced yet.
- Virtual learning performance must be **rebenchmarked** after an engine change.
  Old policies are archived as incompatible. Success in either model cannot
  authorize automated motion of a robot without limit switches or a kill switch.

## Suggested next calibration sequence

1. Obtain a CAD **assembly** with individually addressable solid links and jaw
   components, or take measured shoulder, elbow and wrist joint-axis coordinates.
2. Measure link lengths, tip offset, actual motor ratios and two servo ranges.
3. Measure total weight per moving link and gripper; adjust inertias and motor
   torque limits, rather than only visual mesh vertices.
4. Compare virtual vs hand-measured slow supervised poses on a powerless arm.
5. Only after accurate physics and contact validation, run held-out tasks and
   compare untrained vs trained policies before considering any hardware bridge.
