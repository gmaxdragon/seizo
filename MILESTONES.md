# Seizo Milestones

This file records important build days and turning points in Seizo's development.

> Note: Early history is incomplete. Dates below are based on the records currently remembered. Approximate dates are labeled as such rather than presented as exact.

## July 9, 2026 — Printing Finished + Motors Arrived
- Finished printing the main robot parts.
- Motors arrived.
- This marked the transition from printed parts into full physical assembly.

## July 10, 2026 — First Full Robot Build
- Built the robot in its basic form, without later add-ons.
- This was the first day Seizo existed as a complete physical robot structure rather than separate printed parts.

## July 15, 2026 — Wiring Became the Main Blocker
- After repeated attempts to wire and run the arm with TB6600 stepper drivers, it became clear that the wiring/control approach was too difficult and unreliable.
- Voltage-drop problems were a major issue.
- This became an important design pivot: the original motor-control setup was not practical enough for the arm.

## Around August 2, 2026 — CNC Shield Control Pivot
- Switched to a CNC Shield-based motor-control setup so the arm could be used more reliably.
- This was the key step that made practical arm control much easier than the earlier TB6600 wiring approach.
- Exact date is approximate.

## September 6, 2026 — Wrist Vision + Telemetry Milestone
- Established the wrist-camera grasp reference at approximately X=350 px, Y=317 px.
- Ran 5 guided wrist-alignment validation trials and passed all 5.
- Latest test results:
  - 5/5 successful alignment trials
  - 100% physical pass rate
  - lowest template-match score: ~74.4%
  - average template-match score: ~84.6%
- Connected Raspberry Pi test telemetry to the private `SeizoOfficial` GitHub repository.
- Seizo can now record wrist-alignment results on the Pi, push them to GitHub, and have them inspected remotely.
- This marks the point where Seizo's wrist vision moved from a visual demo toward a measured manipulation subsystem.

## September 6, 2026 — Overhead → Gripper Camera Vision Handoff Proven
- Established the two-camera manipulation architecture:
  - fixed Logitech BRIO on the red tower for global/overhead target selection
  - icSpring camera on the gripper/wrist for close-range final alignment
- Used the Fusion HAT itself as the test pickup object.
- Overhead AI scan successfully produced object candidates and the selected board was labeled as an `electronics board`.
- Fixed the earlier tracker-drift problem (“Seizo Joy-Con drift”) by freezing the overhead selection after the user click and changing the wrist tracker so it does not cumulatively wander when the scene is stationary.
- Proved cross-camera target handoff: the AI found the same physical electronics board in the gripper-camera view despite the large viewpoint change.
- Final gripper-camera tracking validation:
  - test passed
  - 100% wrist tracking uptime
  - minimum wrist tracking score: ~98.6%
  - 0 lost frames
  - stable pixel-error output relative to grasp center at X=350 px, Y=317 px
- The gripper camera now produces `EX`, `EY`, and distance-to-grasp-center values that can feed the next closed-loop servo-control stage.
- This is the first proven Seizo perception chain from global target selection → same-object handoff → stable local gripper tracking.
- No motors were moved during this test; servo integration is the next control milestone.

## September 19, 2026 — Seizo 1.1 Headless Terminal + Autonomous Software Delivery Proven
- Locked Seizo's version convention:
  - `0.x` = hardware-only development
  - `1.x` = software-only development
  - `2.x` = combined software + physical-hardware integration
  - decimal digit = iteration number
- Established **Seizo 1.1 Headless Terminal** as the software-only headless milestone.
- Retired the old Seizo web runtime from normal execution; Headless 1.1 is terminal/telemetry driven.
- Proved the zero-motion software mock:
  - X/Y/Z virtual out-and-back logic passed
  - feedback-driven step shrink/grow logic passed
  - virtual pose returned home
  - physical motion: false
- Proved automatic Pi → GitHub telemetry through `device-status/device_status_latest.json`.
- Proved GitHub → Pi automatic deployment end-to-end:
  - pushed harmless probe commit `6420351`
  - Pi pulled it automatically
  - Pi reported `autodeploy_deployed_6420351`
  - removed the probe in cleanup commit `b0cd24b`
  - Pi pulled the cleanup automatically and reported `autodeploy_deployed_b0cd24b`
- GitHub CLI authentication was confirmed valid on the Pi.
- Working tree was clean and the auto-deploy timer was active.
- Raspberry Pi reported no throttling (`throttled=0x0`).
- Arduino Uno was detected at `/dev/ttyACM0` with USB serial `24333313131351101271`.
- The Headless 1.1 telemetry collector opened no serial device, wrote no GPIO, and sent zero motor/servo commands.
- New operating rule: the operator should not relay software-visible logs/screenshots when Seizo can publish telemetry automatically.
- Auto-deploy may install software changes but may never itself trigger physical motion.
- Next integrated live-arm work belongs in the **2.x** lane and requires deliberate local physical-motion authorization.


## September 20, 2026 — Seizo 2.0 First Real Manual Arm Motion Proven
- Seizo crossed from software-only control into real software + hardware integration.
- The Raspberry Pi controlled the Arduino Uno / CNC Shield / A4988 stack running Grbl 0.9j.
- Six-key manual control was established:
  - W/S = Y+/Y-
  - A/D = base rotation R-/R+ mapped to GRBL X-/X+
  - Q/E = Z+/Z-
- The operator visually confirmed that the physical arm moved.
- Telemetry independently confirmed repeated accepted GRBL commands and changing machine-position reports across X, Y, and Z command paths.
- Current manual tap size at the proven stage:
  - 0.20 GRBL mm per tap
  - approximately 50 configured steps per tap at $100/$101/$102 = 250 steps/mm
  - feed = 60 GRBL mm/min
- Grbl 0.9j compatibility was handled with explicit G91 incremental moves followed by restoration to G90/G0 after each move.
- No homing, hard limits, soft limits, or encoders are installed; reported GRBL coordinates remain commanded/controller coordinates rather than measured physical pose.
- The physical kill switch remains the emergency stop; software hold is not an E-stop.
- This is the first confirmed Seizo **2.x** physical-motion milestone.


## September 26, 2026 — Guided Control + Automation Safety Foundation

- Replaced the crowded manual website with a guided control flow:
  - 3-5 buttons visible at a time;
  - persistent STOP / DISARM;
  - ARM -> five physical checks -> manual drive or Automatic Setup;
  - one dynamic NEXT action in Automatic Setup.
- Repaired the Pi software-delivery/telemetry path and strengthened startup health checks so a responding port is not enough to claim the website is ready.
- Fixed the web ARM preflight to use the proven Grbl 0.9j identification timing instead of a brittle startup-banner-only check.
- Locked the current GRBL motion scale for tracked setup:
  - $100/$101/$102 = 250.000 steps/mm;
  - a scale mismatch blocks ARM instead of silently corrupting referenced coordinates.
- Bound physical hardware PASS to the current Pi boot and current motion-profile signature.
- Added remote ARM, camera, web, workspace and automation-readiness diagnostics.
- Both current cameras were observed live on the repaired runtime before the Pi later went offline:
  - overhead BRIO on /dev/video2;
  - wrist icSpring on /dev/video0.
- Added supervised Automatic Setup:
  - session HOME/reference;
  - tracked X/Y/Z relative coordinates;
  - conservative SAFE MIN/MAX workspace calibration;
  - mandatory return to HOME before calibration completion;
  - no-motion planner dry-run.
- Corrected an important safety flaw: while HOME is manually chosen, HOME and its software travel limits are both session-scoped. STOP/DISARM, restart or HOME replacement clears the limits so stale boundaries cannot be reused against a different pose.
- Added a pure automatic-readiness gate that reports concrete blockers while keeping `automatic_motion_enabled=false`.
- Added a disconnected guarded automatic-executor kernel for future use:
  - not connected to the website or hardware;
  - requires planning readiness, future explicit motion-enable and execution authorization;
  - validates workspace before stepper actions;
  - one action -> one observation;
  - zero blind motion retries;
  - invalidates HOME after uncertain physical execution.
- Added a physical homing upgrade plan:
  - one repeatable switch for X/Y/Z;
  - target articulated-arm homing order Z/Height -> Y/Reach -> X/Base;
  - do not blindly enable stock Grbl homing, which homes Z then X+Y together by default.
- Hardened the local motion website against cross-origin browser control with same-origin checks and a required custom control header.
- Automatic pick/place is still intentionally disabled. The next physical work is to validate the gripper repair, run the guided hardware/setup flow, then commission physical homing.


---

## History Still To Recover
There are additional important Seizo dates between these milestones that have not yet been reconstructed. Add them only when there is enough evidence or a reliable memory of what happened.
