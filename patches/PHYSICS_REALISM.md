# Seizo v6: axial roll, real contact reporting and broader learning

Computer simulation only. The live robot repository and PEAC/Railway are not
modified by this release. The rendered arm remains the existing photo-based
reconstruction. The uploaded STL assembly has not been relabeled as measured CAD.

## Reproduced v5 errors

The old wrist used local Z yaw and +/-75 degree limits. A 75-degree command moved
the tool tip about 179 estimated mm instead of rolling the hand in place.
The old contact loop also labeled ordinary object/table contacts as arm contacts.
Those are software defects, not evidence that the user's robot is faulty.

## Joint and contact corrections

The new tool joint rolls around local X, from wrist toward fingertips. The tool
site lies on that axis. Roll can pass 360 in simulation; observations use periodic
angle information and commands remain small, rate bounded and force limited.
This does NOT certify continuous rotation, feedback or cable clearance on the
actual servo. There are still exactly five actuator controls: three main arm,
one tool roll, and one coupled jaw mechanism. Passive follower joints are not
extra motors. Gripper opening and tool roll remain separate controls.

MuJoCo rigid-body transforms drive the visual wrist and jaws. Contact reporting
requires an active solver contact with positive normal force and classifies the
actual geometry pair. Table/object, arm/object, jaw/object, arm/table and internal
contacts are not interchangeable. A continuing squeeze is reported only when
jaws actually touch an object and the requested opening remains smaller than the
measured simulated opening. Opposing jaws keep their existing collision surfaces.

The held-roll check PRE-POSITIONS a free block between the jaws, closes with
bounded force, turns it and releases it under gravity. The block has no weld.
The fixed-block squeeze check intentionally uses a fixture and labels it as such.
Neither is AI learning or proof of successful autonomous object acquisition.

## Seven task definitions, not seven mastered skills

Reach, roll/aperture positioning, push, grip/lift, lift/place, lift/rotate a held
object, and rotate/place. The cylinder is elongated so sideways/upright placement
is meaningful. Initial locations and orientations vary. For the last two tasks,
success checks actual object orientation, not just the commanded wrist angle.
Oriented placement also requires prior gripping/lifting, release and stable
contact with the support plane. Objects are never teleported into learned grasps.

The local neural PPO controller receives 67 normalized simulation-state features,
including object/goal rotation matrices. It starts with random weights, has dense
programmed rewards and samples its own actions. It is not learning from images.
Automatic lessons advance after repeated held-out validation and retain earlier
lessons. The lesson scheduler is programmed; the action policy learns.

Test all tasks freezes weights, uses fresh paired seeds for policy/random actions,
reports each task separately and gives a binomial uncertainty interval. Fault
injection is scored separately, not counted as successful manipulation. Hundreds
of successes in this environment would still not establish physical reliability.

## Cloud AI and experience

API tests and experience reviews are manual cloud requests, not PPO training.
After an evaluation, the app saves a compact experience.json tied to the exact
model and policy fingerprint. A manual cloud review sends that measured summary
and receives bounded task-selection advice. It does not execute advice, run code,
control motors, retrain hosted weights, upload cameras or make million-call loops.
The UI shows API request and token counters independently from network updates.
Credentials remain in the existing Windows account-bound vault.

## Remaining limits

Joint positions, torque limits, mass, friction, compliance, cable forces and the
full custom gripper mechanics remain uncalibrated. Collision shapes are still
simplified. The 360-degree simulation setting is not a real motor travel limit.
No passing diagnostic or learned-policy score unlocks physical motion. Keep the
robot's physical kill switch and local motion commissioning separate.

## Primary technical sources

MuJoCo joint axes, constraints and force-limited actuators:
https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html

Separate training and evaluation:
https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html

Hack Club API and permitted use:
https://docs.ai.hackclub.com/
https://docs.ai.hackclub.com/guide/rules.html
