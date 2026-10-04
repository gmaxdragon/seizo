"""Fast local semantic planner for Seizo.

This planner is deliberately small and deterministic. It converts only obvious
high-level user intents into the same semantic plan schema used by the LLM
planner. It never emits coordinates, G-code, motor values, servo values, GPIO,
or any other actuator-level command.

It is intended as the zero-cost, zero-network fast path and safety fallback.
"""
from __future__ import annotations

import re
from typing import Iterable

from seizo_core.ai_plan import SCHEMA, safety_preflight, validate_plan


PLANNER_ID="local/deterministic-semantic-v1"


def _text(value) -> str:
    return re.sub(r"[^a-z0-9]+"," ",str(value or "").lower()).strip()


def _aliases(entry: dict) -> list[str]:
    name=_text(entry.get("name","").replace("_"," "))
    aliases=[name] if name else []
    color=_text(entry.get("color",""))
    kind=_text(entry.get("kind",""))
    position=_text(entry.get("position",""))
    if color and kind:
        aliases.append(f"{color} {kind}")
    if position and kind:
        aliases.append(f"{position} {kind}")
    # Keep only meaningful multi-character phrases and preserve order.
    out=[]
    for alias in aliases:
        if len(alias)>=2 and alias not in out:
            out.append(alias)
    return out


def _phrase_present(text: str, phrase: str) -> bool:
    return re.search(r"(?:^|\s)"+re.escape(phrase)+r"(?:$|\s)",text) is not None


def _matches(goal: str, entries: Iterable[dict]) -> list[str]:
    text=_text(goal)
    found=[]
    for entry in entries:
        if not isinstance(entry,dict) or "name" not in entry:
            continue
        if any(_phrase_present(text,alias) for alias in _aliases(entry)):
            name=str(entry["name"])
            if name not in found:
                found.append(name)
    return found


def _hold(summary: str) -> dict:
    return {"schema":SCHEMA,"decision":"hold","summary":summary[:240],"steps":[]}


def plan_local(scene: dict, goal: str) -> dict:
    """Return a validated semantic plan using only explicit scene/goal facts."""
    if not isinstance(scene,dict):
        return _hold("invalid scene")

    blockers=safety_preflight(scene)
    if blockers:
        return _hold("safety hold: "+",".join(blockers))

    goal_text=_text(goal)
    if not goal_text:
        return _hold("empty goal")

    # An explicit stop/cancel request never becomes a new action.
    if re.search(r"(?:^|\s)(stop|cancel|halt|abort)(?:$|\s)",goal_text):
        return _hold("stop or cancel requested")

    objects=_matches(goal,scene.get("objects",[]))
    destinations=_matches(goal,scene.get("destinations",[]))

    # LOOK: only named, mutually-exclusive views are accepted.
    views=[view for view in ("forward","rear","center")
           if _phrase_present(goal_text,view) or _phrase_present(goal_text,view+" view")]
    if any(word in goal_text.split() for word in ("look","camera","view")) and views:
        views=list(dict.fromkeys(views))
        if len(views)==1:
            plan={
                "schema":SCHEMA,"decision":"execute","summary":"local look",
                "steps":[{"action":"look","object":"","destination":"","view":views[0]}],
            }
            return validate_plan(plan,scene)
        return _hold("ambiguous view")

    # INSPECT/CHECK requires exactly one explicitly named known object.
    inspect_words={"inspect","check","examine","observe"}
    if inspect_words.intersection(goal_text.split()):
        if len(objects)==1:
            plan={
                "schema":SCHEMA,"decision":"execute","summary":"local inspect",
                "steps":[{"action":"inspect","object":objects[0],"destination":"","view":""}],
            }
            return validate_plan(plan,scene)
        return _hold("inspect target ambiguous or unknown")

    # PICK/PLACE requires one known object and one known destination. Low-level
    # injection text elsewhere in the goal is ignored because this function
    # never maps it to an actuator-level field.
    motion_words={"move","put","place","pick","transfer"}
    if motion_words.intersection(goal_text.split()):
        if len(objects)==1 and len(destinations)==1:
            plan={
                "schema":SCHEMA,"decision":"execute","summary":"local pick place",
                "steps":[{
                    "action":"pick_place",
                    "object":objects[0],
                    "destination":destinations[0],
                    "view":"",
                }],
            }
            return validate_plan(plan,scene)
        return _hold("move target or destination ambiguous or unknown")

    return _hold("goal not confidently understood")
