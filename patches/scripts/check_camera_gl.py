#!/usr/bin/env python3
"""Read-only MuJoCo RGB camera smoke check (no training or motor controls).

Run directly from the installed Seizo_Learn folder, in the same Python
environment used by START_SEIZO.bat. Never sends network calls or changes
saved PPO checkpoints.
"""
from __future__ import annotations
import json
import os
import platform
import sys
import threading


def main():
    result={"schema":"seizo-camera-gl-smoke/v1",
            "platform":platform.system(), "python":sys.version.split()[0],
            "main_thread":threading.current_thread() is threading.main_thread(),
            "backend":os.environ.get("MUJOCO_GL", "platform default"),
            "render_source":"detailed_simulated_cameras",
            "physical_motion_executed":False, "checkpoint_changed":False}
    world=None
    try:
        from core.view_world import ViewWorld
        from core.view_observation import WIDTH, HEIGHT
        import numpy as np
        import mujoco
        result["mujoco_version"]=getattr(mujoco,"__version__","unknown")
        if not result["main_thread"]:
            raise RuntimeError("Camera doctor must execute on the process main thread.")
        world=ViewWorld(n=1,seed=20261017,task="reach",
                        camera_config={"profile":"fixed"},view_mode="two")
        obs=world.observation()
        images=world._current[0,:2]
        expected_shape=(2,HEIGHT,WIDTH,3)
        if images.shape!=expected_shape or not np.isfinite(obs).all():
            raise RuntimeError("Rendered RGB tensor is invalid.")
        if any(float(np.std(image)) <= 5.0 for image in images):
            raise RuntimeError("Rendered RGB camera appears blank.")
        result["camera_names"]=["overhead","wrist"]
        result["image_shape"]=list(images.shape)
        result["image_standard_deviation"]=[float(np.std(im)) for im in images]
        result["ok"]=True
        result["advice"]="Camera framebuffer initialized; only a short controlled checkpoint-resume test can verify actual training."
    except Exception as error:
        result["ok"]=False
        result["error_type"]=type(error).__name__
        result["error"]=str(error)[:500]
        result["advice"]=(
            "On Windows, run this check in a local interactive desktop session "
            "with current Intel/NVIDIA/AMD OpenGL graphics drivers; do not use "
            "Remote Desktop, a headless agent, or a sleeping/locked graphics session. "
            "Do not set MUJOCO_GL=egl or osmesa on Windows. Do not reset PPO data."
        )
    finally:
        if world is not None:
            try:world.close()
            except Exception as error:
                result["ok"]=False
                result["cleanup_error"]=str(error)[:300]
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__=="__main__":
    raise SystemExit(main())
