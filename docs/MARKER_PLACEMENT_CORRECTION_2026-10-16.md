# Seizo marker placement correction, 2026-10-16

Project owner: Vivaan Goel. This corrects the physical placement reference, not numerical calibration or executable motor settings.

## Evidence and corrected interpretation

Vivaan supplied a current overhead photo and a current side photo in the robotics conversation, after explaining that the second marker is closer to the main arm on the connection from the main-arm joint toward the claw joint. He also explicitly stated that the arm can extend much farther than the photographed pose.

The photos were visually inspected. They remain in the private conversation; no room photos or image metadata are republished here.

- Marker 10, printed TOOL / GRIPPER: visually located on the housing immediately behind the claw, at the wrist-camera/tool assembly. Do not equate the marker center with the claw tip or the tool-center point. Its attachment before versus after wrist roll and its rigid transform are not established by these still images.
- Marker 11, printed FOREARM: visually located toward the main-joint/base-side portion of the linkage running between the main-arm joint and the wrist/claw joint. Do not assume it is centered on that linkage, mounted at the claw tip, or located exactly at either pivot center. In the side photo it is the right-hand card; in the overhead photo it is the card closer to the motor/base assembly.
- The paper and viewing angle obscure the precise fastening surface. Earlier descriptions of a particular left/right bar are historical, not sufficient evidence for an exact rigid-body assignment. Link ownership, marker-to-link rotation and translation, and marker-to-joint offsets remain unmeasured. No numeric offset, axis direction, marker size or pose transform is inferred from the photographs.

This correction supersedes any previous illustrative mid-link placement or exact joint-center assumption. Keep marker numbers 10 and 11 unchanged. Vivaan does not need to peel off, move, reprint or relabel either marker for this reference correction.

## Reach and photographed pose

The owner explicitly says the arm can extend farther. The shown configuration is one pose, NOT a maximum-reach measurement or a travel-limit calibration. Do not derive link lengths, hard stops, safe joint ranges or maximum reach from the marker spacing or apparent extension in either image. Mechanical reach and commissioned safe workspace are distinct.

Measured physical maximum reach: unknown.
Measured safe joint limits from these photos: unavailable.
Physical marker calibration: unavailable.
Physical movement authorized by these photos: no.

Do not shorten the modeled or physical arm merely to match this pose. Do not enlarge existing numerical travel limits on the strength of the qualitative reach statement. Any later range correction needs measured geometry and separately checked clearance; no forced full-extension demonstration is requested here.

## Actual software effect of this correction

This is a documentation-only correction published on the existing seizo-desktop branch. Application code, desktop_manifest.json, saved checkpoints, PPO observation/action definitions, simulation geometry, numeric ranges, and the physical SeizoOfficial repository are unchanged.

The published v11 proposal path was read at commit f9031756078cbe492bbd091d9eab7dd37496019c. In patches/core/proposal_policy.py, infer_saved_decision uses ViewWorld rendered overhead/wrist input; it does not load either of these real photographs or a physical marker-to-joint transform. Therefore there is no live marker offset in that path to numerically adjust. Do not claim this note recalibrates the Pi, relocates a marker in a rendered scene, establishes real-world task skill, or changes the arm's range.

The v11 application remains a no-motion proposal bridge. No motors were commanded, no camera/serial/GPIO device was opened, and no training was reset by this change. No restart or reinstallation is needed for a documentation-only update. Before a future physical pose estimator uses marker 11, it must use the corrected placement reference and a measured, validated mounting transform rather than an assumed midpoint.
