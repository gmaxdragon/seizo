# Seizo Homing Upgrade Plan v1

## Why this is the next hardware milestone

The current arm has no limit switches or encoders. Software HOME and tracked relative motion are useful for supervised setup, but they cannot prove pose after:
- hand movement,
- missed steps,
- controller reset,
- power loss,
- mechanical slip.

True repeatable automatic startup needs a physical reference.

## Current controller facts

Current proven controller:
- Arduino Uno + CNC Shield V3
- Grbl 0.9j
- X/Y/Z mapped to Seizo base/reach/height
- $100/$101/$102 = 250.000 steps/mm
- current homing disabled ($22=0)
- current hard limits disabled ($21=0)
- current soft limits disabled ($20=0)

Official Grbl behavior:
- $22 enables the homing cycle.
- $23 controls homing direction.
- $24 is the slow locating feed.
- $25 is the faster homing seek.
- $26 is switch debounce.
- $27 is pull-off after switch contact.
- Default homing sequence is Z first, then X and Y together.
- A hard-limit event immediately halts motion and position should be considered untrusted.

References:
- https://github.com/gnea/grbl/blob/master/doc/markdown/settings.md
- https://github.com/gnea/grbl/blob/master/grbl/config.h

## Seizo-specific decision

Do **not** enable stock $H homing on the current arm yet.

For an articulated arm, simultaneous X/Y homing means Base + Reach move together. That is not the sequence we want to introduce without physical testing.

Target homing order:

1. **Z / Height** to a clearance-safe reference.
2. **Y / Reach** retract toward a known folded/retracted position.
3. **X / Base** rotate to a known reference last.

The exact direction for each axis must be selected after switch placement and a manual direction check.

## Hardware plan

Install one repeatable home switch per current stepper axis:

- X: Base HOME
- Y: Reach HOME
- Z: Height HOME

Requirements:
- mechanically rigid mounting,
- switch actuator contacted before a hard mechanical stop,
- enough travel after first contact for safe deceleration/pull-off,
- strain-relieved wiring,
- cable routing separated from stepper motor wiring where practical,
- physical kill switch remains reachable during commissioning.

A fourth switch will be added with the planned fourth NEMA axis later.

## Switch wiring strategy

For the first commissioning pass, use the simplest stock-Grbl-compatible wiring:
- switch signal between the relevant limit input and GND,
- use Grbl's normal internal pull-up behavior,
- verify the electrical state before enabling homing.

Stock Grbl documentation describes normally-open switches to GND with normal pull-up behavior. If Seizo later uses normally-closed/fail-safe wiring, treat that as a separate electrical change and validate the required inversion/pull resistor arrangement rather than guessing.

Do not change $5 until the actual switch circuit is installed and measured.

## Firmware plan

Stock Grbl's default Z then X+Y homing order is not acceptable as the final Seizo sequence.

Preferred path:
1. Keep current proven 0.9j firmware untouched while switches are mechanically installed.
2. Verify each switch individually with a read-only limit-state test.
3. Build a dedicated Seizo Grbl firmware configuration with separate homing cycles:
   - Z first,
   - Y second,
   - X third.
4. Bench-test the custom firmware with motor power controlled and kill switch available.
5. Only then enable $22 and perform physical homing.

Do not flash the Uno as part of normal website startup.

## Conservative commissioning settings

Do not write these automatically. These are starting values to evaluate after switches exist.

- $22=1 only after all required home switches are verified.
- $21=0 initially. Keep hard limits off during first homing commissioning.
- $20=0 initially. Keep native Grbl soft limits off until machine-coordinate behavior is verified.
- $24: start around the existing slow/proven motion range.
- $25: start conservatively, not at an aggressive CNC seek speed.
- $26: debounce appropriate to the selected switch.
- $27: enough pull-off to reliably release the switch.

Exact values must be validated on the physical arm.

## Software transition

Today:
- operator ARM,
- current-boot hardware test,
- cameras,
- session HOME,
- software travel limits,
- planner dry-run.

After physical homing is proven:
- replace "SET CURRENT POSE AS HOME" with "HOME ARM",
- successful homing creates the session reference automatically,
- saved travel limits become tied to the physical home switch frame,
- failed/aborted homing leaves automatic readiness locked,
- STOP, reset, hard limit, or uncertain motion invalidates HOME and requires re-homing.

## Hard limits

Do not enable hard limits on day one.

Grbl treats a hard-limit trigger as a critical event and the machine position may be lost. Once switch wiring proves noise-resistant, evaluate $21=1 separately. If enabled, a hard-limit event must:
- halt,
- invalidate software HOME,
- require reset/re-home,
- never auto-retry.

## Exit criteria for true homing

Before Seizo can call physical homing "ready":
- each switch triggers repeatably,
- no false triggers during stepper movement,
- safe homing direction verified per axis,
- custom homing order verified,
- pull-off reliably clears every switch,
- repeated home cycles return to the same physical pose within measured tolerance,
- HOME remains invalid after any homing failure,
- software limits align with the physical home frame,
- kill switch tested.

## What this does not solve

Homing switches create a repeatable reference, but they do not detect missed steps during normal movement. Encoders or additional visual/physical validation remain a later reliability upgrade.
