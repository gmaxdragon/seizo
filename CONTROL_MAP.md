# Seizo Control Map

Current source of truth for the live Seizo reference arm. If a path is not listed as current here, do not assume it is part of normal operation.

## Version lanes

- 0.x: hardware-only development
- 1.x: software-only development
- 2.x: integrated software + physical hardware

## Current compute and control path

```text
Browser :8790
  -> guided Seizo phone controller on Raspberry Pi
     -> Arduino Uno / CNC Shield / A4988 for X/Y/Z steppers
     -> Arduino Nano over USB for gripper/wrist servos
     -> ESP32 remains physically installed but is not part of the current guided control path
  -> view-only camera service :8787
     -> overhead Logitech BRIO
     -> wrist icSpring camera
```

Automatic physical execution is NOT enabled.

## Stepper controller

Controller:
- Arduino Uno
- USB serial: 24333313131351101271
- expected VID:PID: 2341:0043
- current Linux node normally /dev/ttyACM0
- Grbl 0.9j @ 115200 baud
- CNC Shield V3 + A4988

Axis mapping:
- GRBL X = physical base rotation
- GRBL Y = reach
- GRBL Z = height

Current guided manual profile:
- X/Base: 3.00 GRBL mm per button action, 90 mm/min
- Y/Reach: 3.00 GRBL mm per button action, 90 mm/min
- Z/Height: 1.50 GRBL mm per button action, 60 mm/min
- session acceleration: X/Y 15 mm/s^2, Z 8 mm/s^2
- hard single-command bound: <=3.0 GRBL mm
- hard feed bound in compatibility layer: <=150 mm/min

ARM preflight:
- exact Uno identity required
- waits for proven Uno/Grbl startup timing
- identifies Grbl 0.9j from startup or $I
- GRBL startup blocks must be empty
- $100/$101/$102 must remain 250.000 steps/mm +/- 0.01
- acceleration settings must be present and within accepted range
- parser is set to G21/G90
- controller must reach Idle
- no Nano flashing is part of ARM or session startup

The physical kill switch remains the emergency stop. Software STOP sends GRBL feed hold before closing the session but is not an E-stop.

## Servos

Current guided website servo backend:
- Arduino Nano over USB
- current Nano USB candidate identity: VID:PID 1a86:7523
- Nano discovery is restricted to the expected Nano USB identity before HELLO/PING is sent
- current ESP32 candidate identity: VID:PID 10c4:ea60 (CP210x)
- ESP32 is never probed as a Nano and receives no Nano provisioning traffic
- Nano firmware handshake: SEIZO_NANO_SERVO_V1
- 115200 baud
- Nano D9 -> gripper signal
- Nano D10 -> wrist signal
- external regulated 5V powers servos
- Nano and servo power share common ground
- servos are not powered from Nano 5V

Current safe integration range:
- gripper: 1400..1600 us
- wrist temporary integration range: 1400..1600 us

Guided controls:
- N = gripper open
- M = gripper close
- O = wrist -
- P = wrist +
- Hand + Wrist screen also provides a read-only Nano HELLO/PING verification while DISARMED. It sends zero servo output commands.

Older direct Raspberry Pi GPIO servo paths remain historical/debug code, not the current guided-site backend.

## Cameras

Overhead:
- Logitech BRIO
- serial E3D4B871
- global workspace view

Wrist:
- icSpring USB camera
- serial 2409181858122
- close-range view

Current live camera service:
- internal/view-only service on port 8787
- main operator site is port 8790
- both feeds are shown from the guided site
- camera service itself contains no motor-control path

Historical object tracking and cross-camera handoff experiments remain evidence, but vision-driven physical correction is not enabled in the current guided runtime.

## Guided operator website

Primary URL:
- http://seizo-pi.local:8790/
- direct Pi IP is preferred when .local discovery is unreliable

UX rule:
- 3-5 buttons visible at a time
- persistent STOP / DISARM
- one step at a time

Normal flow:
1. ARM MANUAL
2. five-row current-boot hardware test
3. manual drive or Automatic Setup

Five physical checks:
- Base
- Reach
- Height
- Gripper
- Wrist

A PASS is valid only for:
- the current Raspberry Pi boot ID
- the current manual motion profile signature

Changing boot/profile forces a new hardware test.

After a physical FAIL, that component is quarantined from further motion. The guided site can unlock only the next failed component for a focused retest; other failed components remain quarantined.

## Local web-control security

The live control site:
- accepts only local/private hostnames or private/loopback IPs
- checks same-origin browser requests
- requires the custom X-Seizo-Control header for POST control
- bounds POST request size/type
- sends basic browser security headers
- remains local HTTP, so it should stay on a trusted private LAN

## Session HOME and workspace

Physical homing switches are NOT installed yet.

Interim supervised reference:
- operator chooses a physical HOME pose
- current pose becomes tracked X0/Y0/Z0
- tracking is based on accepted relative commands, not encoders
- hand movement, missed steps, mechanical slip, reset, or power loss can invalidate it

Critical rule:
- manual HOME is session-only
- its software travel limits are also session-only
- STOP/DISARM, service restart, HOME clear/replacement invalidate the reference and clear the limits
- old limits are never reused against a newly chosen manual HOME

Limit calibration:
- save conservative SAFE MIN and SAFE MAX for X/Y/Z
- do not intentionally hit hard mechanical stops
- HOME 0 must lie strictly inside each axis range
- calibration finishes only after all tracked axes return close to HOME
- once configured, tracked manual stepper moves are checked before motion and committed after accepted motion

Native Grbl $20/$21/$22 remain off until physical homing/limit commissioning is complete.

## Automatic Setup

Current live Automatic Setup is a guided readiness wizard.

NEXT sequence:
1. ARM MANUAL
2. TEST HARDWARE
3. CHECK CAMERAS
4. SET HOME
5. CALIBRATE LIMITS
6. PLANNER DRY RUN

Planner dry-run:
- validates a bounded out-and-back XYZ Seizo Skill
- checks current readiness and software workspace
- executes zero physical commands
- returns exact blockers when not ready

Live readiness always reports:
- `automatic_motion_enabled: false`

There is deliberately NO `/auto/run` web route.

## Future guarded executor

A disconnected `seizo_core/guarded_executor.py` safety kernel exists for future automatic execution testing.

It is not connected to the live website or hardware.

Its contract requires all three:
1. planning gate ready
2. future safety layer sets `automatic_motion_enabled=true`
3. explicit execution authorization

It also requires:
- workspace check before each stepper action
- one physical action followed by one observation
- zero blind motion retries
- STOP before/after action
- any failure after physical motion begins invalidates HOME

## Physical homing upgrade

Current:
- no X/Y/Z home switches
- no encoders

Planned:
- one repeatable HOME switch for X, Y, Z
- custom homing sequence for this articulated arm:
  1. Z / Height
  2. Y / Reach
  3. X / Base

Do not enable stock Grbl $H yet. Stock Grbl homes Z then X+Y together, which is not the target articulated-arm sequence.

See:
- `docs/HOMING_UPGRADE_PLAN_V1.md`
- `docs/AUTOMATION_ARCHITECTURE_V1.md`

## Software delivery and telemetry

- GitHub repo: gmaxdragon/SeizoOfficial
- main is the live code branch
- external self-healing maintenance agent lives outside the git checkout
- it checks/repairs roughly every 60 seconds, with an independent cron fallback when available
- candidate commit is software-tested before the live checkout fast-forwards
- UI restarts only after candidate core tests pass
- corrupt/missing repo checkout can be rebuilt automatically while the robot is DISARMED
- telemetry publishes to the separate device-status branch roughly every 60 seconds while online
- maintenance never initiates physical motion or Nano flashing

## Controller migration status

The ESP32 is still installed. Its current wiring/function ownership must be mapped before removal.

A read-only controller inventory now distinguishes:
- verified GRBL Uno
- Nano USB candidate
- ESP32 USB candidate
- unknown serial devices

USB identity is not treated as firmware verification. Only the Nano candidate may receive the bounded Nano HELLO/PING handshake.

See:
- `docs/ESP32_TO_NANO_MIGRATION_V1.md`

## Current known limitations

- no physical homing/reference switches
- no encoders
- command coordinates are not measured physical pose
- current operator-set HOME cannot survive STOP/restart safely
- camera-to-axis response is not yet part of the current live guided runtime
- no automatic pick/place execution yet
- gripper mount/payload and long-run repeatability still need physical validation
- mobile base is separate and not part of the current arm control runtime

## Non-negotiable architecture rule

AI may propose intent and Seizo Skills.

Only deterministic validated robotics code may authorize bounded physical actions.

AI never sends unrestricted raw motor commands or G-code to the robot.
