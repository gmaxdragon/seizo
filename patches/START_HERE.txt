SEIZO: SIMULATED CAMERA LEARNING IN YOUR EXISTING UPDATER
Release: 2026.10.14-camera-learning-v8.1
Screen: seizo-camera-learning-v8.1

NO NEW FOLDER OR SECOND APP.
1. STOP & save your current run. Wait until saved and idle before closing its terminal.
2. Reopen your usual START_SEIZO.bat with internet to fetch the update.
3. The main page shows "AI input: simulated overhead + wrist cameras".
4. Train / resume updates the local neural network from the two rendered RGB views.
5. Watch policy and Test all tasks use the SAME camera-input network with frozen weights.
6. In Camera placement and variation choose Fixed, Nearby, or Wider setups.
   A setup stays fixed within an attempt and varies between attempts.
7. STOP & save waits for the current bounded operation, writes the policy/optimizer/
   counters/RNG, reload-verifies them, and then displays Saved and verified.

The two inputs are fake cameras rendered by the simulator. No real Pi feeds, device
camera permissions, Hack Club calls, or hidden joint/object coordinates are needed.
The human's third-person 3D viewer is NOT a policy input. The simulator may use
internal state for reward and a fixed rejection guard, never as neural observation.
Both actor and critic use current/previous RGB plus known task instructions and the
policy's own prior command. Fixed image averaging yields a compact CPU network.
The fake cameras show simplified physics geometry, not photorealistic room video.

Your earlier state-based training is kept under the same protected data folder.
New camera weights live in data/camera_pixels_v8. An old policy is NOT relabeled as
camera-trained. Camera-policy progress is saved and resumed from that same path.
Windows account-bound Hack Club key storage is unchanged. No credentials are in
this release. No PEAC, Railway, Raspberry Pi or physical controller was modified.

Default additional budget is 1,000 completed episodes, not a million tests. Nothing
starts automatically. Practising Roll names a current lesson, not verified mastery.
Only held-out evaluation results support improvement; an update count is not skill.
Learning/testing can take longer than the old privileged-state simulator because
images are rendered at every observation. No camera-policy mastery is claimed.

If RGB rendering fails, training reports the error and is blocked; it never silently
falls back to reading hidden simulator state. Hardware dimensions, camera placement,
gripper tabs, forces and table clearance remain uncalibrated estimates. This cannot
control the real arm, and virtual test success does not grant hardware authority.
