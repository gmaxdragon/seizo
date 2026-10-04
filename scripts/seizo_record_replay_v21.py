#!/usr/bin/env python3
"""Seizo 2.1 Record & Replay.

Record controls
---------------
W/S : Y +/-
A/D : base rotation R -/+ (GRBL X -/+)
Q/E : Z +/-
N/M : gripper OPEN/CLOSE
O/P : wrist -/+ one bounded step
U   : SAVE skill, execute exact inverse actions in reverse order, return to start, exit
ESC : SAVE skill in current pose and exit
SPACE: GRBL software feed hold, SAVE skill, exit

Replay executes the saved Seizo Skill from the same physical start pose.
The physical kill switch remains the emergency stop.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import termios
import time
import tty
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seizo_core.direct_servos import DirectServoController
from seizo_core.nano_servos import NanoServoController, NanoServoError
from seizo_core.grbl_compat import (
    controlled_incremental_move,
    require_manual_parser_state,
    software_hold,
    wait_idle,
)
from seizo_core.skill import SCHEMA, inverse_actions, load_skill, save_skill, validate_skill

CACHE = Path.home() / ".cache" / "seizo"
SKILL = CACHE / "skills" / "latest_recorded.json"
OUT = CACHE / "record_replay_v21_latest.json"

EXPECTED_SERIAL = "24333313131351101271"
EXPECTED_VID = "2341"
EXPECTED_PID = "0043"
BAUD = 115200

STEPPER_STEP_MM = {"X": 3.00, "Y": 3.00, "Z": 1.50}
STEPPER_FEED_MM_MIN = {"X": 90.0, "Y": 90.0, "Z": 60.0}
REPLAY_GAP_S = 0.20
QUIET_RELEASE_SECONDS = 0.18
SMOOTH_ACCEL_MM_S2 = {"X": 15.0, "Y": 15.0, "Z": 8.0}

STEPPER_KEYS = {
    "w": ("Y", +1, "Y+"),
    "s": ("Y", -1, "Y-"),
    "a": ("X", -1, "R-"),
    "d": ("X", +1, "R+"),
    "q": ("Z", +1, "Z+"),
    "e": ("Z", -1, "Z-"),
}

SERVO_KEYS = {
    "n": ("gripper", "open", "GRIP OPEN"),
    "m": ("gripper", "close", "GRIP CLOSE"),
    "o": ("wrist", -1, "WRIST-"),
    "p": ("wrist", +1, "WRIST+"),
}


class ManualOnlyMonitor:
    """No-camera adapter for manual Record & Replay testing.

    It implements the same interface as DualCameraMonitor so manual and
    camera-assisted modes exercise the same Record/Replay engine.
    """
    def require_live(self):
        return None

    def arm_baseline(self):
        return None

    def checkpoint(self, retries=3):
        return {
            "mode": "manual_only",
            "camera_verification": False,
            "prediction_retry_policy": "not_applicable",
        }

    def status(self):
        return {
            "mode": "manual_only",
            "camera_verification": False,
        }

    def close(self):
        return None


def make_servo_controller(backend):
    backend = str(backend).lower()
    if backend == "direct":
        return DirectServoController(), "direct"
    if backend == "nano":
        return NanoServoController(), "nano"
    if backend == "auto":
        try:
            return NanoServoController(), "nano"
        except Exception:
            return DirectServoController(), "direct"
    raise RuntimeError("Unknown servo backend: " + backend)


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(args, timeout=4):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout.strip()
    except Exception:
        return 127, ""


def udev(path):
    rc, out = run(["udevadm", "info", "--query=property", "--name", path], 3)
    props = {}
    if rc == 0:
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
    return props


def find_controller():
    for path in sorted(set(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))):
        props = udev(path)
        if (
            props.get("ID_SERIAL_SHORT") == EXPECTED_SERIAL
            and props.get("ID_VENDOR_ID", "").lower() == EXPECTED_VID
            and props.get("ID_MODEL_ID", "").lower() == EXPECTED_PID
        ):
            return path, props
    raise RuntimeError("Expected Seizo Arduino Uno is not present.")


def read_for(ser, seconds):
    end = time.monotonic() + seconds
    data = bytearray()
    while time.monotonic() < end:
        chunk = ser.read(4096)
        if chunk:
            data.extend(chunk)
        else:
            time.sleep(0.01)
    return bytes(data)


def query(ser, text, seconds=1.2):
    ser.reset_input_buffer()
    ser.write((text + "\r\n").encode("ascii"))
    ser.flush()
    return read_for(ser, seconds).decode("ascii", errors="replace")


def parse_settings(raw):
    out = {}
    for line in raw.splitlines():
        m = re.match(r"^\s*\$(\d+)\s*=\s*(-?(?:\d+(?:\.\d*)?|\.\d+))", line)
        if m:
            out[int(m.group(1))] = float(m.group(2))
    return out


def startup_blocks(raw):
    blocks = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("$N") and "=" in line:
            _, value = line.split("=", 1)
            if value.strip():
                blocks.append(line)
    return blocks


def preflight(ser):
    startup = read_for(ser, 0.7).decode("ascii", errors="replace")
    settings = parse_settings(query(ser, "$$", 1.7))
    starts = query(ser, "$N", 1.0)
    build = query(ser, "$I", 1.0)
    parser = require_manual_parser_state(ser)
    status = wait_idle(ser)

    if "grbl 0.9j" not in (startup + "\n" + build).lower():
        raise RuntimeError("Record/replay is pinned to the proven Grbl 0.9j controller.")
    if startup_blocks(starts):
        raise RuntimeError("GRBL startup blocks are not empty.")
    for setting in (100, 101, 102):
        if settings.get(setting, 0) <= 0:
            raise RuntimeError("GRBL setting $" + str(setting) + " is invalid.")

    return {
        "status": status,
        "parser": parser[:300],
        "steps_per_mm": {
            "X": settings[100],
            "Y": settings[101],
            "Z": settings[102],
        },
        "soft_limits": settings.get(20),
        "hard_limits": settings.get(21),
        "homing": settings.get(22),
        "accel_mm_s2": {
            "X": settings.get(120),
            "Y": settings.get(121),
            "Z": settings.get(122),
        },
    }


def set_session_acceleration(ser, values):
    from seizo_core.grbl_compat import line_expect_ok
    replies = {}
    for axis, setting in (("X",120),("Y",121),("Z",122)):
        value = float(values[axis])
        if not (5.0 <= value <= 100.0):
            raise RuntimeError("Refusing unsafe/invalid session acceleration.")
        replies[str(setting)] = line_expect_ok(ser, "$" + str(setting) + "=" + f"{value:.3f}", timeout=1.0)
    return replies


def restore_session_acceleration(ser, original):
    from seizo_core.grbl_compat import line_expect_ok
    restored = {}
    for axis, setting in (("X",120),("Y",121),("Z",122)):
        value = original.get(axis)
        if value is None:
            continue
        restored[axis] = line_expect_ok(ser, "$" + str(setting) + "=" + f"{float(value):.3f}", timeout=1.0)
    return restored


def restore_accel_on_port(port, original):
    if not original:
        return None
    try:
        import serial
        with serial.Serial(port, BAUD, timeout=0.10, write_timeout=1.0) as ser:
            time.sleep(2.0)
            return restore_session_acceleration(ser, original)
    except Exception as exc:
        telemetry("motion_profile", "restore_failed", {
            "error": type(exc).__name__ + ": " + str(exc),
            "original_accel_mm_s2": original,
        })
        return None


def atomic_write(payload):
    CACHE.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="rr-v21-", suffix=".json", dir=CACHE)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(payload, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)


def telemetry(event, outcome, detail):
    prior = {}
    try:
        prior = json.loads(OUT.read_text())
    except Exception:
        pass
    history = prior.get("history", []) if isinstance(prior, dict) else []
    if not isinstance(history, list):
        history = []
    entry = {
        "timestamp_utc": utc(),
        "event": event,
        "outcome": outcome,
        "detail": detail,
    }
    history.append(entry)
    atomic_write({
        "schema": "seizo-record-replay/v2",
        "release": "2.1",
        "latest": entry,
        "history": history[-120:],
    })
    env = os.environ.copy()
    env["SEIZO_EVENT"] = "rr_" + event + "_" + outcome
    try:
        subprocess.Popen(
            ["/bin/bash", str(ROOT / "scripts/publish_device_status.sh")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def drain_key_repeat(fd):
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], QUIET_RELEASE_SECONDS)
        if not ready:
            return
        try:
            os.read(fd, 64)
        except OSError:
            return


def skill_payload(actions):
    return {
        "schema": SCHEMA,
        "name": "latest-recorded-skill",
        "created_utc": utc(),
        "source_mode": "record-replay",
        "actions": actions,
    }


def save_recording(actions):
    valid = validate_skill(skill_payload(actions))
    save_skill(SKILL, valid)
    telemetry("record_saved", "pass", {
        "actions": len(valid["actions"]),
        "stepper_actions": sum(a["type"] == "relative_move" for a in valid["actions"]),
        "servo_actions": sum(a["type"] == "servo_set" for a in valid["actions"]),
        "skill_path": str(SKILL),
    })
    return valid


def execute_action(ser, servos, action):
    if action["type"] == "relative_move":
        return controlled_incremental_move(
            ser,
            action["axis"],
            action["delta_mm"],
            action["feed_mm_min"],
        )

    if servos is None:
        raise RuntimeError("Recorded skill contains servo actions but no servo backend is available.")
    if action["servo"] == "gripper":
        return servos.gripper_to_us(action["to_us"])
    if action["servo"] == "wrist":
        return servos.wrist_to_us(action["to_us"])
    raise RuntimeError("Unsupported servo action.")


def undo_to_start(ser, servos, actions, fd, cameras):
    inverse = inverse_actions(actions)
    telemetry("undo_start", "started", {"actions": len(inverse)})
    completed = 0
    for i, action in enumerate(inverse):
        ready, _, _ = select.select([fd], [], [], 0)
        if ready:
            key = os.read(fd, 1)
            if key == b" ":
                software_hold(ser)
                telemetry("undo_start", "software_hold_abort", {
                    "completed": completed,
                    "total": len(inverse),
                })
                print("\nU RETURN ABORTED BY SPACE.")
                return False
        cameras.require_live()
        result = execute_action(ser, servos, action)
        vision = cameras.checkpoint(retries=3)
        completed += 1
        telemetry("undo_action", "pass", {
            "index": i,
            "total": len(inverse),
            "action": action,
            "result": result,
            "vision_checkpoint": vision,
        })
        time.sleep(REPLAY_GAP_S)
    telemetry("undo_start", "pass", {"actions": len(inverse)})
    return True


def record_mode(port, cameras, servo_backend):
    actions = []
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    servos = None
    original_accel = None
    accel_restored = False
    try:
        import serial
        with serial.Serial(port, BAUD, timeout=0.10, write_timeout=1.0) as ser:
            time.sleep(2.2)
            pre = preflight(ser)
            original_accel = dict(pre["accel_mm_s2"])
            accel_reply = set_session_acceleration(ser, SMOOTH_ACCEL_MM_S2)

            print("PREFLIGHT PASS.")
            print("MOTION PROFILE: X/Y 3.00 mm @ 90 mm/min, Z 1.50 mm @ 60 mm/min.")
            print("ACCEL: X/Y 15 mm/s^2, Z 8 mm/s^2.")
            print("Turn 12V motor power ON for steppers.")
            print("Turn servo 5V power ON if you want N/M/O/P.")
            print("Keep the physical kill switch reachable.")
            print("First servo command establishes a 1500 us reference before moving.")
            cameras.require_live()
            cameras.arm_baseline()
            active_servo_backend = None
            telemetry("record_session", "started", {
                "preflight": pre,
                "stepper_step_mm": STEPPER_STEP_MM,
                "stepper_feed_mm_min": STEPPER_FEED_MM_MIN,
                "session_accel_mm_s2": SMOOTH_ACCEL_MM_S2,
                "original_accel_mm_s2": original_accel,
                "accel_config_reply": accel_reply,
                "servo_backend_requested": servo_backend,
                "servo_backend_active": active_servo_backend,
            })

            tty.setcbreak(fd)
            print()
            print("RECORDING")
            print("W/S Y | A/D R | Q/E Z | N/M gripper OPEN/CLOSE | O/P wrist -/+")
            print("U = SAVE + RETURN TO START + EXIT")
            print("ESC = SAVE HERE + EXIT")
            print("SPACE = SOFTWARE HOLD + SAVE + EXIT")
            print()

            while True:
                ch = sys.stdin.read(1)
                if not ch:
                    continue
                low = ch.lower()

                if low == "u":
                    if not actions:
                        print("\rU: nothing recorded yet.                         ", end="", flush=True)
                        drain_key_repeat(fd)
                        continue
                    valid = save_recording(actions)
                    returned = undo_to_start(ser, servos, valid["actions"], fd, cameras)
                    if returned:
                        telemetry("record_session", "saved_and_returned_to_start", {
                            "actions": len(valid["actions"]),
                        })
                        print("\nSAVED + RETURNED TO RECORDING START.")
                    else:
                        telemetry("record_session", "saved_return_aborted", {
                            "actions": len(valid["actions"]),
                        })
                    break

                if ch == "\x1b":
                    wait_idle(ser)
                    if actions:
                        valid = save_recording(actions)
                        telemetry("record_session", "saved_in_place", {"actions": len(valid["actions"])})
                    else:
                        telemetry("record_session", "empty_exit", {})
                    break

                if ch == " ":
                    software_hold(ser)
                    if actions:
                        valid = save_recording(actions)
                        telemetry("record_session", "software_hold_saved", {"actions": len(valid["actions"])})
                    else:
                        telemetry("record_session", "software_hold_empty", {})
                    break

                if low in STEPPER_KEYS:
                    axis, sign, label = STEPPER_KEYS[low]
                    delta = sign * STEPPER_STEP_MM[axis]
                    feed = STEPPER_FEED_MM_MIN[axis]
                    cameras.require_live()
                    result = controlled_incremental_move(ser, axis, delta, feed)
                    vision = cameras.checkpoint(retries=3)
                    action = {
                        "type": "relative_move",
                        "axis": axis,
                        "delta_mm": delta,
                        "feed_mm_min": feed,
                        "label": label,
                        "source_key": low,
                    }
                    actions.append(action)
                    telemetry("record_action", "pass", {
                        "index": len(actions) - 1,
                        "action": action,
                        "status_after": result["status_after"],
                        "vision_checkpoint": vision,
                    })
                    print("\rREC " + str(len(actions)).rjust(3, "0") + " | " + label + "                 ", end="", flush=True)
                    drain_key_repeat(fd)
                    continue

                if low in SERVO_KEYS:
                    servo_name, target, label = SERVO_KEYS[low]
                    cameras.require_live()
                    if servos is None:
                        try:
                            servos, active_servo_backend = make_servo_controller(servo_backend)
                            telemetry("servo_backend", "ready", {
                                "requested": servo_backend,
                                "active": active_servo_backend,
                                "state": servos.snapshot(),
                            })
                            print("\nSERVO BACKEND READY: " + active_servo_backend.upper())
                        except Exception as exc:
                            telemetry("servo_backend", "unavailable", {
                                "requested": servo_backend,
                                "error": type(exc).__name__ + ": " + str(exc),
                            })
                            print("\nSERVO UNAVAILABLE: " + str(exc))
                            print("Stepper recording continues. N/M/O/P ignored until servo controller is available.")
                            drain_key_repeat(fd)
                            continue
                    if servo_name == "gripper":
                        result = servos.gripper_set(target)
                    else:
                        result = servos.wrist_step(int(target))
                    vision = cameras.checkpoint(retries=3)

                    before = result["from_us"]
                    after = result["to_us"]
                    if before == after:
                        print("\r" + label + " | already there                 ", end="", flush=True)
                        drain_key_repeat(fd)
                        continue

                    action = {
                        "type": "servo_set",
                        "servo": servo_name,
                        "from_us": before,
                        "to_us": after,
                        "label": label,
                        "source_key": low,
                    }
                    actions.append(action)
                    telemetry("record_action", "pass", {
                        "index": len(actions) - 1,
                        "action": action,
                        "servo_state": servos.snapshot(),
                        "vision_checkpoint": vision,
                    })
                    print("\rREC " + str(len(actions)).rjust(3, "0") + " | " + label + "                 ", end="", flush=True)
                    drain_key_repeat(fd)

            restored = restore_session_acceleration(ser, original_accel)
            accel_restored = True
            telemetry("motion_profile", "restored", {"original_accel_mm_s2": original_accel, "reply": restored})

    except Exception as exc:
        if actions:
            try:
                save_recording(actions)
            except Exception:
                pass
        telemetry("record_session", "fail", {
            "error": type(exc).__name__ + ": " + str(exc),
            "actions": len(actions),
        })
        raise
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if servos is not None:
            servos.shutdown()
        if original_accel and not accel_restored:
            reply = restore_accel_on_port(port, original_accel)
            if reply is not None:
                telemetry("motion_profile", "restored_after_exit", {"original_accel_mm_s2": original_accel, "reply": reply})

    print("\nTurn motor/servo power OFF when finished.")
    return 0


def replay_mode(port, cameras, servo_backend):
    skill = load_skill(SKILL)
    actions = skill["actions"]
    uses_servo = any(a["type"] == "servo_set" for a in actions)
    uses_stepper = any(a["type"] == "relative_move" for a in actions)

    print("Loaded " + str(len(actions)) + " recorded actions.")
    print("Place the arm at the SAME physical start pose used for recording.")
    print("LOCAL LAUNCH ACCEPTED — replay preflight continues directly.")

    servos = None
    original_accel = None
    accel_restored = False
    try:
        import serial
        with serial.Serial(port, BAUD, timeout=0.10, write_timeout=1.0) as ser:
            time.sleep(2.2)
            pre = preflight(ser)
            original_accel = dict(pre["accel_mm_s2"])
            accel_reply = set_session_acceleration(ser, SMOOTH_ACCEL_MM_S2)
            print("PREFLIGHT PASS.")
            print("MOTION PROFILE: replay uses the per-action speeds stored in the skill.")
            print("ACCEL: X/Y 15 mm/s^2, Z 8 mm/s^2.")
            if uses_stepper:
                print("Turn 12V motor power ON.")
            if uses_servo:
                print("Turn servo 5V power ON.")
            print("Keep the physical kill switch reachable.")
            cameras.require_live()
            cameras.arm_baseline()
            active_servo_backend = None
            if uses_servo:
                servos, active_servo_backend = make_servo_controller(servo_backend)
            telemetry("replay_session", "started", {
                "actions": len(actions),
                "uses_stepper": uses_stepper,
                "uses_servo": uses_servo,
                "preflight": pre,
                "session_accel_mm_s2": SMOOTH_ACCEL_MM_S2,
                "original_accel_mm_s2": original_accel,
                "accel_config_reply": accel_reply,
                "servo_backend_requested": servo_backend,
                "servo_backend_active": active_servo_backend,
                "servo_state": servos.snapshot() if servos is not None else None,
            })

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            completed = 0
            try:
                tty.setcbreak(fd)
                for i, action in enumerate(actions):
                    ready, _, _ = select.select([fd], [], [], 0)
                    if ready:
                        key = os.read(fd, 1)
                        if key == b" ":
                            software_hold(ser)
                            telemetry("replay_session", "software_hold_abort", {
                                "completed": completed,
                                "total": len(actions),
                            })
                            print("\nREPLAY ABORTED BY SPACE.")
                            break

                    cameras.require_live()
                    result = execute_action(ser, servos, action)
                    vision = cameras.checkpoint(retries=3)
                    completed += 1
                    telemetry("replay_action", "pass", {
                        "index": i,
                        "total": len(actions),
                        "action": action,
                        "result": result,
                        "vision_checkpoint": vision,
                    })
                    print("\rREPLAY " + str(completed).rjust(3, "0") + "/" + str(len(actions)).rjust(3, "0") + " | " + action.get("label", "") + "      ", end="", flush=True)
                    time.sleep(REPLAY_GAP_S)
                else:
                    telemetry("replay_session", "pass", {
                        "completed": completed,
                        "total": len(actions),
                    })
                    print("\nREPLAY COMPLETE.")
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

            restored = restore_session_acceleration(ser, original_accel)
            accel_restored = True
            telemetry("motion_profile", "restored", {"original_accel_mm_s2": original_accel, "reply": restored})

    except Exception as exc:
        telemetry("replay_session", "fail", {
            "error": type(exc).__name__ + ": " + str(exc),
        })
        raise
    finally:
        if servos is not None:
            servos.shutdown()
        if original_accel and not accel_restored:
            reply = restore_accel_on_port(port, original_accel)
            if reply is not None:
                telemetry("motion_profile", "restored_after_exit", {"original_accel_mm_s2": original_accel, "reply": reply})

    print("Turn motor/servo power OFF when finished.")
    return 0


def main():
    if not sys.stdin.isatty():
        print("Interactive terminal required.")
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["manual", "camera"])
    parser.add_argument("--action", choices=["record", "replay"])
    parser.add_argument("--servo-backend", choices=["direct", "nano", "auto"], default="direct")
    args = parser.parse_args()

    mode = args.mode
    action = args.action

    if mode is None:
        print("SEIZO 2.1 — RECORD & REPLAY")
        print("M = MANUAL-ONLY test now")
        print("C = CAMERA-ASSISTED mode")
        mode = input("Choose M or C: ").strip().lower()
        mode = {"m": "manual", "c": "camera"}.get(mode)
        if mode is None:
            print("Unknown mode.")
            return 2

    if action is None:
        print("1 = RECORD a new skill")
        print("2 = REPLAY latest skill")
        choice = input("Choose 1 or 2: ").strip()
        action = {"1": "record", "2": "replay"}.get(choice)
        if action is None:
            print("Unknown action.")
            return 2

    print("Start with 12V motor power OFF and servo 5V OFF.")
    print("Physical kill switch reachable.")
    print("LOCAL LAUNCH ACCEPTED — continuing directly.")

    monitor = None
    try:
        if mode == "camera":
            # Lazy import keeps the manual phone controller independent from
            # experimental camera/vision code.
            from seizo_core.camera_monitor import DualCameraMonitor
            monitor = DualCameraMonitor()
            if not monitor.wait_fresh(timeout=10.0):
                raise RuntimeError("Both camera feeds did not become live.")

            print("\nOPEN THIS LIVE CAMERA VIEW ON YOUR PHONE/LAPTOP:")
            for url in monitor.urls():
                print("  " + url)
            print("You MUST be able to see BOTH live feeds before motion can arm.")
            print("In the browser press: I CAN SEE BOTH CAMERAS")

            if not monitor.wait_ack(timeout=600.0):
                raise RuntimeError("Camera acknowledgement timed out.")
            monitor.require_live()
            monitor.arm_baseline()
            telemetry("camera_gate", "pass", monitor.status())
        else:
            monitor = ManualOnlyMonitor()
            monitor.arm_baseline()
            telemetry("manual_gate", "pass", monitor.status())
            print("MANUAL-ONLY MODE: cameras are not required for this run.")
            print("The saved skill remains compatible with camera-assisted replay later.")

        port, _ = find_controller()
        if action == "record":
            return record_mode(port, monitor, args.servo_backend)
        return replay_mode(port, monitor, args.servo_backend)

    except Exception as exc:
        telemetry(mode + "_gate", "fail", {"error": type(exc).__name__ + ": " + str(exc)})
        print(mode.upper() + " GATE BLOCKED: " + str(exc))
        return 3
    finally:
        if monitor is not None:
            monitor.close()


if __name__ == "__main__":
    raise SystemExit(main())
