# Seizo Same-Arm Architecture

## Core decision

Seizo keeps the current modified arm.

The arm itself is not the bottleneck. The two real constraints are:

1. the base must be rigidly stabilized against overturning;
2. the software must stop treating one-axis jogs as the product interaction model.

The current Uno + GRBL + Nano stack remains usable while those two problems are fixed.

## Mechanical direction

Do not replace the arm.

Keep:
- current approximately four-foot arm structure;
- current three NEMA17-driven GRBL axes;
- current gripper and wrist servos;
- current cameras;
- current Uno/CNC Shield and Nano during this optimization phase.

Improve:
- base mounting;
- stiffness at the stationary base interface;
- cable management if any cable creates motion drag;
- later, optional homing switches when unattended motion becomes necessary.

## Base stabilization

The target is not "add weight." The target is to create a rigid load path from the
stationary lower robot base into a large plate and then into the table/bench.

Preferred construction:

1. Capture the NON-ROTATING lower base with either:
   - existing mounting holes, if structurally suitable; or
   - a two-piece clamp/collar around the stationary base.
2. Bolt that interface to a stiff plate.
3. Clamp the plate to the table in at least two separated locations.
4. Ensure the rotating turret has full clearance.
5. Keep the physical kill switch accessible.

The printed collar is primarily an adapter/locator. The plate and table clamps
should carry the overturning moment.

Preferred plate options:
- 6-10 mm aluminum plate;
- steel plate if weight is acceptable;
- budget prototype: 18-24 mm plywood reinforced underneath with steel/aluminum
  flat bar or angle.

For a long arm, table clamping is substantially better than trying to make a
freestanding base heavy enough.

## Manual control model

Single-axis jog remains available for:
- diagnosis;
- direction checking;
- calibration;
- precise final nudging.

It is NOT the primary fast-driving model.

The same GRBL controller can execute coordinated G1 moves containing X, Y and Z
in one block. Seizo therefore supports coordinated manually triggered vectors.

Examples:
- Base + Reach together;
- Base + Reach + Z together;
- diagonal planar motion.

Each request remains:
- explicitly triggered by the operator;
- bounded to current per-axis manual step limits;
- one GRBL motion block;
- no hidden queued trajectory;
- no autonomous continuation.

## Speed model

The prior default profile remains NORMAL:
- X/Y feed: 90 GRBL mm/min;
- Z feed: 60 GRBL mm/min;
- low session acceleration remains 15 / 15 / 8 mm/s^2.

FAST manual mode raises feed while retaining low acceleration:
- XY-only coordinated/manual motion: up to 135 mm/min;
- Z-only: 90 mm/min;
- mixed XY+Z: 110 mm/min.

This deliberately attacks travel time without increasing the acceleration impulse
that contributes more directly to tipping and mechanical shock.

FAST remains operator-selected and is not evidence that the hardware is safe at a
higher acceleration.

## Skill-authoring direction

The faster authoring path on THIS arm is:

1. coordinated manual move;
2. capture meaningful relative pose/keyframe;
3. coordinated manual move;
4. capture another pose;
5. gripper event;
6. preview/review;
7. only later, replay after base stabilization and motion validation.

Do not make users encode a skill as dozens of individual motor taps.

## Future reference / homing

Homing switches are not required to improve manual control speed.

They become important before:
- unattended replay;
- absolute-position skill execution across power cycles;
- robust software travel envelopes.

Until then, keep automated sequences disabled and treat commanded position as
relative/session state, not measured physical truth.

## Software principles

- Same arm is the product hardware baseline.
- Single-axis = diagnostic/fine adjustment.
- Coordinated multi-axis = normal fast manual driving.
- User-triggered vector commands are allowed before automation.
- FAST feed may increase travel speed without changing acceleration.
- Physical base stabilization is the highest-value mechanical improvement.
- Do not replace working hardware merely to satisfy a software architecture.
- Add hardware only when a demonstrated requirement cannot be solved with the
  current system.
