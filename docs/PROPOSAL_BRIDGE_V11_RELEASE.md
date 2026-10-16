# Seizo v11: stable desktop proposal release

Owner: Vivaan Goel. Request: publish tested desktop updates through the existing launcher, not leave them only on development branches. Release approval does not authorize robot movement.

## Scope

Release `2026.10.15-proposal-bridge-v11`, app `seizo-proposal-bridge-v11`. Keep `START_SEIZO.bat`, `seizo-desktop`, and the original `data/camera_views_v9` checkpoint identity. No checkpoint upload is required simply to install this no-motion release.

REAL ARM LOCKED is visible. The app still proposes one simulator decision and can deliver a receipt to a loopback mock Pi. It cannot drive motors. Even perfect simulated scores, AI approval claims or an environment flag cannot enable physical motion.

## Existing launcher compatibility

The original Library installer `Seizo_Install_Once_AutoUpdates.zip`, version 3, contains a batch file that runs its local seizo_updater.py. That exact updater has Git blob 38324420ca3000331a906bbef78a45ab6fe35c83. It does not replace itself on launch. Its original asset allowlist rejects the gzip/PNG entries already present in v10.

Changing only GitHub's root updater would not fix installed copies. v11 therefore distributes the three unchanged geometry/texture binaries losslessly inside a checksummed JSON envelope, which the original updater accepts. A bounded standard-library decoder reconstructs only those three fixed non-executable asset paths before renderer import. It validates all sizes, checksums and file signatures before writing and rejects symbolic-link destinations. Existing renderer inputs remain byte-identical. The original 80-file manifest limit is retained. No new launcher or manual file replacement is needed.

The root updater also receives a narrow allowlist repair for those exact assets. Release tests must exercise the original unmodified updater as well as the patched copy, reconstruct the original assets, reject corrupt envelopes, and preserve saved data byte-for-byte.

## Evidence boundaries

Cloud replies, weight updates, simulated movement and mock receipts are not real-arm validation. Accepted-path integration tests use synthetic score fixtures and mocked intent while exercising actual saved-policy loading, rendered images and HTTP. They are not Vivaan's task scores.

Real movement requires a separate commissioning release: measured reference and limits, verified mechanics/servos, calibrated camera/arm geometry, workspace/payload limits, tested independent emergency stop and current local authorization. None is inferred from a chat statement. No SeizoOfficial/main, firmware, GPIO, serial, HAT, PEAC or Railway change is part of this update.

## Delivery preference

When an authorized Seizo desktop update is complete, release tested compatible no-motion software through the existing updater in the same task. Do not stop at a draft PR unless a failing check or compatibility problem blocks publication. Never publish failed tests or treat desktop release consent as physical-motion consent. Separate published code verification from what ran on the user's machine.

## Install

END RUN & SAVE. Wait for Saved. Close the old terminal. Reopen the existing START_SEIZO.bat with internet. Verify seizo-proposal-bridge-v11 and REAL ARM LOCKED. Open AI instruction to mock Pi (no motion).

Training and settings stay in place. Missing, incompatible or unproven inputs are blockers; do not reset the model to work around them.
