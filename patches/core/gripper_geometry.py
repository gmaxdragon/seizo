"""Shared, explicitly provisional two-servo tool specification. Simulation only."""
from __future__ import annotations
import json, math
from pathlib import Path
SPEC=json.loads((Path(__file__).resolve().parents[1]/'web/assets/gripper.json').read_text())
MAX_ANGLE=float(SPEC['max_link_angle_rad'])

def jaw_shift(opening):
    """Fixed-length parallel-link displacement, relative to the CLOSED mesh."""
    a=max(0.,min(1.,float(opening)))*MAX_ANGLE
    x,y,_=SPEC['link']
    return (x*(math.cos(a)-1)-y*math.sin(a),x*math.sin(a)+y*(math.cos(a)-1))

def aperture_mm(opening):
    return 2*(SPEC['minimum_visual_half_gap']+jaw_shift(opening)[1])
