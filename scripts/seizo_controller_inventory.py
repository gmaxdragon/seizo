#!/usr/bin/env python3
"""Enumerate Seizo serial controllers using USB metadata only.

Safety:
- never opens a serial port
- never writes USB serial data
- never touches GPIO
- never commands motors or servos
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seizo_core.controller_inventory import classify_props

CACHE = Path.home() / ".cache" / "seizo"
OUT = CACHE / "controller_inventory_latest.json"


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def udev(path):
    try:
        p = subprocess.run(
            ["udevadm", "info", "--query=property", "--name", path],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except Exception:
        return {}
    props = {}
    if p.returncode == 0:
        for line in p.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                props[key] = value
    return props


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="controller-inventory-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def main():
    ports = sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")))
    devices = []
    for port in ports:
        props = udev(port)
        identity = classify_props(props)
        devices.append({
            "port": port,
            **identity,
            "manufacturer": str(props.get("ID_VENDOR_FROM_DATABASE") or props.get("ID_VENDOR") or "")[:120],
            "model": str(props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL") or "")[:120],
        })

    by_role = {}
    for item in devices:
        by_role.setdefault(item["role"], []).append(item["port"])

    payload = {
        "schema": "seizo-controller-inventory/v1",
        "timestamp_utc": utc(),
        "outcome": "pass",
        "devices": devices,
        "roles": by_role,
        "nano_serial_probe_scope": list(by_role.get("nano_candidate", [])),
        "esp32_serial_probe_allowed": False,
        "physical_motion_requested": False,
        "serial_ports_opened": 0,
        "serial_writes_sent": 0,
        "hardware_actuator_interfaces_opened": False,
        "motor_commands_sent": 0,
        "servo_commands_sent": 0,
    }
    atomic_json(OUT, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
