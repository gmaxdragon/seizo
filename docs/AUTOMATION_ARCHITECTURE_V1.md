# Seizo Automation Architecture v1

## Goal

Move from guided manual control to autonomous skills without letting AI, cameras, or stale state bypass physical safety.

## Safety hierarchy

1. Physical kill switch / power removal
2. Bounded manual actuator commands
3. Current-boot hardware verification
4. Two live camera feeds
5. Session HOME/reference
6. Persisted conservative software travel limits
7. No-motion planner preview
8. Future guarded automatic executor
9. Vision correction and learned skill improvement

## Current implementation

- Manual controls remain bounded and operator-triggered.
- Hardware PASS state is valid only for the current Raspberry Pi boot.
- HOME is session-only and is invalidated by STOP/DISARM or process restart.
- X/Y/Z are tracked relative to HOME using accepted manual commands.
- While HOME is operator-set, travel limits are deliberately session-scoped and are cleared on STOP/DISARM or restart. Reusing persisted limits against an unverified manual HOME is unsafe.
- After physical homing switches are proven, limits can persist because they will be tied to a repeatable physical reference frame.
- Once HOME exists, calibration records SAFE MIN/MAX points selected by the operator.
- Once limits are configured, manual X/Y/Z commands are checked against those limits.
- Calibration must end with all tracked axes back near HOME.
- The automatic readiness gate reports exact blockers.
- Planner dry-run validates a bounded out-and-back Seizo Skill against current readiness and workspace limits.
- Planner dry-run executes zero physical commands.
- No `/auto/run` physical execution route exists.

## Important limitation

This is not yet unattended homing. The arm has no encoders or homing switches. If the arm is moved by hand, skips steps, loses power, or starts from a different pose, software position can be wrong. A repeatable physical HOME sensor/endstop system is the next major hardware safety upgrade.

## Future automatic executor requirements

Before adding an automatic execution route:

- current-boot hardware test PASS
- cameras live
- HOME/reference valid
- travel limits configured
- planner preview PASS
- execution broken into bounded Seizo Skill actions
- workspace checked before every stepper command
- camera observation after movement, never automatic blind retries
- software STOP plus physical kill switch
- failure must halt, not retry motion
- automatic executor must remain separate from AI intent generation

## UI rule

Normal operation should show 3-5 buttons at a time, including persistent STOP/DISARM. Automatic Setup is a guided wizard, not a dense control panel.
