#!/usr/bin/env python3
"""Read-only Seizo Nano servo-controller probe.

Safety:
- excludes the known GRBL Uno
- opens only candidate USB serial devices
- sends HELLO and PING only
- never attaches a servo output
- never sends GRIP/WRIST/OFF commands
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from seizo_core.nano_servos import BAUD, HANDSHAKE, _candidate_ports

CACHE=Path.home()/".cache"/"seizo"
OUT=CACHE/"nano_probe_latest.json"


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix="nano-probe-",suffix=".json",dir=path.parent)
    try:
        with os.fdopen(fd,"w") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(payload,f,indent=2,sort_keys=True)
            f.write("\n");f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def main():
    payload={
        "schema":"seizo-nano-readonly-probe/v1",
        "timestamp_utc":utc(),
        "physical_motion_requested":False,
        "servo_output_commands_sent":0,
        "candidates":[],
        "outcome":"fail",
    }
    try:
        import serial
    except Exception as exc:
        payload["error"]="pyserial unavailable: "+str(exc)
        atomic_json(OUT,payload)
        return 2

    ports=list(_candidate_ports())
    payload["candidate_ports"]=ports
    for port in ports:
        item={"port":port,"handshake":False,"ping":False,"raw":[]}
        ser=None
        try:
            ser=serial.Serial(port,BAUD,timeout=.2,write_timeout=.5)
            time.sleep(1.8)
            ser.reset_input_buffer()
            ser.write(b"HELLO\n");ser.flush()
            end=time.monotonic()+1.2
            while time.monotonic()<end:
                line=ser.readline().decode("ascii",errors="replace").strip()
                if line:
                    item["raw"].append(line[:160])
                if line==HANDSHAKE:
                    item["handshake"]=True
                    break
            if item["handshake"]:
                ser.reset_input_buffer()
                ser.write(b"PING\n");ser.flush()
                end=time.monotonic()+1.0
                while time.monotonic()<end:
                    line=ser.readline().decode("ascii",errors="replace").strip()
                    if line:
                        item["raw"].append(line[:160])
                    if line=="PONG":
                        item["ping"]=True
                        break
        except Exception as exc:
            item["error"]=type(exc).__name__+": "+str(exc)
        finally:
            if ser is not None:
                try: ser.close()
                except Exception: pass
        payload["candidates"].append(item)

    good=[x for x in payload["candidates"] if x.get("handshake") and x.get("ping")]
    if len(good)==1:
        payload["outcome"]="pass"
        payload["verified_port"]=good[0]["port"]
        payload["firmware"]=HANDSHAKE
    elif len(good)>1:
        payload["error"]="Multiple Seizo Nano controllers answered."
    elif not ports:
        payload["error"]="No non-GRBL serial candidate is present."
    else:
        payload["error"]="Nano USB serial exists but Seizo HELLO/PING did not verify."

    atomic_json(OUT,payload)
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0 if payload["outcome"]=="pass" else 3


if __name__=="__main__":
    raise SystemExit(main())
