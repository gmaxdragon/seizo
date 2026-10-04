# ARCHIVED RESEARCH — Seizo V2 SCARA Concept

> Status: ARCHIVED / NOT THE ACTIVE BUILD.
>
> On Sep 27, 2026 the project decision returned to the existing modified Jackytle MK2 Plus. This file remains only as discarded architecture research and must not override Hardware.md or CONTROL_MAP.md.

## Historical concept

This concept explored a compact 3-axis SCARA arm built around the hardware already owned.

Main actuators:
- J1: NEMA17 base/shoulder yaw
- J2: NEMA17 elbow yaw
- Z: NEMA17 vertical rack axis
- gripper: existing small servo, treated as a separate tool subsystem

No fourth NEMA17 in V2.
No TB6600 requirement.
No timing belts.
No purchased lead screws.
No purchased linear rails.
No new structural hardware beyond reusing existing bearings and fasteners.

This statement is superseded. The existing modified MK2 Plus remains the active Seizo arm.

## Why SCARA

The old arm made Y/Z motors fight gravity through long printed links and exposed gear meshes.
The SCARA arrangement moves J1/J2 in the horizontal plane, so those motors mainly overcome inertia and friction rather than continuously holding the arm against gravity.

Only Z lifts the tool vertically.

This is a better match for Seizo's first task:
- overhead vision,
- pick from above,
- move across a tabletop,
- place from above.

## Printer constraint

Target printer: Anycubic Kobra S1 Max, 350 x 350 x 350 mm build volume.

All major printed pieces must fit individually inside 330 x 330 x 330 mm to keep margin from the nominal build envelope.

## Overall dimensions

V2 target geometry:
- base footprint: 220 x 220 mm
- base body height: about 75 mm
- first arm link center-to-center: 145 mm
- second arm link center-to-center: 135 mm
- theoretical planar reach: 280 mm from J1 to Z axis
- initial software-safe radial workspace: 70 to 265 mm
- Z travel: 110 mm
- nominal tool plate: 60 x 60 mm
- target total mass kept as low as practical
- initial payload target for qualification: 100 g
- 150 g and above are later measured tests, not assumed ratings

No counterweight in V2.

## Transmission

### J1
- NEMA17
- fully printed coaxial planetary reducer
- target reduction: 4:1
- gearbox is a self-contained module
- arm structural load is carried by the joint support/bearings, not the motor shaft

### J2
- NEMA17
- same 4:1 fully printed planetary module as J1
- standardizing the reducer avoids two different gearbox designs
- structural load is carried by the elbow support/bearings

### Z
- NEMA17 fixed to the second arm link
- direct printed rack and pinion
- pinion target: module 1.0, 16 teeth
- rack target: module 1.0, 10–12 mm face width
- 110 mm usable vertical stroke
- rack captured inside a rigid printed carriage so pinion/rack center distance cannot open up like the old arm gears
- printed replaceable slider shoes; bearing-assisted version can use salvaged bearings if available

No printed flexible belt.

## Planetary reducer design direction

Use an FDM-friendly fixed-ring, sun-input, carrier-output planetary arrangement.

The gearbox must:
- constrain all gear centers inside one rigid housing,
- use three or more planets,
- use involute teeth,
- use enough face width to distribute load,
- keep output support independent of the NEMA shaft,
- allow the gearbox to be replaced as one module.

A published compact NEMA17 4:1 printed planetary gearbox demonstrates that this class of reducer can be built with essentially printed parts plus motor-mount screws. Seizo V2 will use its own dimensions/interface rather than blindly copying another arm.

## Structural joints

Reuse existing bearings and fasteners from the current arm wherever practical.

Design assumptions to validate before production print:
- generic NEMA17 face pattern: 42 mm class
- motor shaft: nominal 5 mm
- common salvaged bearing target: 608 class where available
- final bearing pockets remain parametric until actual salvaged bearing OD/width are measured

Do not buy a different bearing merely because the CAD was drawn around one size.
Adapter sleeves/spacers should be printable.

## Link construction

J1-to-J2 link:
- one-piece hollow box link
- approximately 42 mm wide x 28 mm tall
- 145 mm joint-center spacing
- 3.2–4.0 mm walls
- internal ribs around motor/joint interfaces
- elbow motor mounts close to the link end

J2-to-Z link:
- one-piece hollow box link
- approximately 36 mm wide x 24 mm tall
- 135 mm joint-center spacing
- 3.0–3.6 mm walls
- ribbed Z-motor mount

The links are not scaled copies of the old arm.

## Base

- broad 220 x 220 mm printed base to resist tipping
- low center of mass
- J1 gearbox centered in the base
- optional existing fasteners can bolt/clamp the base to a board
- design must remain usable freestanding for low-speed bench tests

## Z carriage

The Z carriage is the most important printed linear component.

Design:
- rigid rectangular mast/rack
- captured on two opposing printed guide surfaces
- adjustable printed wear shoes
- 0.25–0.40 mm starting running clearance per guided face, tuned by printer/material
- anti-rotation built into rectangular guide geometry
- hard physical geometry prevents rack from disengaging from pinion
- tool plate and wrist camera mount at the bottom

If salvaged small bearings are available, a roller version can replace slider shoes without changing the arm interface.

## Tooling

V2 initially has:
- fixed vertical tool orientation
- modular printed 60 x 60 mm tool plate
- current gripper can attach after servo control is proven
- wrist camera attaches to the Z/tool module
- no powered wrist rotation in V2

A fourth actuator is deferred until three-axis pick/place repeatability proves that independent wrist rotation is actually needed.

## Material and slicing baseline

Design parts so PETG is acceptable, because it is tougher but less stiff than PLA.

Structural parts:
- 0.20 mm layer
- 5–6 walls
- 5–6 top/bottom layers
- 30–40% gyroid/cubic infill
- local solid/ribbed regions around bearing seats and motor mounts

Gears/rack:
- 0.16 mm layer preferred
- 6–8 walls
- high/solid infill where geometry requires
- slower print than cosmetic parts
- no support touching functional tooth surfaces where avoidable

If PLA+ is already available, it may be used for prototype gears because of stiffness/dimensional repeatability.
Do not require a new filament purchase to proceed.

## Electronics reuse

Keep:
- Raspberry Pi
- Arduino Uno
- CNC Shield
- 3 existing A4988 channels
- 3 existing NEMA17 motors
- cameras
- physical kill switch
- existing 12 V supply
- servo supply/controller after separate verification

No fourth stepper channel is needed.

## New axis semantics

GRBL/low-level motor channels will become:
- X -> J1 angle
- Y -> J2 angle
- Z -> vertical millimeters

Do not reuse the old arm's steps/mm values as physical calibration.

J1/J2 calibration will be defined as steps per degree.
Z will be steps per millimeter.

## Nominal resolution model

Assuming a 200-step motor and 1/16 microstepping:

J1/J2 with 4:1 reducer:
- 12,800 microsteps per output revolution
- about 35.56 microsteps per degree

Z with module-1 16-tooth pinion:
- pitch diameter 16 mm
- travel per motor revolution about 50.27 mm
- about 63.66 microsteps per mm

These are geometry starting points only. Final calibration is measured on the actual build.

## Kinematics

Planar SCARA:
x = L1*cos(theta1) + L2*cos(theta1 + theta2)
y = L1*sin(theta1) + L2*sin(theta1 + theta2)

z is the independent vertical rack axis.

Use the elbow configuration that keeps the links inside the declared safe workspace and avoids self-collision.

The overhead camera naturally maps to planar X/Y.
The wrist camera remains the close-range verification source.

## Build strategy

Do not print the whole arm immediately.

Phase A — one gearbox:
1. print one 4:1 reducer,
2. fit one NEMA17,
3. rotate unloaded,
4. check backlash, binding and gear wear,
5. run repeated forward/reverse cycles.

Phase B — planar skeleton:
1. print base, Link 1 and elbow joint,
2. fit J1/J2,
3. no Z or gripper,
4. prove smooth XY movement by hand and then at low motor speed.

Phase C — Z:
1. print Z mast, rack, carriage and pinion,
2. prove full vertical stroke without rack disengagement,
3. qualify holding and repeatability.

Phase D — tool:
1. attach camera,
2. attach proven gripper,
3. recalibrate camera geometry.

## Qualification gates

Before automatic movement:
- no gear disengagement,
- no motor/gearbox walking on shaft,
- no base lift at normal acceleration,
- no visible joint housing flex that changes gear center distance,
- 20/20 commanded return-to-point cycles without mechanical intervention,
- physical HOME/endstop strategy added,
- workspace limits measured,
- planner dry-run passes.

Before calling V2 a successful replacement:
- 20 lightweight object relocations,
- target >=18/20 successful,
- failures logged and classified,
- zero continuation after a detected mechanical failure.

## What is deliberately NOT in V2

- four-foot reach
- fourth NEMA17
- TB6600
- timing belts
- purchased lead screw
- purchased linear rail
- independent powered wrist
- mobile base integration
- decorative shell before mechanics pass
- automatic motion before homing/reference is reliable
