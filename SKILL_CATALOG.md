# Seizo Skill Catalog

This catalog separates **authoring modes** (how a user creates a skill) from
**behavior skills** (what the robot can do). Ratings are planning aids, not proof
of completion.

Scale:
- Difficulty: 1 = easiest, 5 = hardest
- Coolness: 1-10
- Usability: 1-10

| Skill / Mode | Type | Difficulty | Coolness | Usability | Status / Notes |
|---|---|---:|---:|---:|---|
| Manual Control | Authoring | 1 | 7 | 10 | Proven; guided browser flow is the current operator surface |
| Record & Replay | Authoring | 2 | 9 | 10 | Engine/history retained; not the current guided-runtime priority until reference/limits are stronger |
| Return to Recording Start (U) | Behavior | 1 | 8 | 10 | Included in 2.1 |
| Replay Skill | Behavior | 1 | 8 | 10 | Included in 2.1 |
| Reverse Replay | Behavior | 2 | 8 | 8 | Easy follow-on using inverse skill actions |
| Loop / Repeat Skill | Behavior | 2 | 8 | 9 | Useful after repeatability baseline |
| Named Relative Waypoints | Behavior | 2 | 7 | 9 | Safer after better reference discipline |
| Digital Arm | Authoring | 3 | 9 | 9 | Planned |
| AI -> Skill / Text -> Movement | Authoring | 3 | 10 | 9 | Planned after deterministic skill compiler |
| Drag & Drop Blocks | Authoring | 3 | 8 | 8 | Planned |
| Code Mode | Authoring | 2 | 7 | 8 | Planned; compiles to same Skill format |
| Camera-Guided Manual Alignment | Behavior | 4 | 9 | 8 | Experimental code/evidence retained; physical correction is quarantined from the current guided runtime |
| Teach by Demonstration | Authoring | 5 | 10 | 9 | Camera/live-feed dependent |
| Camera-Verified Pick & Place | Behavior | 5 | 10 | 10 | Wrist camera verifies grasp; overhead camera checks global placement/drift |
| Object Sorting | Behavior | 5 | 10 | 9 | Later closed-loop vision skill |
| Skill Macros / Compose Skills | Behavior | 3 | 9 | 10 | High leverage after several proven base skills |

## Build priority

1. Finish the **reference/safety foundation**: guided hardware check, session HOME, conservative limits, planner dry-run, then physical X/Y/Z homing switches.
2. Prove **deterministic relocation** with the guarded executor only after physical homing/reference is repeatable.
3. Re-introduce **Record & Replay**, Reverse Replay and loops only through the same current workspace/executor safety layer.
4. Add **Digital Arm** and **Text -> Skill** as alternate authoring surfaces over the same Skill schema and allowlisted primitives.
5. Re-introduce camera-driven correction only after a measured camera-to-axis model exists and the guarded executor owns physical authorization.
6. Add teach-by-demonstration and autonomous pick/place after deterministic relocation is measured across repeated trials.

## Product architecture

All authoring modes compile into the same deterministic Seizo Skill representation:

manual / record / AI / demonstration / drag-drop / code
-> Seizo Skill
-> deterministic validator
-> bounded executor
-> robot

A skill is not considered proven merely because software accepted its commands.
Physical behavior and repeatability must be measured separately.


## Camera verification architecture

- Wrist camera = local truth for final approach, grasp confirmation, object retention and placement confirmation.
- Overhead camera = global truth for target selection, workspace position, gross drift/stall detection and post-move correction.
- Camera output proposes corrections; deterministic motion validation approves them.
- Before any camera-driven action, the live feed must be visible to the operator.
- A camera can detect disagreement between commanded and observed state, but it does not replace encoders or a physical kill switch.

## Future local controller architecture

If long servo signal wires or Linux-side PWM become a reliability bottleneck:
- Raspberry Pi stays the high-level brain for vision, planning and skills.
- Arduino Uno/CNC Shield stays the stepper controller.
- Preferred future local servo/IO coprocessor: ESP32-C3 Super Mini.
- Simpler fallback: Arduino Nano.
- Use a wired Pi-to-controller link for deterministic control.
- Keep the physical kill switch and independent servo power architecture.
