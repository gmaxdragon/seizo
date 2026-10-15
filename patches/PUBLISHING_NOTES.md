# Seizo v9: detailed simulated views and bounded exploratory learning

The current release is 2026.10.15-views-exploration-v9. Use the existing START_SEIZO.bat.
The runtime is simulation only. No physical motor interface or automatic cloud request.

The learner starts with random weights in data/camera_views_v9. Previous state and
camera checkpoints are preserved, not relabeled as trained on the new observations.
Both actor and critic see current and previous RGB from wrist, overhead and optional
side/front helpers, plus known task instructions and previous requested actions.
There is no hidden joint/object position, camera pose, depth or contact input.
The 384x288 visual renders use the shipped detailed arm meshes and procedural room
materials; they are not real Pi frames, photographs, or calibrated camera geometry.
Each neural camera image is average-pooled to 48x36 for CPU processing.

Automatic view stages start with helpers, then fade them, then restrict to two.
Transitions need two qualifying held-out checks using only wrist and overhead,
20 trials per check, at least 70 percent success and no invalid-physics results.
All scored evaluation runs use only those two mounted views, even during helper
practice. A lesson name, completed counter or optimizer update is not mastery.

A temporary discovery reward requires new actual movement/roll/opening cells.
Repeated cells within an attempt get no new credit. The bonus is capped at 0.5
per attempt and fades away by 500 completed episodes. Invalid states get no bonus.
Rewards may use simulator state; that state is never fed to the neural policy.
No scripted reaching/pickup teacher or pretrained solution is included.

Safety guards, estimated 7 mm tabs, coupled gripper and longitudinal roll remain.
Visual meshes do not turn the provisional physics into a measured hardware twin.

Release validation uses the dedicated Views v9 workflow, including native Windows
software OpenGL, Linux EGL, core/regression tests and a real browser workflow.
The browser checks four images, focus switching, helper masking, training, STOP/save,
reloading and cancellation of a scored evaluation. It does not claim that a full
seven-task skill suite succeeded. Short network-update tests are not evidence of
useful reaching, gripping or deployment readiness. Actual laptop/GPU and real robot
performance remain unverified. Existing legacy repository CI is a separate workflow.
