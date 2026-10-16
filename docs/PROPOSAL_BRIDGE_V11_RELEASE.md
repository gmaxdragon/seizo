# Seizo v11: stable desktop proposal release

Owner: Vivaan Goel. Request: publish tested desktop updates through the existing launcher, not leave them only on development branches. Release approval does not authorize robot movement.

## Release scope

Publish the existing no-motion AI proposal bridge as `2026.10.15-proposal-bridge-v11`, app label `seizo-proposal-bridge-v11`. Keep `START_SEIZO.bat`, the stable `seizo-desktop` manifest channel and the original `data/camera_views_v9` checkpoint identity. No user checkpoint upload is required just to install this no-motion release.

The root source updater needs a narrow allowlist repair for the already published compressed camera geometry and the two room textures. Do not allow arbitrary new binary asset extensions. The release retains the original 80-file manifest limit.

The new visible banner says REAL ARM LOCKED. The app still only proposes one simulator decision and can deliver a receipt to a loopback mock Pi. It cannot drive physical motors. Even perfect simulated scores, AI claims of approval or an environment flag must not enable physical movement.

## Evidence boundaries

A successful cloud request, numerical weight update, simulated movement, or mock receipt is not real-arm validation. Accepted-path integration tests use synthetic score fixtures and mocked intent, while exercising actual saved-policy loading, rendered images and HTTP. These are not Vivaan's actual skill results.

Physical operation requires a separate hardware commissioning release: measured reference and limits, verified mechanics and servo signals, calibrated camera/arm geometry, workspace and payload limits, tested independent emergency stop and current local authorization. None is inferred from a chat statement. No physical runtime, SeizoOfficial/main, firmware, GPIO, serial, HAT, PEAC or Railway change is part of this update.

## Delivery preference for later work

When an authorized Seizo desktop update is complete, release the tested compatible no-motion software through the existing updater in the same task. Do not stop at a draft PR unless a specific failing check or compatibility problem blocks publication. Never silently publish failed tests or turn desktop release consent into physical-motion consent. Report the published version and actual verification separately from what ran on the user's machine.

## Install

END RUN & SAVE. Wait for Saved. Close the old Seizo terminal. Reopen the existing START_SEIZO.bat with internet. Verify `seizo-proposal-bridge-v11` and REAL ARM LOCKED. Open AI instruction to mock Pi (no motion).

Training data and settings stay in place. Missing, incompatible or unproven policy/evaluation inputs appear as blockers; do not reset the model to work around them.
