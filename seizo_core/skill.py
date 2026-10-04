"""Seizo Skill v1.

All authoring modes compile into this deterministic representation.
Current v1 actions:
- bounded relative stepper movement
- bounded direct-GPIO servo setpoint movement
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "seizo-skill/v1"
MAX_ACTIONS = 200
MAX_DELTA_MM = 3.00
MAX_FEED_MM_MIN = 150.0

SERVO_RANGES = {
    "gripper": (1400, 1600),
    "wrist": (1400, 1600),
}


def _float(value, label):
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(label + " must be numeric.") from exc


def _int(value, label):
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(label + " must be an integer.") from exc


def validate_action(action: dict, index: int) -> dict:
    if not isinstance(action, dict):
        raise ValueError("Action " + str(index) + " is invalid.")

    kind = action.get("type")
    if kind == "relative_move":
        axis = str(action.get("axis", "")).upper()
        if axis not in {"X", "Y", "Z"}:
            raise ValueError("Action " + str(index) + " has invalid axis.")
        delta = _float(action.get("delta_mm"), "delta_mm")
        feed = _float(action.get("feed_mm_min"), "feed_mm_min")
        if not (0 < abs(delta) <= MAX_DELTA_MM):
            raise ValueError("Action " + str(index) + " exceeds stepper move bound.")
        if not (0 < feed <= MAX_FEED_MM_MIN):
            raise ValueError("Action " + str(index) + " exceeds feed bound.")
        return {
            "type": "relative_move",
            "axis": axis,
            "delta_mm": round(delta, 6),
            "feed_mm_min": round(feed, 3),
            "label": str(action.get("label", ""))[:24],
            "source_key": str(action.get("source_key", ""))[:1].lower(),
        }

    if kind == "servo_set":
        servo = str(action.get("servo", "")).lower()
        if servo not in SERVO_RANGES:
            raise ValueError("Action " + str(index) + " has invalid servo.")
        lo, hi = SERVO_RANGES[servo]
        from_us = _int(action.get("from_us"), "from_us")
        to_us = _int(action.get("to_us"), "to_us")
        if not lo <= from_us <= hi or not lo <= to_us <= hi:
            raise ValueError("Action " + str(index) + " servo pulse exceeds safe integration range.")
        if from_us == to_us:
            raise ValueError("Action " + str(index) + " servo action has no movement.")
        return {
            "type": "servo_set",
            "servo": servo,
            "from_us": from_us,
            "to_us": to_us,
            "label": str(action.get("label", ""))[:24],
            "source_key": str(action.get("source_key", ""))[:1].lower(),
        }

    raise ValueError("Action " + str(index) + " has unsupported type.")


def _metadata(value):
    if not isinstance(value, dict):
        return {}
    out={}
    inv=value.get("invert")
    if isinstance(inv, dict):
        clean={}
        for axis in ("X","Y","Z"):
            if axis in inv:
                clean[axis]=bool(inv[axis])
        if clean:
            out["invert"]=clean
    ref=value.get("workspace_reference")
    if ref is not None:
        out["workspace_reference"]=str(ref)[:80]
    start=value.get("start_position")
    if isinstance(start,dict):
        clean_start={}
        for axis in ("X","Y","Z"):
            if axis in start:
                try:
                    clean_start[axis]=round(float(start[axis]),6)
                except Exception:
                    pass
        if len(clean_start)==3:
            out["start_position"]=clean_start
    return out


def validate_skill(skill: dict) -> dict:
    if not isinstance(skill, dict) or skill.get("schema") != SCHEMA:
        raise ValueError("Unsupported Seizo Skill schema.")
    actions = skill.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise ValueError("Skill action count is invalid.")
    clean = [validate_action(action, i) for i, action in enumerate(actions)]
    return {
        "schema": SCHEMA,
        "name": str(skill.get("name", "recorded-skill"))[:80],
        "created_utc": str(skill.get("created_utc", ""))[:40],
        "source_mode": str(skill.get("source_mode", "unknown"))[:40],
        "metadata": _metadata(skill.get("metadata")),
        "actions": clean,
    }


def inverse_actions(actions: list[dict]) -> list[dict]:
    result = []
    for action in reversed(actions):
        valid = validate_action(action, 0)
        if valid["type"] == "relative_move":
            result.append({
                **valid,
                "delta_mm": -valid["delta_mm"],
                "label": "UNDO " + valid.get("label", ""),
                "source_key": "u",
            })
        else:
            result.append({
                **valid,
                "from_us": valid["to_us"],
                "to_us": valid["from_us"],
                "label": "UNDO " + valid.get("label", ""),
                "source_key": "u",
            })
    return result


def save_skill(path: Path, skill: dict) -> None:
    valid = validate_skill(skill)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(valid, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def load_skill(path: Path) -> dict:
    return validate_skill(json.loads(path.read_text()))
