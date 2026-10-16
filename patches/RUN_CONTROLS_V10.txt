CURRENT RELEASE: 2026.10.15-proposal-bridge-v11
See START_HERE.txt. REAL ARM LOCKED.

SEIZO RUN CONTROLS v10
Build: seizo-run-controls-v10
Use your existing START_SEIZO.bat. No replacement folder, reset, or new API key.
End the old run, wait for saving, close its terminal and reopen that same starter.

ETA
The main page shows estimates for the selected training budget and full test.
They come from completed runs measured on this PC, with an empirical planning
range, not a promised completion time or an estimate of skill mastery. A first
run says Calibrating until enough real samples exist. Training, policy tests,
random baselines and injected-fault trials are counted separately. Render speed,
view mix, curriculum changes and other running programs can change the estimate.

END RUN & SAVE
The button immediately requests cancellation and stops displayed playback.
The current physics/render/update operation must finish safely, then saving is
verified. This is not an OS process kill. The tab and server stay open. Existing
weights, optimizer, RNG, remaining episode target and settings are preserved.
Resume uses the remaining budget when episodes/task settings are unchanged.
Changing the episode budget or task starts an additional run using existing
weights; it does not erase learned parameters. The partial rollout is not a
promise to restore the exact paused physical scene. Wait for Saved and verified.

BACKGROUND
Hide live previews to reduce browser rendering. Training still requires its two
or four input-camera renders. The browser may be minimized or closed, but the
Python terminal must remain open and the computer awake. No cloud work is
started. The opt-in Windows keep-awake option applies only while plugged in and
working. It lets the display turn off, never edits the power plan, releases after
the run, and cannot override shutdown, manual sleep or lid policies.

CAMERAS
Workspace framing makes objects larger in the overhead view. A configurable
estimated wrist-lens height reduces obstruction by the housing. Full/wide
framing remains available. These are estimated camera positions, not a measured
match or photorealistic view of the real room. The neural input size and v9 policy
ID are unchanged. Earlier results with different camera settings are stale.

No Pi, live camera, motor, PEAC or Railway change. Saved API-key storage unchanged.
