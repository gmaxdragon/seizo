# Seizo Y/Z Belt Conversion Plan v1

## Problem being solved

Operator-observed failure:
- Y/Reach and Z/Height sometimes lose proper gear mesh.
- clicking occurs when teeth fail to stay engaged under load or after travel changes the geometry.
- Z can progress far enough that its gear/coupling comes loose.
- continuing to command the motor after loss of engagement damages repeatability and can loosen hardware.

This is a transmission/structure problem. Software cannot make two spur gears stay meshed if their center distance or alignment changes.

## Design decision

Replace the fragile direct printed-gear mesh on Y and Z with a **real reinforced synchronous timing belt drive**.

Do NOT 3D print the belt.

Recommended prototype family:
- 3 mm pitch GT/GT3-style synchronous belt
- 9 mm belt width
- real fiberglass-reinforced belt
- flanged motor pulley
- driven pulley rigidly fixed to the joint
- adjustable motor position or a properly designed tensioning mechanism

Why 3M / 9 mm instead of the common tiny 2 mm / 6 mm printer belt:
- Seizo is a long-lever robot arm, not a lightweight printer carriage.
- 3 mm pitch and 9 mm width provide a more robust prototype transmission while remaining compact.
- Gates lists 3 mm pitch, 9 mm width GT3 belts and identifies the family for stepper/servo and robotics applications.

## Preserve the existing ratio first

Do not blindly redesign the joint ratio.

Measure or count:
- current motor gear teeth: N_motor
- current joint gear teeth: N_joint

Current reduction ratio:
    ratio = N_joint / N_motor

Choose timing pulleys with approximately the same ratio first.

Examples only:
- current ratio ~1:1 -> 30T motor / 30T joint
- current ratio ~2:1 -> 20T motor / 40T joint
- current ratio ~3:1 -> 20T motor / 60T joint

Only increase reduction if the repaired transmission still lacks torque. More reduction gives more joint torque but less joint speed.

## Minimum geometry rules

For each loaded pulley:
- target at least 6 belt teeth fully in mesh.
- target at least 60 degrees of belt wrap.
- keep shafts parallel.
- keep pulley faces aligned.
- make the supporting structure rigid enough that center distance does not visibly change under arm load.
- provide controlled tension adjustment rather than forcing a belt over pulley flanges.

If an idler is absolutely needed, treat reversing direction carefully because tight/slack sides swap. A sliding motor mount is preferred for this prototype.

## Seizo mounting strategy

Preferred:
1. Existing NEMA17 remains fixed to an adjustable/slotted plate.
2. Motor gets a small flanged timing pulley.
3. Joint receives a larger or equal-ratio timing pulley.
4. Pulley should attach to a rigid hub/shaft interface, not only friction on printed plastic.
5. NEMA17 plate gets approximately 8-12 mm usable tension adjustment.
6. Once tension is correct, all motor mounting screws clamp the plate rigidly.
7. Add physical retention so the Z pulley/gear cannot walk axially off its shaft.

Avoid:
- springy motor mounts,
- intentionally flexible printed arms holding pulley spacing,
- belt tension so high that bearings/printed hubs deform,
- smooth printed shaft bores relying only on friction,
- printed TPU timing belts for final motion.

## Pulley construction

Best prototype order:
1. metal motor pulley when the actual motor shaft diameter is confirmed,
2. commercial driven pulley if geometry allows,
3. otherwise a printed driven pulley with a rigid mechanical hub/bolt pattern.

If a driven pulley is printed:
- use PETG/ASA/nylon rather than brittle low-infill PLA for the structural hub,
- use high perimeter count,
- orient the part so belt load does not split layer lines,
- mechanically retain it to the joint with bolts/key/clamp where possible,
- do not rely on a press-fit alone for Z.

The exact GT tooth profile should come from a proven parametric timing-pulley profile, not hand-drawn triangular teeth.

## Measurements needed for final printable mounts

For Y and Z, only record:
1. motor shaft center to joint shaft center, mm,
2. current motor-gear tooth count and joint-gear tooth count,
3. motor shaft diameter,
4. joint shaft/hub diameter and how the current gear attaches,
5. maximum available belt/pulley width,
6. one photo square-on to the two shaft axes with a ruler in frame.

With those values the belt length, pulley tooth counts and adjustable mounting travel can be generated instead of manually CADing from scratch.

## Commissioning sequence

After belt conversion:
1. power OFF: rotate mechanism through safe range by hand if mechanically possible,
2. verify belt tracks in the center of both pulleys,
3. verify nothing walks axially,
4. verify no tooth jump through the range,
5. start with the existing low Seizo acceleration,
6. one small Y or Z button press,
7. inspect,
8. opposite press,
9. mark PASS only after both directions stay engaged,
10. then calibrate conservative software travel limits.

Do not discover travel limits by driving into clicking/hard stops.

## Software interaction

Seizo now quarantines a component after it is marked physical FAIL.
Y/Z remain blocked until hardware test is explicitly reset after repair.

Automatic mode remains blocked until:
- current-boot hardware test passes,
- cameras live,
- HOME/reference set,
- safe travel limits calibrated,
- planner dry-run passes.
