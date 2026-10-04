"""Seizo session-referenced software workspace limits.

Because the current arm has no homing switches or encoders, these limits are
relative to an operator-established physical HOME/reference for the current
session. They are not GRBL machine-coordinate soft limits.
"""
from __future__ import annotations

import json
from pathlib import Path

AXES=("X","Y","Z")
SCHEMA="seizo-workspace-limits/v1"


class WorkspaceLimitError(RuntimeError):
    pass


class WorkspaceGuard:
    def __init__(self, path: Path):
        self.path=Path(path)
        self.reference_valid=False
        self.calibrating=False
        self.position={a:0.0 for a in AXES}
        self.config={
            "schema":SCHEMA,
            "limits":{a:{"min":None,"max":None} for a in AXES},
        }
        self.load()

    def load(self):
        try:
            raw=json.loads(self.path.read_text())
            if raw.get("schema")!=SCHEMA:
                return
            limits=raw.get("limits",{})
            clean={a:{"min":None,"max":None} for a in AXES}
            for a in AXES:
                item=limits.get(a,{})
                for k in ("min","max"):
                    v=item.get(k)
                    clean[a][k]=None if v is None else float(v)
            self.config={"schema":SCHEMA,"limits":clean}
        except Exception:
            pass

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_name(self.path.name+".tmp")
        tmp.write_text(json.dumps(self.config,indent=2,sort_keys=True)+"\n")
        tmp.replace(self.path)

    def set_reference_here(self):
        self.position={a:0.0 for a in AXES}
        self.reference_valid=True
        self.calibrating=False

    def clear_reference(self):
        self.reference_valid=False
        self.calibrating=False
        self.position={a:0.0 for a in AXES}

    def start_calibration(self):
        if not self.reference_valid:
            raise WorkspaceLimitError("Set HOME/reference first.")
        self.calibrating=True

    def cancel_calibration(self):
        self.calibrating=False

    def set_limit_here(self,axis,bound):
        axis=str(axis).upper(); bound=str(bound).lower()
        if axis not in AXES or bound not in ("min","max"):
            raise WorkspaceLimitError("Invalid axis/bound.")
        if not self.reference_valid or not self.calibrating:
            raise WorkspaceLimitError("Start limit calibration first.")
        self.config["limits"][axis][bound]=round(float(self.position[axis]),6)
        self.save()

    def complete_calibration(self):
        if not self.reference_valid or not self.calibrating:
            raise WorkspaceLimitError("Calibration is not active.")
        for axis in AXES:
            lo=self.config["limits"][axis]["min"]
            hi=self.config["limits"][axis]["max"]
            if lo is None or hi is None:
                raise WorkspaceLimitError(f"{axis} min/max not both saved.")
            if not lo < hi:
                raise WorkspaceLimitError(f"{axis} min must be below max.")
            if not lo < 0.0 < hi:
                raise WorkspaceLimitError(f"HOME zero must lie strictly inside {axis} limits.")
        self.calibrating=False
        self.save()

    def clear_limits(self):
        self.config={"schema":SCHEMA,"limits":{a:{"min":None,"max":None} for a in AXES}}
        self.save()
        self.calibrating=False

    def configured(self):
        try:
            for axis in AXES:
                lo=self.config["limits"][axis]["min"]
                hi=self.config["limits"][axis]["max"]
                if lo is None or hi is None:
                    return False
                if not float(lo) < 0.0 < float(hi):
                    return False
            return True
        except Exception:
            return False

    def require_motion_ready(self):
        if not self.reference_valid:
            raise WorkspaceLimitError("Set HOME/reference before movement.")
        if not self.configured() and not self.calibrating:
            raise WorkspaceLimitError("Calibrate software travel limits before normal movement.")

    def predict(self,axis,physical_delta):
        axis=str(axis).upper()
        if axis not in AXES:
            raise WorkspaceLimitError("Unknown axis.")
        self.require_motion_ready()
        nxt=float(self.position[axis])+float(physical_delta)
        if self.calibrating:
            return nxt
        lo=float(self.config["limits"][axis]["min"])
        hi=float(self.config["limits"][axis]["max"])
        if nxt < lo-1e-9 or nxt > hi+1e-9:
            raise WorkspaceLimitError(
                f"{axis} move blocked by software limit: next={nxt:.3f}, safe=[{lo:.3f},{hi:.3f}]"
            )
        return nxt

    def commit(self,axis,physical_delta):
        axis=str(axis).upper()
        self.position[axis]=round(float(self.position[axis])+float(physical_delta),6)

    def preview_sequence(self,physical_moves):
        if not self.reference_valid:
            raise WorkspaceLimitError("Set HOME/reference before replay.")
        if not self.configured():
            raise WorkspaceLimitError("Software travel limits are not calibrated.")
        pos=dict(self.position)
        for axis,delta in physical_moves:
            axis=str(axis).upper()
            if axis not in AXES:
                raise WorkspaceLimitError("Unknown replay axis.")
            nxt=float(pos[axis])+float(delta)
            lo=float(self.config["limits"][axis]["min"])
            hi=float(self.config["limits"][axis]["max"])
            if nxt < lo-1e-9 or nxt > hi+1e-9:
                raise WorkspaceLimitError(
                    f"Replay blocked: {axis} would reach {nxt:.3f} outside [{lo:.3f},{hi:.3f}]"
                )
            pos[axis]=nxt
        return pos

    def snapshot(self):
        return {
            "reference_valid":self.reference_valid,
            "calibrating":self.calibrating,
            "configured":self.configured(),
            "position":dict(self.position),
            "limits":json.loads(json.dumps(self.config["limits"])),
        }
