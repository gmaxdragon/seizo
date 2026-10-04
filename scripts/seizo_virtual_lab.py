#!/usr/bin/env python3
"""Run the complete software-only Seizo virtual lab in the terminal."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from seizo_core.virtual_seizo import deterministic_scenarios, randomized_stress

OUT=Path.home()/".cache/seizo/virtual_lab_latest.json"


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episodes",type=int,default=1500)
    args=ap.parse_args()

    print()
    print("==============================================")
    print("          SEIZO VIRTUAL LAB")
    print("==============================================")
    print("SOFTWARE SIMULATION ONLY")
    print("Hardware access: NONE")
    print("Arm movement requested: NO")
    print("GRBL / Nano / GPIO / servos: NOT OPENED")
    print()

    start=time.monotonic()
    scenarios=deterministic_scenarios()
    print("Deterministic scenarios")
    print("-----------------------")
    for s in scenarios:
        print(("[PASS] " if s.passed else "[FAIL] ")+s.name+"  ("+s.detail+")")

    print()
    print(f"Randomized stress: {args.episodes} episodes")
    print("--------------------------------")
    stress=randomized_stress(args.episodes)
    print(f"Passed: {stress['passed']}/{stress['episodes']}")
    print(f"Safe fault aborts observed: {stress['safe_aborts']}")
    if stress["failures"]:
        for f in stress["failures"][:5]:
            print("[FAIL] episode",f)
    else:
        print("[PASS] no invariant failures")

    sources=[(ROOT/"seizo_core/virtual_seizo.py").read_text(),(ROOT/"seizo_core/sensor_fusion.py").read_text()]
    imported=set()
    for source in sources:
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    forbidden_imports=sorted(imported & {"serial","RPi","gpiozero","requests","urllib","socket"})
    forbidden_paths=[token for token in ("/dev/tty","/dev/gpiochip","/sys/class/gpio") if any(token in source for source in sources)]
    forbidden_hits=forbidden_imports+forbidden_paths
    isolation_ok=not forbidden_hits
    print()
    print("Hardware-isolation scan")
    print("-----------------------")
    print("[PASS] simulator contains no hardware I/O paths" if isolation_ok else "[FAIL] forbidden tokens: "+", ".join(forbidden_hits))

    all_scenarios=all(x.passed for x in scenarios)
    overall=all_scenarios and stress["passed"]==stress["episodes"] and isolation_ok
    elapsed=time.monotonic()-start
    payload={
        "schema":"seizo-virtual-lab/v1",
        "timestamp_unix":time.time(),
        "episodes":stress["episodes"],
        "deterministic":[s.__dict__ for s in scenarios],
        "stress":stress,
        "hardware_isolation_pass":isolation_ok,
        "forbidden_hits":forbidden_hits,
        "physical_motion_requested":False,
        "hardware_interfaces_opened":False,
        "elapsed_s":round(elapsed,3),
        "outcome":"pass" if overall else "fail",
        "limitations":[
            "software/logic simulation, not a measured physical twin",
            "mechanical stiffness, backlash, gear wear and real sensor geometry require later physical validation",
            "ultrasonic thresholds remain provisional until the mounted orientation is measured",
            "camera calibration accuracy requires the printed targets and final mount",
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    tmp.replace(OUT)

    print()
    print("==============================================")
    print("FINAL RESULT:", "PASS" if overall else "FAIL")
    print("==============================================")
    print("Report:",OUT)
    if overall:
        print("No manual testing is needed for this software-simulation stage.")
    else:
        print("Send the FAIL output to ChatGPT; do not troubleshoot manually.")
    print()
    return 0 if overall else 1


if __name__=="__main__":
    raise SystemExit(main())
