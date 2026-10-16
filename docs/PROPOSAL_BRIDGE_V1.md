# Seizo proposal bridge: development validation

Date: October 15, 2026 (Pacific). Project owner: Vivaan Goel.

This extends the existing desktop Seizo application. It does not replace the simulator, connect a real Raspberry Pi, or enable physical motion.

## Source and delivery

- Development branch: `seizo-proposal-bridge-20261015` in `gmaxdragon/seizo`.
- Application identity: `seizo-proposal-bridge-dev-v1`.
- Stable baseline remains `91984ba805aed628829b96d2bf85b58634917388`, manifest `2026.10.15-run-controls-v10`.
- Tested source commit: `e885763a4f4506f01aba167b31939951c4b6ec1e`. The workflow applied and SHA256-checked the six existing-file integration changes before testing, then committed those exact files on this development branch as `48ac97e171b06617086e4fb163c16c5e8c556b77`.
- Dedicated validation: https://github.com/gmaxdragon/seizo/actions/runs/38852686062
- No physical `SeizoOfficial/main`, HAT, firmware, GPIO, serial, PEAC or Railway changes.
- The stable desktop manifest and existing `START_SEIZO.bat` are unchanged. Reopening that launcher still loads the stable release, not this development build. No new application ZIP workflow is introduced.

## Implemented flow

Explicit user click -> one text-only Hack Club task interpretation -> read-only loading of the original v9 camera PPO checkpoint -> original observation encoder and policy inference on freshly rendered overhead and wrist images -> strict proposal validation -> authenticated loopback HTTP mock-Pi receipt -> existing UI result.

The bridge proposes **one bounded decision**. It does not execute a simulated trajectory, complete a pickup, or replay a policy on hardware. It uses an initial scene from the existing simulator, not the live room. Known object selection happens before inference and never searches for a successful action. Custom destinations, distances and orientations are not supported by this initial intent interface.

The existing model is `seizo-detailed-view-curriculum-v9`. The adapter reads `policy.npz` through the original loader, checks its matching camera configuration, and refuses missing, corrupt, untrained, incompatible, unsaved or changed checkpoints. The bridge does not create a replacement checkpoint. Tests compare checkpoint bytes, model output, optimizer arrays and random-generator state.

Original controls are base, shoulder, forearm, wrist and gripper. Requested simulator deltas retain the existing scales 3, 3, 3, 7 and 0.16. The first four units are explicitly simulation degrees; the gripper unit is opening fraction. These are not calibrated physical coordinates, GRBL millimeters or servo pulses.

## Validation and cancellation

The versioned protocol allowlists fields, tasks, targets, action mappings, units, identities and timestamps. It rejects prose, partial JSON, duplicate keys, nonfinite or invalid numbers, AI-provided approval, unknown fields, stale frames, expired requests, mismatched identities and out-of-range actions. Provider replies must be complete, contain one choice and contain no tool calls.

Each mock session has a fresh random authentication secret and session ID. Requests and receipts are authenticated and bound to proposal IDs and body hashes. IDs are single-use. There is no persisted queue, automatic retransmission or automatic resume. Connection loss latches cancellation. Browser heartbeat ownership is held only in page memory; reload does not adopt or resubmit a prior job.

STOP sets cancellation before waiting for the model, renderer or provider. This STOP belongs to the desktop prototype. It neither controls the physical arm nor replaces its hardware emergency stop.

Only simulation-domain receipts are supported. Every receipt retains `automatic_motion_enabled=false`, `authorized=false`, `executed=false` and `physically_verified=false`. There is no execution endpoint or physical-controller import. This is a tested no-device software path, not an operating-system sandbox or safety certification.

## Evaluation evidence

The UI shows checkpoint identity and frozen task results. Newly completed evaluations include a runtime fingerprint covering physics, observation and policy code, relevant assets, camera settings and dependency versions. Old reports without that fingerprint remain intact but cannot silently qualify as current bridge evidence.

Mock delivery requires a matching frozen two-camera task evaluation with at least 20 clean trials, at least 70 percent success and more successes than the paired random baseline. This development admission rule is not a guarantee, independent replication, physical safety threshold or sim-to-real certification. Unproven policies may display their proposed decision, but the bridge refuses delivery and displays the evaluation blocker.

## Executed tests

| Check | Observed result |
| --- | --- |
| Linux full application regression | 214 run, 213 passed, one Windows-only skip; 121.468 seconds |
| Windows proposal suite | 57 run, 56 passed, one MuJoCo camera-test skip; 21.057 seconds |
| Windows credential storage | 17 run, 16 passed, one non-Windows skip; 0.329 seconds |
| Local proposal suite | 57 run, 56 passed, one MuJoCo-unavailable skip; 15.287 seconds |
| Actual Chromium/WebGL integration | Passed with original saved-policy inference, rendered RGB and real loopback HTTP |
| Browser STOP while mock provider blocked | Acknowledged in 0.054274 seconds on the CI runner, before releasing the provider |
| Checkpoint preservation | Original bytes unchanged; missing checkpoint prevented provider call |
| Reload | Did not resubmit instruction |
| JavaScript errors | None observed |
| Live cloud requests | Zero |
| Bridge simulator steps / physical actions | Zero / zero |

Accepted-path tests deliberately use **synthetic passing-score fixtures**. Test checkpoints receive a genuine numerical PPO update on synthetic observations. Those fixtures exercise integration, not useful learned skill. The actual-camera test uses the original renderer, encoder, saved-policy inference and HTTP receiver. Cloud intent is mocked in integration tests; provider parsing is separately tested through synthetic HTTPS responses. The screenshot's 16/20 and 1/20 numbers are test fixtures, not the user's results.

Linux used MuJoCo 3.3.7 and software OpenGL. Windows tested protocol, checkpoint, HTTP and credentials without MuJoCo; this is not native Windows graphics validation. The actual browser screenshot and JSON evidence were downloaded and inspected. Sixteen relevant source/test files in the returned artifact matched the local tested files byte-for-byte.

Initial CI failures were corrected: missing graphics library, an unpinned newer MuJoCo, Windows line-ending conversion and a stale runner integrity hash. Assertions were not weakened. The final dedicated workflow passed. Unrelated legacy repository-wide CI is outside this validation; not all repository workflows are claimed green.

Artifacts for run 38852686062: `seizo-proposal-runtime-source` (12026028065), `seizo-proposal-windows-tests` (12025793445), seven-day retention. Copies of final logs, evidence JSON, screenshot and a fuller report were also retained in the conversation files.

## Remaining boundaries

The user's current laptop checkpoint, actual task performance, live Hack Club key, real cameras and Pi were not inspected. A successful API reply or test suite cannot substitute for evaluating that checkpoint. Desktop promotion remains a separate release step; this branch does not update the stable launcher channel.

Future physical commissioning must separately verify mechanics, servo signals, repeatable measured reference, calibrated joint and tool limits, camera geometry, workspace, payload and an independent reachable tested hardware emergency stop. Require explicit local authorization, one action followed by independent observation, no blind retry, invalidation of uncertain pose and no restart/reconnect replay. No AI-generated field may bypass those gates.

## Changed source map

- `core/proposal_protocol.py`: schemas, bounds, identities, freshness and replay protection.
- `core/proposal_receiver.py`: authenticated loopback receipt-only HTTP.
- `core/proposal_policy.py`: original checkpoint, evaluation/runtime binding and camera inference.
- `core/proposal_bridge.py`: explicit lifecycle, STOP and delivery.
- `core/cloud.py`: strict intent parsing through the existing provider/key path.
- `app.py`, `web/proposal_ui.js`, `web/app.js`, `web/index.html`: authenticated routes and existing UI integration.
- `core/runner.py`: runtime fingerprint on freshly completed evaluations, not a new learning algorithm.
- `tests/test_proposal*.py`, `tests/browser_proposal_bridge.py`: rejection, preservation, camera, transport and browser tests.
- `.github/workflows/proposal-bridge.yml`: development-only validation, not physical or stable deployment.
