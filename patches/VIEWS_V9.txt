SEIZO: DETAILED CAMERA VIEWS AND EXPLORATION v9
Release: 2026.10.15-views-exploration-v9
Screen: seizo-detailed-views-v9

Use the SAME START_SEIZO.bat. No new folder, app or API key.
STOP & save, wait for verified saving and idle, close the terminal and reopen it.

Leave Training views on Automatic and Task on Automatic lessons. Train / resume
starts a random-initialized PPO network. It samples its own bounded actions,
receives task rewards and a small early bonus for new actual movement. Repeated
poses receive no repeated bonus within an attempt. The discovery bonus is capped
at +0.5 per attempt and fades to zero by episode 500. The task reward remains.

Initially the learner can see overhead, wrist, side and front RGB views. Some
unassisted attempts are included early to avoid dependence on the extra views.
Helper views become less frequent, then disappear, only after two successive
held-out 20-trial checks with >=70% success and no invalid-physics trials. Time or
update counters do not certify a skill. Failure leaves the phase unchanged.

Test all tasks ALWAYS masks side and front views. It scores using wrist and
overhead only, without updating weights or adding the discovery bonus. Camera
focus buttons only enlarge a picture for you; they do not secretly change inputs.
Watch policy uses the selected practice-view condition and does not update weights.

The four views render the detailed arm meshes with shadows and procedural
floor/mat materials. Camera positions are estimates informed by the existing
setup, not measured intrinsics or real Pi frames. The wrist camera remains
selectable before the roll joint or on the rolling hand. The main third-person
viewer is not another neural input. The actor and critic receive RGB, task
instructions, prior requested actions and camera validity, not exact body poses.
Views are 384x288, pooled to 48x36 per camera for the CPU network.

Earlier state and v8 camera checkpoints are not deleted or renamed as trained
for this new input space. New progress is in data/camera_views_v9; STOP & save
also preserves the view curriculum and verifies reloading. Saved Windows keys
are unchanged. Training/testing make zero cloud API calls. Nothing auto-starts.

Two tool servos only: full simulated shaft roll and coupled jaw opening. Main
arm physics, jaw contacts and table/penetration rejection remain in place. The
higher-detail visual meshes are not calibrated physical collision geometry.
No Pi, GPIO, serial, robot control, PEAC or Railway changes are included. Real
hardware testing requires measured limits, camera calibration and local safeguards.
