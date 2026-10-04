"""Pure automation readiness and no-motion planning for Seizo.

This module never opens serial, GPIO, camera devices, or actuator backends.
It only evaluates already-collected state and previews bounded skill motion
against the session-referenced software workspace.
"""
from __future__ import annotations

from .skill import validate_skill
from .workspace_limits import WorkspaceLimitError


def readiness(*, armed: bool, physical: dict, camera_overhead: bool,
              camera_wrist: bool, workspace: dict) -> dict:
    physical = physical if isinstance(physical, dict) else {}
    workspace = workspace if isinstance(workspace, dict) else {}
    components = ("base", "y", "z", "gripper", "wrist")
    hardware_pass = all(physical.get(name) == "pass" for name in components)
    cameras_live = bool(camera_overhead and camera_wrist)
    reference = bool(workspace.get("reference_valid"))
    limits = bool(workspace.get("configured"))
    calibrating = bool(workspace.get("calibrating"))

    blockers = []
    if not armed:
        blockers.append("ARM_MANUAL")
    if not hardware_pass:
        blockers.append("HARDWARE_TEST")
    if not cameras_live:
        blockers.append("TWO_CAMERAS")
    if not reference:
        blockers.append("HOME_REFERENCE")
    if not limits:
        blockers.append("TRAVEL_LIMITS")
    if calibrating:
        blockers.append("FINISH_LIMIT_CALIBRATION")

    if not armed:
        next_step = "ARM_MANUAL"
    elif not hardware_pass:
        next_step = "TEST_HARDWARE"
    elif not cameras_live:
        next_step = "CHECK_CAMERAS"
    elif not reference:
        next_step = "SET_HOME"
    elif not limits or calibrating:
        next_step = "CALIBRATE_LIMITS"
    else:
        next_step = "PLANNER_READY"

    return {
        "schema": "seizo-auto-readiness/v1",
        "hardware_pass": hardware_pass,
        "cameras_live": cameras_live,
        "home_reference_valid": reference,
        "travel_limits_configured": limits,
        "calibrating_limits": calibrating,
        "ready_for_planning": not blockers,
        "automatic_motion_enabled": False,
        "next_step": next_step,
        "blockers": blockers,
        "position_mm": workspace.get("position", {}),
        "limits_mm": workspace.get("limits", {}),
        "note": "Planning can be validated without enabling automatic physical motion.",
    }


def preview_skill(skill: dict, workspace_guard, gate: dict) -> dict:
    """Validate a Seizo Skill and workspace path without sending any command."""
    valid = validate_skill(skill)
    blockers = list((gate or {}).get("blockers", []))
    if blockers:
        return {
            "schema": "seizo-auto-preview/v1",
            "ready": False,
            "blockers": blockers,
            "actions": len(valid["actions"]),
            "physical_motion_executed": False,
            "automatic_motion_enabled": False,
        }

    moves = [
        (action["axis"], action["delta_mm"])
        for action in valid["actions"]
        if action["type"] == "relative_move"
    ]
    try:
        end = workspace_guard.preview_sequence(moves)
    except WorkspaceLimitError as exc:
        return {
            "schema": "seizo-auto-preview/v1",
            "ready": False,
            "blockers": ["WORKSPACE_PATH"],
            "error": str(exc),
            "actions": len(valid["actions"]),
            "physical_motion_executed": False,
            "automatic_motion_enabled": False,
        }

    return {
        "schema": "seizo-auto-preview/v1",
        "ready": True,
        "blockers": [],
        "actions": len(valid["actions"]),
        "relative_moves": len(moves),
        "predicted_end_position_mm": end,
        "physical_motion_executed": False,
        "automatic_motion_enabled": False,
    }
