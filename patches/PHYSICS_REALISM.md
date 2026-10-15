# Seizo two-servo gripper correction, v5

This is computer simulation only. No Raspberry Pi, serial/GPIO controller,
physical-motor command path, or Railway service was changed.

## What was wrong

The previous displayed jaw was already tapered toward its closed centerline,
but the renderer translated it inward again. The visible tips crossed. The old
physics model also explicitly excluded collisions between the opposing jaws.
Wrist leveling and visible tool coordinates could disagree with physics.

## Corrected mechanism

Five actuators total: three main arm controls, ONE wrist actuator rotating the
whole tool, and ONE gripper actuator driving a coupled pair of jaw linkages.
The additional linkage follower joints are passive constraints, not servos.
The jaws remain parallel, move on fixed-length links and do not translate past
their closed geometry. The displayed large gripper is retained. Its hollow
contour is decomposed into convex collision pieces so the holes are not filled
by a single convex hull. Opposing-jaw collisions are enabled. Frames contain
actual simulated wrist and jaw transforms, and the renderer uses those exact
transforms rather than a different interpolated mechanism.

A closing request continues after contact. Contact resists the motion with
bounded actuator force and soft pad constraints. This does not permit the jaws
to pass through an object. Objects are not teleported into a successful grasp.
The simulator advances at 1 ms integration steps, 60 per learning action.
Zero action retains its existing target instead of chasing gravity-induced sag.

## Check gripper

Use Open / close, Wrist turn, and Contact squeeze. These finite diagnostics fix
only the three main arm axes. Contact squeeze uses an explicitly labeled fixed
block to isolate the gripper. They are NOT learned grasp demonstrations.
STOP stops displayed playback. Separate automated tests also initialize a free
block between the jaws, hold it by contact, then release it under gravity.
This verifies a pre-positioned grasp, not autonomous object acquisition.

## Calibration limits

The main arm appearance remains the earlier reconstructed assembly. Its lengths,
linkage topology, wrist shaft direction and travel, masses, friction, gear ratios,
servo force limits and compliance remain unmeasured estimates. The existing
wrist shaft orientation is retained; it is not a calibrated hardware mapping.
The nominal empty visual tip gap is 6 estimated mm and maximum gripping torque
is 0.06 simulated Nm. Neither is a recommendation for the physical robot.
The rear support has no independent actuator. Complete full-link self-collision,
cable forces and physical-robot transfer are not validated.

The supplied STL files have not been converted into a complete measured dynamic
assembly in this update. No simulated success releases real-robot control.
Old policies are archived because they were trained on a different mechanism.
The previous API key storage is unchanged and no key is included in this release.
Training and mechanism checks now require MuJoCo; the HTTP layer blocks them
rather than silently using the old approximate contact engine when it is absent.
