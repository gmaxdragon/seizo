# Seizo

Seizo is an experimental robotic-arm platform built around a Raspberry Pi, an Arduino Uno/CNC Shield stepper stack, an Arduino Nano servo controller, dual USB cameras, deterministic safety gates, and a constrained AI planning layer.

This public repository is a curated code snapshot from the actively developed private Seizo control repository. It intentionally excludes live device telemetry, remote job queues, machine-local state, credentials, and deployment-specific data.

## Architecture

```text
Human / browser
      |
      v
Raspberry Pi guided controller
      |
      +--> deterministic safety + workspace gates
      |
      +--> high-level semantic planner
      |
      +--> Seizo Skill representation
      |
      +--> Arduino Uno / CNC Shield / A4988 -> X/Y/Z steppers
      |
      +--> Arduino Nano -> gripper + wrist servos
      |
      +--> dual USB cameras -> view / verification
```

The still-installed ESP32 is intentionally isolated from Nano discovery in the current codebase. See `docs/ESP32_TO_NANO_MIGRATION_V1.md`.

## Core rules

- AI proposes intent and semantic actions, not unrestricted motor commands.
- Deterministic code validates plans and workspace bounds.
- Manual control remains the primary live path.
- Automatic physical execution is not enabled by this public snapshot.
- Physical HOME is session-referenced until repeatable homing hardware is installed.
- The physical emergency-stop / kill-switch path is independent of software STOP.

## Key files

- `scripts/seizo_phone_control.py`: guided local control UI
- `scripts/seizo_record_replay_v21.py`: bounded skill recording/replay engine
- `seizo_core/ai_plan.py`: constrained semantic plan schema
- `seizo_core/local_semantic_planner.py`: fast deterministic planner
- `seizo_core/auto_gate.py`: readiness and dry-run gates
- `seizo_core/guarded_executor.py`: future guarded execution kernel
- `seizo_core/workspace_limits.py`: session HOME and software workspace limits
- `seizo_core/controller_inventory.py`: read-only Uno/Nano/ESP32 identity separation
- `firmware/nano_servo_controller/nano_servo_controller.ino`: Nano servo firmware

## Offline tests

The included CI is intentionally hardware-free.

```bash
python -m unittest -q \
  tests.test_auto_gate \
  tests.test_controller_inventory \
  tests.test_guarded_executor \
  tests.test_local_semantic_planner \
  tests.test_nano_servo_backend \
  tests.test_phone_control \
  tests.test_workspace_limits
```

## Hardware

See `Hardware.md` and `CONTROL_MAP.md` for the current reference build. Hardware revisions, wiring, limits, gearing, and calibration differ between builds, so the reference values should not be assumed safe for another robot.

## Status

The deterministic planner and virtual safety stack have passed large software-only stress campaigns. Real arm calibration, repeatable homing, travel-limit commissioning, and skill teaching remain active development areas.
