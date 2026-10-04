# Seizo Hardware

This file is the source of truth for Seizo's physical hardware.

## Arm
- Modified Jackytle MK2 Plus
- Approx. 4 ft full extension
- 3x NEMA 17 motors currently
- Planetary/geared mechanisms
- Large 2-finger parallel gripper
- Gripper material: PETG
- MG90S gripper servo
- MG90S wrist servo
- Gripper mounted

## Motor Control
- Arduino Uno
- CNC Shield V3
- A4988 stepper drivers

## Compute
- Raspberry Pi 4 2GB

## Vision
- 2x USB RGB cameras
- 1x wrist camera
- 1x overhead/workspace camera

## Power
- 12V 5A power supply

## Mobile Base
- NEMA 17 for forward/backward drive
- 2 rear driven wheels
- 2 front free-spinning steering wheels
- MG90S steering servo
- Planetary/geared drivetrain concept
- Still in development

## Sensors
- 2x ultrasonic sensors
- Limit switches: NOT currently installed
- Planned homing upgrade: 1 repeatable HOME switch for each current X/Y/Z stepper axis
- Encoders: TBD

## Other Electronics
- Arduino Nano remains installed for the current gripper/wrist servo backend.
- ESP32 is still physically installed as of 2026-10-04. It has not been removed or fully migrated to the Nano.
- The ESP32's current functional/wiring role is not yet verified in the live software source of truth, so Seizo must not send it serial commands during controller discovery.
- Last published USB telemetry showed a CP2102-class device at VID:PID 10c4:ea60, treated as the current ESP32 candidate.
- Last published USB telemetry showed a CH340/CH341-class device at VID:PID 1a86:7523, treated as the current Nano candidate.
- Future option: consolidate appropriate ESP32 functions onto the Nano only after each wire, voltage level, peripheral, and timing requirement is mapped and validated.

## Current Mechanical Problems
- X/base lift fix has been designed by the operator and needs physical validation.
- Y/reach uses a small NEMA17 pinion driving a larger horizontal spur gear. Mesh consistency under load is the current Y problem.
- Z/height can click under load and its driven gear/coupling has come loose; retention/mesh must be fixed before more repeated Z testing.
- Gripper and wrist servos failed the latest guided test. Nano/servo signal path is being diagnosed separately from the arm mechanics.
- Payload not measured.
- Physical homing/reference system still needed.

## Rules
- Do not assume hardware is installed unless it is listed here.
- Update this file whenever hardware changes.
