"""Collect tested app bytes only, never checkpoints, credentials or camera photos."""
from pathlib import Path, PurePosixPath
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
app=ROOT/'Seizo_Learn';output=ROOT/'release-source'
old=json.loads((ROOT/'desktop_manifest.json').read_text())
names=set(old['patches'])|set(json.loads((ROOT/'views-v9-paths.json').read_text()))
# Supersede inherited release notes, which describe v8 rather than this candidate.
notes='''# Seizo v9: detailed simulated views and bounded exploratory learning

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
'''
for name in ('VALIDATION.md','PUBLISHING_NOTES.md'):(app/name).write_text(notes,encoding='utf-8');names.add(name)
hashes={}
for name in sorted(names):
    rel=PurePosixPath(name)
    assert not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] not in ('.git','.github','data'),name
    source=app/name;assert source.is_file(),name
    target=output/'patches'/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target);hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
(output/'hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
(output/'base.json').write_text(json.dumps(old['base'],indent=2)+'\n')
(app/'evidence'/'release_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
print('Packaged',len(hashes),'tested-source files and assets. No user data included.')
