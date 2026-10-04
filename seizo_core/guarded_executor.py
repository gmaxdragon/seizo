"""Guarded Seizo automatic execution kernel.

This module has no hardware imports and no web route. Physical I/O must be
injected explicitly by a future caller. The live Seizo phone controller does
not use this module yet.

Rules:
- planning gate must already pass
- a separate execution authorization must be explicit
- workspace is checked before every stepper action
- actions execute once, never blind-retried
- observation/checkpoint runs after every physical action
- any failure stops the sequence immediately
"""
from __future__ import annotations

from .skill import validate_skill


class AutomaticExecutionBlocked(RuntimeError):
    pass


class GuardedExecutor:
    def __init__(self, workspace, move_stepper, move_servo, checkpoint,
                 stop_requested=lambda: False):
        self.workspace = workspace
        self.move_stepper = move_stepper
        self.move_servo = move_servo
        self.checkpoint = checkpoint
        self.stop_requested = stop_requested

    def execute(self, skill: dict, gate: dict, *, execution_authorized: bool = False) -> dict:
        valid = validate_skill(skill)
        if not isinstance(gate, dict) or not gate.get("ready_for_planning"):
            raise AutomaticExecutionBlocked("Automatic planning gate is not ready.")
        if gate.get("automatic_motion_enabled") is not True:
            raise AutomaticExecutionBlocked("Automatic physical motion remains disabled by the safety gate.")
        if not execution_authorized:
            raise AutomaticExecutionBlocked("Physical automatic execution is not authorized.")

        completed = []
        for index, action in enumerate(valid["actions"]):
            if self.stop_requested():
                raise AutomaticExecutionBlocked("STOP requested before action " + str(index) + ".")

            physical_started = False
            try:
                if action["type"] == "relative_move":
                    axis = action["axis"]
                    delta = action["delta_mm"]
                    self.workspace.predict(axis, delta)
                    physical_started = True
                    result = self.move_stepper(action)
                    self.workspace.commit(axis, delta)
                elif action["type"] == "servo_set":
                    physical_started = True
                    result = self.move_servo(action)
                else:
                    raise AutomaticExecutionBlocked("Unsupported action type.")

                if self.stop_requested():
                    raise AutomaticExecutionBlocked("STOP requested after action " + str(index) + ".")

                observation = self.checkpoint(action, result)
                if not isinstance(observation, dict) or observation.get("ok") is not True:
                    raise AutomaticExecutionBlocked(
                        "Observation failed after action " + str(index) + ". No retry was attempted."
                    )
            except Exception:
                if physical_started:
                    self.workspace.clear_reference()
                raise

            completed.append({
                "index": index,
                "type": action["type"],
                "label": action.get("label", ""),
                "observation": observation,
            })

        return {
            "schema": "seizo-guarded-execution/v1",
            "completed_actions": len(completed),
            "completed": completed,
            "physical_execution_authorized": True,
            "blind_motion_retries": 0,
            "final_position_mm": dict(self.workspace.position),
        }
