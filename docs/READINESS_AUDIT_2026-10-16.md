# Seizo AI and real-arm readiness audit

Checked October 16, 2026, Pacific time. Owner: Vivaan Goel. Requested target: tomorrow or the following day, October 17-18. A target date is not an execution permission or a promise that unverified hardware will be ready.

## Current result

**Not demonstrated ready for AI-controlled physical movement.** This is a specific evidence gap, not a conclusion that the arm cannot move manually or that future learning cannot work.

The physical robot, desktop simulator and Nexus CAD workstation remain separate. No motor, servo, GPIO, serial or homing command was sent during this audit. No Pi job was queued. No physical-controller code, geometry, offsets, motion limits or checkpoint was changed.

## Fresh software checks in this audit

Inspected `gmaxdragon/seizo`, `seizo-desktop`, at `af429dade76b9f89967ed062df3ea212f39135a5`, which still publishes v12. Reconstructed the Git tree of the returned v12 source package and verified it equals `b6d6d5abf8b747cc92c1cf009af555f72ec0856d`, the tree recorded in the current repository's release proof. Verified every packaged patch file used for tests matches those bytes.

Reran these checks against that source in an isolated working container:

| Check | Result observed now |
| --- | --- |
| Feedback, gradient direction, scoring and cancellation tests | 27 run, 22 passed, 5 skipped; 0.371 seconds |
| Proposal, checkpoint, authentication, replay and physical-lock tests | 70 run, 64 passed, 6 skipped; 15.110 seconds |

The five feedback skips require MuJoCo. The six proposal skips comprise one MuJoCo integration and five repository/original-updater tests that require release-CI context. MuJoCo is not installed in this local audit environment. These skips are not counted as passes, and this audit did not run a fresh camera-training experiment or claim live cloud connectivity. The previous full release CI evidence remains separate historical evidence.

The controlled numerical tests support that the implemented optimizer can change action probabilities in response to feedback. Protocol tests support rejection of malformed, replayed or unauthorized proposals. Neither establishes a useful reaching skill.

## Actual task evidence, not an update counter

Read the actual `Seizo_v12_Learning_Experiment.json` from the prior release evidence, not merely the summary report. It is a separate test policy, not Vivaan's laptop checkpoint:

- 192 real simulated training transitions, two completed episodes and twelve optimizer updates.
- Three full held-out reach trials: 0/3 successes before, 0/3 after, 0/3 for random actions.
- Guard-aborted trials increased from 0/3 to 3/3 after that short training run.
- The comparison explicitly says `small_sample_not_proof` and `more_guard_aborts_observed`.

This evidence must not be upgraded to real-arm readiness. The user's current saved `camera_views_v9/policy.npz` and matching current evaluation are still not available in this audit. A longer run may change results but has not been performed by this audit. The cloud task interpreter and local PPO control policy are different models; testing one does not validate the other.

## Pi telemetry: fetched now, but the contents are old

Read `gmaxdragon/SeizoOfficial`, branch `device-status`, `device_status_latest.json`. Its blob was `3c9a8ef4487f4900ae0bcc487512ba4a91cc0451`. The top-level timestamp is **2026-10-04T00:15:45+00:00**, which is October 3 at 5:15:45 PM Pacific. It is roughly thirteen days old at this audit.

The snapshot reports runtime commit `27987b5dfea4a2ca95a3705c0f9e4e294a1e8f74`, not the later current physical-repository main head known in this project. Its `arm_status` is null and X/Y/Z workspace min/max values are null. It reports camera `fresh` flags inside that old snapshot, but those are not fresh frames today. Stale telemetry does not prove that the Pi is offline or broken; it means its present state and deployment cannot be verified from this report.

Historical Pi AI repair data in that snapshot also distinguishes **0/21 pure local-LLM successes** from **21/21 hybrid results using deterministic fallback in all 21 cases**. Its recommended planner was the deterministic semantic planner. That is not proof that the language model learned arm control. This historical local Qwen result is distinct from the newer desktop Hack Club interpreter and PPO training.

## Physical evidence that still needs current confirmation

Read current physical `Hardware.md`. It continues to list missing home switches, unmeasured payload/reference, unresolved base/gear/coupling checks, and failed latest gripper/wrist tests. Prior user reports that the stepper axes worked are retained as user evidence; they do not establish repeatable calibrated pose, measured limits, reliable servo operation or absence of slip under load.

The project previously recorded no reachable physical kill switch during desk work. No newer test establishing a working independent stop was found. The two marker photos corrected the placement reference but did not measure marker-to-link transforms or establish safe travel limits. Longer apparent reach is not a calibrated workspace.

Before an initial AI-directed physical trial, the exact task needs current reference/limit calibration, fresh observation, reliable mechanics, a tested reachable independent physical emergency stop and explicit local operator authorization. A non-gripping task may exclude gripper use, but must keep failed or untested servos disabled; it still does not waive the other physical gates. The existing desktop proposal bridge is mock-Pi only and has no commissioned motor path.

## October 17-18 follow-up

Two read-only readiness checks were scheduled for the afternoons of October 17 and October 18, America/Los_Angeles. They inspect current connected repository evidence and report changes or blockers. They do not train continuously, control the Pi, release experimental motor code or guarantee movement by the deadline.

The first physical milestone should be one bounded, supervised, independently observed movement, not unattended picking or self-directed trial-and-error. That milestone remains conditional on the gates above. No automated task may interpret the calendar date, a passing JSON/schema check, old `fresh` flags or a simulated success percentage as permission to enable motors.

The immediate operator step is to make current read-only status available: Pi online, motor/servo power off, controller disarmed. Do not press ARM solely to produce a status screenshot. After a fresh heartbeat or current status screen is available, diagnose that exact current state rather than replaying stale commands or assuming the old servo failure persists unchanged.
