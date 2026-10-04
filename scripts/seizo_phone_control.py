#!/usr/bin/env python3
"""Seizo one-page manual hardware test.

Active scope is deliberately manual:
- no replay
- no automatic return
- no workspace automation
- no camera-driven motion

The physical kill switch is the emergency stop.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import seizo_record_replay_v21 as rr
from seizo_core.grbl_compat import line_expect_ok, wait_idle, controlled_incremental_vector_move
from seizo_core.nano_servos import _candidate_ports
from seizo_core.workspace_limits import WorkspaceGuard, WorkspaceLimitError
from seizo_core.auto_gate import readiness as auto_readiness, preview_skill
from seizo_core.skill import save_skill, validate_skill

PORT = 8790
WEB_RELEASE = "guided-teach-2026-10-04.1"
PAGE_MARKER = "SEIZO_MANUAL_WEB_OK"
CAMERA_API = "http://127.0.0.1:8787"
CACHE = Path.home() / ".cache" / "seizo"
CONFIG_PATH = CACHE / "motion_config.json"
TEST_PATH = CACHE / "manual_test_latest.json"
SETUP_PATH = CACHE / "setup_status_latest.json"
SESSION_PATH = CACHE / "session_status_latest.json"
SELFTEST_PATH = CACHE / "software_selftest_latest.json"
ARM_STATUS_PATH = CACHE / "arm_status_latest.json"
WORKSPACE_PATH = CACHE / "workspace_limits.json"
NANO_PROBE_PATH = CACHE / "nano_probe_latest.json"
PHONE_SKILL_DIR = CACHE / "skills" / "phone"
LATEST_TAUGHT_SKILL = CACHE / "skills" / "latest_taught.json"
MANUAL_TEST_PROFILE = "xyz-3-3-1p5_feed-90-90-60_nano-v1"

COMPONENT_KEYS = {
    "base": ("a", "d"),
    "y": ("w", "s"),
    "z": ("q", "e"),
    "gripper": ("n", "m"),
    "wrist": ("o", "p"),
}


def read_json(path, default=None):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else default
    except Exception:
        return default


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def record_arm_status(outcome, message, **detail):
    atomic_json(ARM_STATUS_PATH, {
        "schema": "seizo-arm-status/v1",
        "timestamp_unix": time.time(),
        "outcome": str(outcome),
        "message": str(message)[:500],
        "detail": detail,
    })


def camera_status():
    try:
        with urllib.request.urlopen(CAMERA_API + "/status", timeout=0.5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def load_invert():
    state = {"X": False, "Y": False, "Z": False}
    data = read_json(CONFIG_PATH, {}) or {}
    saved = data.get("invert", {})
    for axis in state:
        if axis in saved:
            state[axis] = bool(saved[axis])
    return state


def save_invert(state):
    atomic_json(CONFIG_PATH, {"invert": state})


def fast_manual_preflight(ser):
    """No-motion preflight for the pinned GRBL Uno.

    Opening an Uno serial port can reset the board. The proven read-only probe
    therefore allows the bootloader/GRBL startup time and confirms identity
    from either the startup banner or the $I build response.
    """
    time.sleep(2.2)
    startup = rr.read_for(ser, 0.8).decode("ascii", errors="replace")
    build = rr.query(ser, "$I", 1.0)
    if "grbl 0.9j" not in (startup + "\n" + build).lower():
        raise RuntimeError("Expected proven GRBL 0.9j controller was not identified.")

    settings = rr.parse_settings(rr.query(ser, "$$", 1.7))
    starts = rr.query(ser, "$N", 1.0)
    if rr.startup_blocks(starts):
        raise RuntimeError("GRBL startup blocks are not empty.")

    for setting in (100, 101, 102):
        value = settings.get(setting)
        if value is None or abs(float(value) - 250.0) > 0.01:
            raise RuntimeError("GRBL $" + str(setting) + " must remain at the proven 250.000 steps/mm.")
    accel = {"X": settings.get(120), "Y": settings.get(121), "Z": settings.get(122)}
    if any(v is None or not (5.0 <= float(v) <= 100.0) for v in accel.values()):
        raise RuntimeError("GRBL acceleration settings are missing or invalid.")

    line_expect_ok(ser, "G21 G90", timeout=0.8)
    wait_idle(ser, timeout=1.5)
    return {"accel_mm_s2": accel}


def current_boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except Exception:
        return "unknown"


def new_test_state(boot_id=None):
    return {
        "schema": "seizo-manual-test/v2",
        "boot_id": boot_id or current_boot_id(),
        "profile": MANUAL_TEST_PROFILE,
        "command_counts": {k: 0 for k in "wsadqenmop"},
        "physical": {name: "untested" for name in COMPONENT_KEYS},
        "last_key": None,
        "last_label": None,
        "updated_at": time.time(),
    }


def new_teach_state():
    return {
        "active": False,
        "name": "",
        "actions": [],
        "started_at": None,
        "started_position": None,
        "last_saved_path": None,
        "last_saved_actions": 0,
    }


def skill_filename(name):
    clean = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:48]
    if not clean:
        clean = "taught-skill"
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return clean + "-" + stamp + ".json"


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.ser = None
        self.servos = None
        self.servo_backend = None
        self.original_accel = None
        self.armed = False
        self.fast_mode = False
        self.invert = load_invert()
        self.message = "Ready. Turn on 12V motor power + external 5V servo power, then ARM."
        self.last_command = None
        self.workspace = WorkspaceGuard(WORKSPACE_PATH)
        # Manual HOME is not physically repeatable yet. Never trust limits
        # loaded from an earlier process/session against a newly chosen HOME.
        self.workspace.clear_limits()
        self.auto_preview = None
        self.teach = new_teach_state()
        self.boot_id = current_boot_id()
        loaded_test = read_json(TEST_PATH, {}) or {}
        if (loaded_test.get("boot_id") != self.boot_id or
                loaded_test.get("profile") != MANUAL_TEST_PROFILE):
            self.test = new_test_state(self.boot_id)
            atomic_json(TEST_PATH, self.test)
        else:
            self.test = loaded_test
        for key in "wsadqenmop":
            self.test.setdefault("command_counts", {}).setdefault(key, 0)
        for name in COMPONENT_KEYS:
            self.test.setdefault("physical", {}).setdefault(name, "untested")

    def _save_test(self):
        self.test["updated_at"] = time.time()
        atomic_json(TEST_PATH, self.test)

    def _close_locked(self):
        if self.ser is not None:
            if self.original_accel:
                try:
                    rr.restore_session_acceleration(self.ser, self.original_accel)
                except Exception:
                    pass
            try:
                self.ser.close()
            except Exception:
                pass
        if self.servos is not None:
            try:
                self.servos.shutdown()
            except Exception:
                pass
        self.ser = None
        self.servos = None
        self.servo_backend = None
        self.original_accel = None
        self.armed = False
        self.workspace.clear_reference()
        self.workspace.clear_limits()
        self.auto_preview = None
        self.teach = new_teach_state()

    def arm(self):
        with self.lock:
            if self.armed:
                self.message = "Already ARMED."
                record_arm_status("pass", self.message, already_armed=True)
                return
            import serial
            port, _ = rr.find_controller()
            ser = serial.Serial(port, rr.BAUD, timeout=0.10, write_timeout=1.0)
            try:
                pre = fast_manual_preflight(ser)
                original = dict(pre["accel_mm_s2"])
                rr.set_session_acceleration(ser, rr.SMOOTH_ACCEL_MM_S2)
            except Exception as exc:
                record_arm_status(
                    "fail",
                    f"{type(exc).__name__}: {exc}",
                    controller_port=port,
                    stage="preflight",
                )
                try:
                    ser.close()
                except Exception:
                    pass
                raise
            self.ser = ser
            self.original_accel = original
            self.armed = True
            self.message = "ARMED — manual only. Test one row at a time."
            record_arm_status(
                "pass",
                self.message,
                controller_port=port,
                accel_mm_s2=pre.get("accel_mm_s2"),
            )

    def stop_now(self):
        ser = self.ser
        if ser is not None:
            try:
                ser.write(b"!")
                ser.flush()
            except Exception:
                pass
        with self.lock:
            self._close_locked()
            self.message = "STOPPED / DISARMED. Physical kill switch remains the emergency stop."

    def flip_axis(self, axis):
        with self.lock:
            axis = str(axis).upper()
            if axis not in ("X", "Y", "Z"):
                raise RuntimeError("Unknown axis.")
            self.invert[axis] = not self.invert[axis]
            save_invert(self.invert)
            self.message = f"{axis} direction reversed. Retest that row."

    def set_speed_mode(self, mode):
        with self.lock:
            mode = str(mode).lower()
            if mode not in ("normal", "fast"):
                raise RuntimeError("Speed mode must be normal or fast.")
            self.fast_mode = mode == "fast"
            self.message = (
                "FAST manual mode: same low acceleration, higher travel feed."
                if self.fast_mode else
                "NORMAL manual mode."
            )

    def _component_for_axis(self, axis):
        return {"X":"base","Y":"y","Z":"z"}[str(axis).upper()]

    def _require_component_available(self, component):
        state = self.test.get("physical", {}).get(str(component).lower(), "untested")
        if state == "fail":
            raise RuntimeError(
                str(component).upper() +
                " is quarantined after a physical FAIL. Repair it, then use RETEST HARDWARE before moving it again."
            )

    def _feed_for_axes(self, axes):
        axes = set(str(a).upper() for a in axes)
        if not self.fast_mode:
            if axes == {"Z"}:
                return 60.0
            if "Z" in axes:
                return 75.0
            return 90.0
        # Faster travel without increasing the proven low acceleration values.
        if axes == {"Z"}:
            return 90.0
        if "Z" in axes:
            return 110.0
        return 135.0

    def vector_move(self, x_sign=0, y_sign=0, z_sign=0):
        with self.lock:
            if not self.armed or self.ser is None:
                raise RuntimeError("Tap ARM first.")
            if self.teach.get("active"):
                raise RuntimeError("Coordinated vector moves are disabled while teaching. Use the guided single-axis controls.")

            signs = {
                "X": int(x_sign),
                "Y": int(y_sign),
                "Z": int(z_sign),
            }
            if any(v not in (-1, 0, 1) for v in signs.values()):
                raise RuntimeError("Vector directions must be -1, 0, or +1.")
            if not any(signs.values()):
                raise RuntimeError("Choose at least one direction.")

            physical = {
                "X": signs["X"] * rr.STEPPER_STEP_MM["X"],
                "Y": signs["Y"] * rr.STEPPER_STEP_MM["Y"],
                "Z": signs["Z"] * rr.STEPPER_STEP_MM["Z"],
            }
            commanded = {}
            for axis, delta in physical.items():
                if not delta:
                    continue
                self._require_component_available(self._component_for_axis(axis))
                commanded[axis] = -delta if self.invert.get(axis, False) else delta

            if self.workspace.reference_valid and (self.workspace.calibrating or self.workspace.configured()):
                for axis, delta in physical.items():
                    if delta:
                        self.workspace.predict(axis, delta)

            feed = self._feed_for_axes(commanded.keys())
            result = controlled_incremental_vector_move(self.ser, commanded, feed)
            if self.workspace.reference_valid:
                for axis, delta in physical.items():
                    if delta:
                        self.workspace.commit(axis, delta)
            self.last_command = {
                "kind": "coordinated_manual",
                "physical_delta_mm": physical,
                "grbl_delta_mm": commanded,
                "feed_mm_min": feed,
            }
            active = ", ".join(f"{a}{d:+.1f}" for a, d in commanded.items())
            self.message = (
                f"COORDINATED manual move accepted: {active} at {feed:.0f} mm/min. "
                "Axes move together in one GRBL block."
            )
            return result

    def nano_probe_now(self):
        with self.lock:
            if self.armed:
                raise RuntimeError("STOP / DISARM before the read-only Nano check.")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts/seizo_nano_readonly_probe.py")],
                cwd=ROOT, capture_output=True, text=True, timeout=12, check=False,
            )
            result = read_json(NANO_PROBE_PATH, {}) or {}
            if proc.returncode == 0 and result.get("outcome") == "pass":
                self.message = "Nano VERIFIED by HELLO/PING. No servo output command was sent."
                return result
            error = result.get("error") or (proc.stderr or proc.stdout or "Nano probe failed").strip()[-500:]
            self.message = "Nano check failed: " + str(error)
            raise RuntimeError(self.message)

    def ensure_servo(self):
        if self.servos is None:
            self.servos, self.servo_backend = rr.make_servo_controller("nano")
        return self.servos

    def _count(self, key, label):
        self.test["command_counts"][key] = int(self.test["command_counts"].get(key, 0)) + 1
        self.test["last_key"] = key
        self.test["last_label"] = label
        self._save_test()

    def step(self, key):
        with self.lock:
            if not self.armed or self.ser is None:
                raise RuntimeError("Tap ARM first.")
            key = str(key).lower()
            self._teach_capacity_check()

            if key in rr.STEPPER_KEYS:
                axis, sign, label = rr.STEPPER_KEYS[key]
                self._require_component_available(self._component_for_axis(axis))
                physical_delta = sign * rr.STEPPER_STEP_MM[axis]
                grbl_delta = -physical_delta if self.invert.get(axis, False) else physical_delta
                if self.workspace.reference_valid and (self.workspace.calibrating or self.workspace.configured()):
                    self.workspace.predict(axis, physical_delta)
                feed = self._feed_for_axes([axis])
                result = rr.controlled_incremental_move(self.ser, axis, grbl_delta, feed)
                if self.workspace.reference_valid:
                    self.workspace.commit(axis, physical_delta)
                self.last_command = {
                    "kind": "stepper",
                    "key": key,
                    "axis": axis,
                    "physical_delta_mm": physical_delta,
                    "grbl_delta_mm": grbl_delta,
                    "feed_mm_min": feed,
                }
                self._count(key, label)
                taught = self._record_taught_action({
                    "type": "relative_move",
                    "axis": axis,
                    "delta_mm": grbl_delta,
                    "feed_mm_min": feed,
                    "label": label,
                    "source_key": key,
                })
                suffix = f" TEACH REC #{taught}." if taught else ""
                self.message = f"{label} command accepted. Watch the arm; then test the opposite button." + suffix
                return result

            if key in rr.SERVO_KEYS:
                servo_name, target, label = rr.SERVO_KEYS[key]
                self._require_component_available(servo_name)
                servos = self.ensure_servo()
                result = (
                    servos.gripper_set(target)
                    if servo_name == "gripper"
                    else servos.wrist_step(int(target))
                )
                self.last_command = {
                    "kind": "servo",
                    "key": key,
                    "servo": servo_name,
                    "result": result,
                }
                self._count(key, label)
                taught = 0
                if result.get("from_us") != result.get("to_us"):
                    taught = self._record_taught_action({
                        "type": "servo_set",
                        "servo": servo_name,
                        "from_us": result["from_us"],
                        "to_us": result["to_us"],
                        "label": label,
                        "source_key": key,
                    })
                suffix = f" TEACH REC #{taught}." if taught else ""
                self.message = (
                    f"{label} command accepted by Nano ({result['from_us']}→{result['to_us']} µs). "
                    "Watch for physical movement." + suffix
                )
                return result

            raise RuntimeError("Unknown manual control.")

    def report_component(self, component, outcome):
        with self.lock:
            component = str(component).lower()
            outcome = str(outcome).lower()
            if component not in COMPONENT_KEYS:
                raise RuntimeError("Unknown test row.")
            if outcome not in ("pass", "fail"):
                raise RuntimeError("Outcome must be pass or fail.")
            keys = COMPONENT_KEYS[component]
            missing = [k for k in keys if int(self.test["command_counts"].get(k, 0)) < 1]
            if missing:
                raise RuntimeError("Test both movement buttons in this row before marking it.")
            self.test["physical"][component] = outcome
            self._save_test()
            pretty = {
                "base": "Base",
                "y": "Y reach",
                "z": "Z height",
                "gripper": "Gripper",
                "wrist": "Wrist",
            }[component]
            if outcome == "pass":
                self.message = f"{pretty} marked PHYSICALLY PASS."
            elif component in ("y", "z"):
                self.message = (
                    f"{pretty} marked FAIL and QUARANTINED. Further commands to this axis are blocked "
                    "until RETEST HARDWARE is used after the gear/transmission repair."
                )
            elif component in ("gripper", "wrist"):
                self.message = (
                    f"{pretty} marked FAIL and QUARANTINED. Nano diagnostics will separate controller/USB "
                    "health from the downstream 5V, ground, signal, or servo path."
                )
            else:
                self.message = (
                    f"{pretty} marked FAIL. Stop testing that axis; check motor power, driver/wiring, "
                    "mechanical binding, and that the arm is not at a physical limit."
                )

    def set_home_reference(self):
        with self.lock:
            if not self.armed:
                raise RuntimeError("ARM MANUAL before setting HOME.")
            self.workspace.clear_limits()
            self.workspace.set_reference_here()
            self.auto_preview = None
            self.message = "HOME/reference set for this session. Physical pose is now X0 Y0 Z0."

    def clear_home_reference(self):
        with self.lock:
            self.workspace.clear_reference()
            self.workspace.clear_limits()
            self.auto_preview = None
            self.message = "HOME/reference cleared. Automatic planning is locked."

    def start_limit_calibration(self, reset=False):
        with self.lock:
            if not self.armed:
                raise RuntimeError("ARM MANUAL before calibrating limits.")
            if not self.workspace.reference_valid:
                raise RuntimeError("Set HOME/reference first.")
            if reset:
                self.workspace.clear_limits()
            self.workspace.start_calibration()
            self.auto_preview = None
            self.message = "Limit calibration started. Save conservative SAFE MIN/MAX points, not hard mechanical stops."

    def capture_limit(self, axis, bound):
        with self.lock:
            axis = str(axis).upper()
            bound = str(bound).lower()
            if axis not in ("X","Y","Z") or bound not in ("min","max"):
                raise RuntimeError("Invalid SAFE limit.")
            snap = self.workspace.snapshot()
            current = float(snap["position"][axis])
            other = snap["limits"][axis]["max" if bound == "min" else "min"]
            if other is not None:
                if bound == "min" and not current < float(other):
                    raise RuntimeError("SAFE MIN must be below SAFE MAX.")
                if bound == "max" and not current > float(other):
                    raise RuntimeError("SAFE MAX must be above SAFE MIN.")
            self.workspace.set_limit_here(axis, bound)
            self.auto_preview = None
            value = self.workspace.snapshot()["limits"][axis][bound]
            self.message = f"{axis} SAFE {bound.upper()} saved at {value:.1f} mm."
            return value

    def finish_limit_calibration(self):
        with self.lock:
            if not self.workspace.calibrating:
                raise RuntimeError("Limit calibration is not active.")
            position = self.workspace.snapshot()["position"]
            tolerance = {
                "X": rr.STEPPER_STEP_MM["X"] / 2.0 + 0.01,
                "Y": rr.STEPPER_STEP_MM["Y"] / 2.0 + 0.01,
                "Z": rr.STEPPER_STEP_MM["Z"] / 2.0 + 0.01,
            }
            away = [
                f"{axis}={position[axis]:.1f}"
                for axis in ("X","Y","Z")
                if abs(float(position[axis])) > tolerance[axis]
            ]
            if away:
                raise RuntimeError("Return all axes to HOME before finishing: " + ", ".join(away))
            self.workspace.complete_calibration()
            self.auto_preview = None
            self.message = "Safe travel limits saved. Automatic planner can now be dry-run."

    def cancel_limit_calibration(self):
        with self.lock:
            self.workspace.cancel_calibration()
            self.auto_preview = None
            self.message = "Limit calibration cancelled. Automatic planning remains locked until limits are complete."

    def clear_limits(self):
        with self.lock:
            self.workspace.clear_limits()
            self.auto_preview = None
            self.message = "Saved travel limits cleared."

    def auto_gate(self, cams=None):
        if cams is None:
            cams = camera_status()
        return auto_readiness(
            armed=self.armed,
            physical=self.test.get("physical", {}),
            camera_overhead=bool(cams.get("overhead_fresh")),
            camera_wrist=bool(cams.get("wrist_fresh")),
            workspace=self.workspace.snapshot(),
        )

    def planner_dry_run(self):
        with self.lock:
            cams = camera_status()
            gate = self.auto_gate(cams)
            skill = {
                "schema": "seizo-skill/v1",
                "name": "automatic-readiness-loop",
                "created_utc": "session",
                "source_mode": "planner-dry-run",
                "actions": [
                    {"type":"relative_move","axis":"X","delta_mm":3.0,"feed_mm_min":60.0,"label":"X+","source_key":"d"},
                    {"type":"relative_move","axis":"X","delta_mm":-3.0,"feed_mm_min":60.0,"label":"X-","source_key":"a"},
                    {"type":"relative_move","axis":"Y","delta_mm":3.0,"feed_mm_min":60.0,"label":"Y+","source_key":"w"},
                    {"type":"relative_move","axis":"Y","delta_mm":-3.0,"feed_mm_min":60.0,"label":"Y-","source_key":"s"},
                    {"type":"relative_move","axis":"Z","delta_mm":1.5,"feed_mm_min":45.0,"label":"Z+","source_key":"q"},
                    {"type":"relative_move","axis":"Z","delta_mm":-1.5,"feed_mm_min":45.0,"label":"Z-","source_key":"e"},
                ],
            }
            self.auto_preview = preview_skill(skill, self.workspace, gate)
            if self.auto_preview.get("ready"):
                self.message = "PLANNER DRY RUN PASS. Path validated; zero physical commands executed."
            else:
                blockers = ", ".join(self.auto_preview.get("blockers", [])) or "unknown"
                self.message = "Planner dry run blocked: " + blockers
            return self.auto_preview

    def _teach_capacity_check(self):
        if self.teach.get("active") and len(self.teach.get("actions", [])) >= 200:
            raise RuntimeError("Teaching buffer is full at 200 actions. Save or cancel before moving again.")

    def _record_taught_action(self, action):
        if not self.teach.get("active"):
            return 0
        actions = self.teach.setdefault("actions", [])
        if len(actions) >= 200:
            raise RuntimeError("Teaching buffer is full at 200 actions.")
        candidate = {
            "schema": "seizo-skill/v1",
            "name": self.teach.get("name") or "taught-skill",
            "created_utc": "session",
            "source_mode": "phone-teach",
            "actions": [action],
        }
        clean = validate_skill(candidate)["actions"][0]
        actions.append(clean)
        return len(actions)

    def start_teaching(self, name):
        with self.lock:
            if self.teach.get("active"):
                raise RuntimeError("A teaching session is already active.")
            if not self.armed:
                raise RuntimeError("ARM MANUAL before teaching a skill.")
            gate = self.auto_gate(camera_status())
            if not gate.get("ready_for_planning"):
                blockers = ", ".join(gate.get("blockers", [])) or "unknown"
                raise RuntimeError("Finish safety setup before teaching: " + blockers)
            skill_name = str(name or "").strip()[:80]
            if not skill_name:
                skill_name = "taught-skill-" + time.strftime("%H%M%S", time.localtime())
            snap = self.workspace.snapshot()
            self.teach = {
                "active": True,
                "name": skill_name,
                "actions": [],
                "started_at": time.time(),
                "started_position": dict(snap.get("position", {})),
                "last_saved_path": self.teach.get("last_saved_path"),
                "last_saved_actions": self.teach.get("last_saved_actions", 0),
            }
            self.message = (
                "TEACHING " + skill_name + ". Manual moves are now being recorded. "
                "Use STOP / DISARM for any unexpected motion."
            )

    def cancel_teaching(self):
        with self.lock:
            if not self.teach.get("active"):
                raise RuntimeError("No teaching session is active.")
            last_path = self.teach.get("last_saved_path")
            last_count = self.teach.get("last_saved_actions", 0)
            self.teach = new_teach_state()
            self.teach["last_saved_path"] = last_path
            self.teach["last_saved_actions"] = last_count
            self.message = "Teaching cancelled. Unsaved taught actions were discarded."

    def save_teaching(self):
        with self.lock:
            if not self.teach.get("active"):
                raise RuntimeError("No teaching session is active.")
            actions = list(self.teach.get("actions", []))
            if not actions:
                raise RuntimeError("Move the arm at least once before saving the taught skill.")
            snap = self.workspace.snapshot()
            payload = {
                "schema": "seizo-skill/v1",
                "name": self.teach.get("name") or "taught-skill",
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source_mode": "phone-teach",
                "metadata": {
                    "invert": dict(self.invert),
                    "workspace_reference": self.boot_id,
                    "start_position": dict(self.teach.get("started_position") or {}),
                },
                "actions": actions,
            }
            valid = validate_skill(payload)
            PHONE_SKILL_DIR.mkdir(parents=True, exist_ok=True)
            path = PHONE_SKILL_DIR / skill_filename(valid["name"])
            save_skill(path, valid)
            save_skill(LATEST_TAUGHT_SKILL, valid)
            # Keep the legacy latest-recorded path in sync for local terminal replay.
            save_skill(rr.SKILL, valid)
            count = len(valid["actions"])
            self.teach = new_teach_state()
            self.teach["last_saved_path"] = str(path)
            self.teach["last_saved_actions"] = count
            self.message = (
                f"TAUGHT SKILL SAVED: {valid['name']} ({count} actions). "
                "Automatic replay remains locked; validate the start pose and path before replay."
            )
            return {"path": str(path), "actions": count, "name": valid["name"], "end_position": snap.get("position")}

    def reset_test(self):
        with self.lock:
            self.test = new_test_state(self.boot_id)
            self._save_test()
            self.message = "Quick-test results reset."

    def retest_next_failed(self):
        with self.lock:
            for component, keys in COMPONENT_KEYS.items():
                if self.test.get("physical", {}).get(component) != "fail":
                    continue
                self.test["physical"][component] = "untested"
                for key in keys:
                    self.test["command_counts"][key] = 0
                self.test["last_key"] = None
                self.test["last_label"] = None
                self._save_test()
                pretty = {
                    "base": "Base",
                    "y": "Y reach",
                    "z": "Z height",
                    "gripper": "Gripper",
                    "wrist": "Wrist",
                }[component]
                self.message = f"{pretty} unlocked for one focused retest. Other failed components stay quarantined."
                return component
            raise RuntimeError("No failed hardware row needs retesting.")

    def status(self):
        try:
            uno_port, _ = rr.find_controller()
        except Exception:
            uno_port = None
        try:
            nano_ports = list(_candidate_ports())
        except Exception:
            nano_ports = []
        cams = camera_status()
        setup = read_json(SETUP_PATH, {}) or {}
        workspace = self.workspace.snapshot()
        auto = self.auto_gate(cams)
        nano_probe = read_json(NANO_PROBE_PATH, {}) or {}
        nano_verified = nano_probe.get("outcome") == "pass"
        return {
            "armed": self.armed,
            "boot_id": self.boot_id,
            "message": self.message,
            "uno_port": uno_port,
            "nano_ports": nano_ports,
            "nano_verified": nano_verified,
            "nano_probe": nano_probe,
            "servo_backend": self.servo_backend,
            "fast_mode": self.fast_mode,
            "invert": dict(self.invert),
            "camera_overhead": bool(cams.get("overhead_fresh")),
            "camera_wrist": bool(cams.get("wrist_fresh")),
            "automation_enabled": False,
            "automation": auto,
            "workspace": workspace,
            "auto_preview": self.auto_preview,
            "teach": {
                "active": bool(self.teach.get("active")),
                "name": str(self.teach.get("name") or "")[:80],
                "actions": len(self.teach.get("actions", [])),
                "started_position": self.teach.get("started_position"),
                "last_saved_path": self.teach.get("last_saved_path"),
                "last_saved_actions": self.teach.get("last_saved_actions", 0),
            },
            "test": self.test,
            "setup": setup,
            "session": read_json(SESSION_PATH, {}) or {},
            "selftest": read_json(SELFTEST_PATH, {}) or {},
            "last_command": self.last_command,
        }


STATE = State()


PAGE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seizo Control</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0b0e12;color:#f5f7fa;margin:0}
main{max-width:620px;margin:auto;padding:16px 14px 110px}
h1{font-size:27px;margin:2px 0}.sub{margin:4px 0 14px;color:#aab3bf}
.card{background:#171b21;border:1px solid #2a313a;border-radius:16px;padding:15px;margin:10px 0}
.status{display:flex;gap:6px;flex-wrap:wrap}.chip{font-size:12px;padding:6px 9px;border-radius:999px;background:#333a45}
.good{background:#19532f}.bad{background:#702b31}.off{background:#39404a}.warn{background:#715516}
.msg{background:#0e1217;padding:12px;border-radius:11px;line-height:1.35;margin:12px 0}
button{width:100%;border:0;border-radius:12px;background:#323945;color:white;font-weight:750;font-size:16px;min-height:54px;padding:12px}
button:active{transform:scale(.985)}button:disabled{opacity:.42}
.primary{background:#18713b}.danger{background:#a02b31}.pass{background:#195e34}.fail{background:#8a2e34}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.grid4{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.note{color:#aab3bf;font-size:13px;line-height:1.45}.eyebrow{font-size:12px;letter-spacing:.08em;color:#95a1b0;font-weight:800}
.screen[hidden]{display:none}.step{font-size:13px;color:#9fabb9;margin-bottom:5px}.title{font-size:22px;font-weight:800;margin:3px 0 8px}
.badge{display:inline-block;font-size:12px;padding:5px 8px;border-radius:999px;background:#353c46}
.row{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid #2a313a}
.row:last-child{border-bottom:0}.row b{font-size:14px}
.link{display:inline-block;color:#b9d8ff;text-decoration:underline;cursor:pointer;padding:8px 0;font-weight:700}
.cams{display:grid;grid-template-columns:1fr 1fr;gap:8px}.cams img{width:100%;aspect-ratio:4/3;object-fit:cover;background:#050607;border-radius:10px}
.sticky-stop{position:fixed;left:0;right:0;bottom:0;background:rgba(11,14,18,.95);border-top:1px solid #2a313a;padding:10px 14px 14px;z-index:20}
.sticky-stop .inner{max-width:620px;margin:auto}.sticky-stop button{min-height:58px}
#busy{display:none;color:#ffd56a;font-size:13px;margin-top:8px}
.control-name{font-weight:850;font-size:18px;margin-bottom:8px}
.result{font-size:13px;color:#aab3bf;margin-top:10px}
input{width:100%;min-height:48px;border:1px solid #3a424d;border-radius:10px;background:#0e1217;color:#fff;padding:10px 12px;font-size:16px;margin:8px 0 12px}
@media(max-width:500px){.cams{grid-template-columns:1fr}.grid2,.grid4{gap:7px}}
</style>
</head>
<body data-seizo-page="SEIZO_MANUAL_WEB_OK"><main>
<h1>Seizo</h1>
<p class="sub">Guided control. One step at a time.</p>

<div class="card">
  <div class="status">
    <span class="chip good">WEB ONLINE</span>
    <span id="uno" class="chip">Uno…</span>
    <span id="nano" class="chip">Nano…</span>
    <span id="cams" class="chip">Cameras…</span>
  </div>
  <div id="message" class="msg">Loading…</div>
  <div id="busy">Working…</div>
</div>

<section id="screen-start" class="screen card">
  <div class="eyebrow">START</div>
  <div class="title">Get the arm ready</div>
  <p class="note">Keep the physical kill switch reachable. ARM only enables bounded manual commands.</p>
  <div class="grid2">
    <button class="primary" onclick="armNow()">ARM MANUAL</button>
    <button onclick="openCameras('start')">CAMERAS</button>
    <button onclick="showScreen('automatic')">AUTOMATIC SETUP</button>
  </div>
</section>

<section id="screen-test" class="screen card" hidden>
  <div id="test-step" class="step">TEST 1 OF 5</div>
  <div id="test-title" class="title">Base rotation</div>
  <p id="test-help" class="note">Tap both directions once while watching the robot. Then mark the result.</p>
  <div class="grid2">
    <button id="test-neg" onclick="runTestMove(-1)">←</button>
    <button id="test-pos" onclick="runTestMove(1)">→</button>
    <button class="pass" onclick="finishTest('pass')">PASS</button>
    <button class="fail" onclick="finishTest('fail')">FAIL</button>
  </div>
  <div id="test-result" class="result"></div>
</section>

<section id="screen-summary" class="screen card" hidden>
  <div class="eyebrow">READY</div>
  <div class="title">What do you want to do?</div>
  <div id="test-summary"></div>
  <div class="grid2" style="margin-top:10px">
    <button class="primary" onclick="showScreen('controls')">MANUAL DRIVE</button>
    <button onclick="showScreen('automatic')">AUTOMATIC SETUP</button>
    <button onclick="retestNextFail()">RETEST NEXT FAIL</button>
    <button onclick="showScreen('directions')">FIX DIRECTION</button>
  </div>
</section>

<section id="screen-controls" class="screen card" hidden>
  <div class="eyebrow">MANUAL DRIVE</div>
  <div class="title">Choose a control</div>
  <div class="grid2">
    <button onclick="showScreen('xy')">BASE + REACH</button>
    <button onclick="showScreen('height')">HEIGHT</button>
    <button onclick="showScreen('hand')">HAND + WRIST</button>
    <button onclick="showScreen('summary')">BACK</button>
  </div>
  <span class="link" onclick="showScreen('teach')">TEACH SKILL STATUS</span>
</section>

<section id="screen-xy" class="screen card" hidden>
  <div class="control-name">Base + Reach</div>
  <div class="grid4">
    <button onclick="move('a')">← BASE</button>
    <button onclick="move('d')">BASE →</button>
    <button onclick="move('w')">REACH +</button>
    <button onclick="move('s')">REACH −</button>
  </div>
  <span class="link" onclick="showScreen('controls')">← Change control</span>
</section>

<section id="screen-height" class="screen card" hidden>
  <div class="control-name">Height</div>
  <div class="grid2">
    <button onclick="move('q')">Z ↑</button>
    <button onclick="move('e')">Z ↓</button>
  </div>
  <span class="link" onclick="showScreen('controls')">← Change control</span>
</section>

<section id="screen-hand" class="screen card" hidden>
  <div class="control-name">Hand + Wrist</div>
  <div class="grid4">
    <button onclick="move('n')">OPEN</button>
    <button onclick="move('m')">CLOSE</button>
    <button onclick="move('o')">WRIST −</button>
    <button onclick="move('p')">WRIST +</button>
  </div>
  <span class="link" onclick="verifyNano()">VERIFY NANO · NO MOTION</span><br>
  <span class="link" onclick="showScreen('controls')">← Change control</span>
</section>

<section id="screen-directions" class="screen card" hidden>
  <div class="eyebrow">DIRECTION FIX</div>
  <div class="title">Only use this if an axis is backwards</div>
  <div class="grid2">
    <button onclick="flip('X')">REVERSE BASE</button>
    <button onclick="flip('Y')">REVERSE REACH</button>
    <button onclick="flip('Z')">REVERSE HEIGHT</button>
    <button onclick="showScreen('summary')">BACK</button>
  </div>
  <p id="dirs" class="note"></p>
</section>

<section id="screen-cameras" class="screen card" hidden>
  <div class="eyebrow">CAMERAS</div>
  <div class="title">Live view</div>
  <div class="cams"><img id="over" alt="Overhead camera"><img id="wrist" alt="Wrist camera"></div>
  <div class="grid2" style="margin-top:10px">
    <button onclick="refresh()">REFRESH STATUS</button>
    <button onclick="showScreen(cameraBack)">BACK</button>
  </div>
</section>

<section id="screen-automatic" class="screen card" hidden>
  <div class="eyebrow">AUTOMATIC SETUP</div>
  <div class="title">Build the safety gates</div>
  <div class="row"><b>Hardware test</b><span id="auto-hardware" class="badge">CHECKING</span></div>
  <div class="row"><b>Two cameras</b><span id="auto-cameras" class="badge">CHECKING</span></div>
  <div class="row"><b>Session HOME</b><span id="auto-home" class="badge">NOT SET</span></div>
  <div class="row"><b>Safe travel limits</b><span id="auto-limits" class="badge">NOT SET</span></div>
  <div class="row"><b>Planner</b><span id="auto-planner" class="badge">LOCKED</span></div>
  <p id="auto-next" class="note">Checking the next required step…</p>
  <div class="grid2">
    <button id="auto-primary" class="primary" onclick="autoNext()">NEXT</button>
    <button onclick="openCameras('automatic')">CAMERAS</button>
    <button onclick="goHome()">BACK TO MANUAL</button>
  </div>
</section>

<section id="screen-auto-home" class="screen card" hidden>
  <div class="eyebrow">AUTOMATIC SETUP / HOME</div>
  <div class="title">Choose a repeatable HOME pose</div>
  <p class="note">Put the arm in a safe, repeatable pose. This becomes X0 Y0 Z0 for this session. Until physical homing switches are installed, HOME and its travel limits are both forgotten after STOP/DISARM or restart.</p>
  <p id="auto-home-position" class="msg">Position: not referenced</p>
  <div class="grid2">
    <button class="primary" onclick="setHome()">SET CURRENT POSE AS HOME</button>
    <button onclick="clearHome()">CLEAR HOME</button>
    <button onclick="showScreen('automatic')">BACK</button>
  </div>
</section>

<section id="screen-auto-limits" class="screen card" hidden>
  <div id="limit-step" class="step">SAFE LIMIT 1 OF 3</div>
  <div id="limit-title" class="title">Base</div>
  <p class="note">Move only to a conservative safe point. Do not use the hard mechanical stop. Save both SAFE MIN and SAFE MAX.</p>
  <p id="limit-position" class="msg">Position: --</p>
  <div class="grid2">
    <button id="limit-neg" onclick="limitMove(-1)">MOVE −</button>
    <button id="limit-pos" onclick="limitMove(1)">MOVE +</button>
    <button onclick="saveLimit('min')">SAVE SAFE MIN</button>
    <button onclick="saveLimit('max')">SAVE SAFE MAX</button>
  </div>
  <span class="link" onclick="cancelLimits()">Cancel limit calibration</span>
</section>

<section id="screen-auto-return" class="screen card" hidden>
  <div class="eyebrow">RETURN TO HOME</div>
  <div id="return-title" class="title">Base → 0</div>
  <p class="note">Bring this axis back to its tracked HOME coordinate before continuing.</p>
  <p id="return-position" class="msg">Position: --</p>
  <div class="grid2">
    <button id="return-neg" onclick="limitMove(-1)">MOVE −</button>
    <button id="return-pos" onclick="limitMove(1)">MOVE +</button>
    <button class="primary" onclick="confirmAxisHome()">AT HOME / NEXT</button>
  </div>
  <span class="link" onclick="cancelLimits()">Cancel limit calibration</span>
</section>

<section id="screen-auto-preview" class="screen card" hidden>
  <div class="eyebrow">PLANNER DRY RUN</div>
  <div class="title">Validate without moving</div>
  <p class="note">This checks a bounded out-and-back XYZ plan against hardware status, cameras, HOME, and software limits. It sends zero physical commands.</p>
  <pre id="preview-result" class="msg" style="white-space:pre-wrap">No dry run yet.</pre>
  <div class="grid2">
    <button class="primary" onclick="plannerDryRun()">RUN DRY CHECK</button>
    <button onclick="showScreen('teach')">TEACH SKILL</button>
    <button onclick="showScreen('automatic')">BACK</button>
  </div>
</section>

<section id="screen-teach" class="screen card" hidden>
  <div class="eyebrow">TEACH SKILL</div>
  <div class="title">Demonstrate with manual controls</div>
  <p class="note">Teaching records only the bounded manual commands you make. It does not enable automatic motion or replay.</p>
  <input id="teach-name" maxlength="80" placeholder="Skill name, e.g. pick-front-center">
  <div id="teach-status" class="msg">Not recording.</div>
  <div class="grid2">
    <button id="teach-start" class="primary" onclick="startTeach()">START TEACHING</button>
    <button onclick="teachManual()">MANUAL DRIVE</button>
    <button id="teach-save" onclick="saveTeach()">SAVE SKILL</button>
    <button id="teach-cancel" onclick="cancelTeach()">CANCEL</button>
  </div>
</section>

<p class="note"><b>Safety:</b> software STOP is not an E-stop. The physical kill switch is the emergency stop. No homing switches or encoders are installed yet.</p>
</main>

<div class="sticky-stop"><div class="inner"><button class="danger" onclick="stopNow()">STOP / DISARM</button></div></div>

<script>
const host=location.hostname || 'seizo-pi.local';
document.getElementById('over').src='http://'+host+':8787/overhead.mjpg';
document.getElementById('wrist').src='http://'+host+':8787/wrist.mjpg';

const tests=[
  {name:'Base rotation',neg:'a',pos:'d',negLabel:'← BASE',posLabel:'BASE →'},
  {name:'Reach',neg:'s',pos:'w',negLabel:'REACH −',posLabel:'REACH +'},
  {name:'Height',neg:'e',pos:'q',negLabel:'Z ↓',posLabel:'Z ↑'},
  {name:'Gripper',neg:'n',pos:'m',negLabel:'OPEN',posLabel:'CLOSE'},
  {name:'Wrist',neg:'o',pos:'p',negLabel:'WRIST −',posLabel:'WRIST +'}
];
const componentNames=['base','y','z','gripper','wrist'];
const autoAxes=[
  {axis:'X',name:'Base',neg:'a',pos:'d',step:3.0},
  {axis:'Y',name:'Reach',neg:'s',pos:'w',step:3.0},
  {axis:'Z',name:'Height',neg:'e',pos:'q',step:1.5}
];
let latest=null,currentTest=0,lastScreen='start',limitAxis=0,cameraBack='start',testBack='summary';

function allScreens(){return [...document.querySelectorAll('.screen')]}
function showScreen(name){
  allScreens().forEach(x=>x.hidden=true);
  const e=document.getElementById('screen-'+name);
  if(e)e.hidden=false;
  lastScreen=name;
  if(name==='test') renderTest();
  if(name==='summary') renderSummary();
  if(name==='automatic') renderAutomatic();
  if(name==='auto-home') renderAutoHome();
  if(name==='auto-limits') renderLimit();
  if(name==='auto-return') renderReturn();
  if(name==='auto-preview') renderPreview();
  if(name==='teach') renderTeach();
}
function openCameras(back){
  cameraBack=back||'start';
  showScreen('cameras');
}
function goHome(){
  if(latest && latest.armed){
    const next=firstUnfinished(latest);
    showScreen(next<tests.length?'test':'summary');
  }else showScreen('start');
}
function firstUnfinished(s){
  for(let i=0;i<componentNames.length;i++){
    const v=((s.test||{}).physical||{})[componentNames[i]]||'untested';
    if(v==='untested')return i;
  }
  return tests.length;
}
function hasFailedHardware(s){
  const p=((s||{}).test||{}).physical||{};
  return componentNames.some(n=>p[n]==='fail');
}
function firstIncompleteLimitAxis(s){
  const limits=((s||{}).workspace||{}).limits||{};
  for(let i=0;i<autoAxes.length;i++){
    const lim=limits[autoAxes[i].axis]||{};
    if(lim.min==null || lim.max==null)return i;
  }
  return autoAxes.length-1;
}
function renderTest(){
  const t=tests[currentTest];
  document.getElementById('test-step').textContent='TEST '+(currentTest+1)+' OF '+tests.length;
  document.getElementById('test-title').textContent=t.name;
  document.getElementById('test-neg').textContent=t.negLabel;
  document.getElementById('test-pos').textContent=t.posLabel;
  document.getElementById('test-result').textContent='';
}
function renderSummary(){
  if(!latest)return;
  const p=(latest.test||{}).physical||{};
  document.getElementById('test-summary').innerHTML=componentNames.map((n,i)=>{
    const v=p[n]||'untested';
    return '<div class="row"><b>'+tests[i].name+'</b><span class="badge '+(v==='pass'?'good':v==='fail'?'bad':'off')+'">'+v.toUpperCase()+'</span></div>';
  }).join('');
}
function renderAutomatic(){
  if(!latest)return;
  const a=latest.automation||{};
  setAutoBadge('auto-hardware',a.hardware_pass?'PASS':'NOT READY',a.hardware_pass?'good':'warn');
  setAutoBadge('auto-cameras',a.cameras_live?'LIVE':'NOT READY',a.cameras_live?'good':'warn');
  setAutoBadge('auto-home',a.home_reference_valid?'SET':'NOT SET',a.home_reference_valid?'good':'warn');
  setAutoBadge('auto-limits',a.travel_limits_configured?'SET':'NOT SET',a.travel_limits_configured?'good':'warn');
  setAutoBadge('auto-planner',a.ready_for_planning?'READY':'LOCKED',a.ready_for_planning?'good':'off');
  const labels={
    TEST_HARDWARE:'Finish the five hardware checks first.',
    CHECK_CAMERAS:'Both cameras must be live.',
    SET_HOME:'Set a repeatable HOME pose for this session.',
    CALIBRATE_LIMITS:'Capture conservative safe travel limits.',
    ARM_MANUAL:'ARM MANUAL before planner validation.',
    PLANNER_READY:'All planning gates pass. Run the no-motion planner dry check.'
  };
  document.getElementById('auto-next').textContent=labels[a.next_step]||('Blocked: '+(a.blockers||[]).join(', '));
  const buttonLabels={
    ARM_MANUAL:'ARM MANUAL',
    TEST_HARDWARE:'TEST HARDWARE',
    CHECK_CAMERAS:'CHECK CAMERAS',
    SET_HOME:'SET HOME',
    CALIBRATE_LIMITS:'CALIBRATE LIMITS',
    PLANNER_READY:'PLANNER DRY RUN'
  };
  document.getElementById('auto-primary').textContent=buttonLabels[a.next_step]||'REFRESH';
}
async function autoNext(){
  if(!latest)return;
  const step=((latest||{}).automation||{}).next_step;
  if(step==='ARM_MANUAL'){
    try{await act('/arm');showScreen('automatic')}catch(e){}
    return;
  }
  if(step==='TEST_HARDWARE'){
    try{
      if(!latest.armed)await act('/arm');
      if(hasFailedHardware(latest))await act('/retest-next-fail');
      testBack='automatic';
      currentTest=firstUnfinished(latest);
      showScreen(currentTest<tests.length?'test':'automatic');
    }catch(e){}
    return;
  }
  if(step==='CHECK_CAMERAS'){openCameras('automatic');return}
  if(step==='SET_HOME'){showScreen('auto-home');return}
  if(step==='CALIBRATE_LIMITS'){await startLimits();return}
  if(step==='PLANNER_READY'){showScreen('auto-preview');return}
  await refresh(false);
  renderAutomatic();
}
function renderAutoHome(){
  if(!latest)return;
  const w=latest.workspace||{};
  const p=w.position||{};
  document.getElementById('auto-home-position').textContent=w.reference_valid?
    'Tracked position: X '+fmt(p.X)+' · Y '+fmt(p.Y)+' · Z '+fmt(p.Z):
    'Position: not referenced yet';
}
function fmt(v){return Number(v||0).toFixed(1)+' mm'}
function axisState(){
  const a=autoAxes[limitAxis];
  const w=(latest||{}).workspace||{};
  const p=w.position||{};
  const lim=(w.limits||{})[a.axis]||{};
  return {a,w,p,lim};
}
function renderLimit(){
  if(!latest)return;
  const {a,p,lim}=axisState();
  document.getElementById('limit-step').textContent='SAFE LIMIT '+(limitAxis+1)+' OF '+autoAxes.length;
  document.getElementById('limit-title').textContent=a.name;
  document.getElementById('limit-neg').textContent=a.name+' −';
  document.getElementById('limit-pos').textContent=a.name+' +';
  document.getElementById('limit-position').textContent=
    'Current '+a.axis+': '+fmt(p[a.axis])+' · MIN '+(lim.min==null?'--':fmt(lim.min))+' · MAX '+(lim.max==null?'--':fmt(lim.max));
}
function renderReturn(){
  if(!latest)return;
  const {a,p}=axisState();
  document.getElementById('return-title').textContent=a.name+' → HOME 0';
  document.getElementById('return-neg').textContent=a.name+' −';
  document.getElementById('return-pos').textContent=a.name+' +';
  document.getElementById('return-position').textContent='Current '+a.axis+': '+fmt(p[a.axis]);
}
function renderPreview(){
  if(!latest)return;
  const p=latest.auto_preview;
  document.getElementById('preview-result').textContent=p?JSON.stringify(p,null,2):
    'No dry run yet. All readiness gates must pass first.';
}
function renderTeach(){
  if(!latest)return;
  const t=latest.teach||{};
  const a=latest.automation||{};
  const active=!!t.active;
  document.getElementById('teach-name').disabled=active;
  if(active && t.name)document.getElementById('teach-name').value=t.name;
  document.getElementById('teach-start').disabled=active || !a.ready_for_planning;
  document.getElementById('teach-save').disabled=!active || Number(t.actions||0)<1;
  document.getElementById('teach-cancel').disabled=!active;
  let text=active?
    ('RECORDING · '+(t.name||'skill')+' · '+Number(t.actions||0)+' actions'):
    'Not recording.';
  if(!active && t.last_saved_path)text+=' Last saved: '+Number(t.last_saved_actions||0)+' actions.';
  if(!a.ready_for_planning && !active)text+=' Finish hardware, cameras, HOME, and safe limits first.';
  document.getElementById('teach-status').textContent=text;
}
async function setHome(){
  try{await act('/auto/home');showScreen('automatic')}catch(e){}
}
async function clearHome(){
  try{await act('/auto/home-clear');showScreen('automatic')}catch(e){}
}
async function startLimits(){
  try{
    const w=(latest||{}).workspace||{};
    if(w.calibrating){
      limitAxis=firstIncompleteLimitAxis(latest);
      const lim=(w.limits||{})[autoAxes[limitAxis].axis]||{};
      if(lim.min!=null && lim.max!=null)showScreen('auto-return');
      else showScreen('auto-limits');
      return;
    }
    await act('/auto/cal-start',{reset:'1'});
    limitAxis=0;
    showScreen('auto-limits');
  }catch(e){}
}
async function limitMove(dir){
  const a=autoAxes[limitAxis];
  await move(dir<0?a.neg:a.pos);
  if(lastScreen==='auto-limits')renderLimit();
  if(lastScreen==='auto-return')renderReturn();
}
async function saveLimit(bound){
  const a=autoAxes[limitAxis];
  try{
    await act('/auto/limit',{axis:a.axis,bound});
    const lim=(((latest||{}).workspace||{}).limits||{})[a.axis]||{};
    if(lim.min!=null && lim.max!=null)showScreen('auto-return');
    else renderLimit();
  }catch(e){}
}
async function confirmAxisHome(){
  if(!latest)return;
  const {a,p}=axisState();
  const tolerance=a.step/2+0.01;
  if(Math.abs(Number(p[a.axis]||0))>tolerance){
    document.getElementById('message').textContent='Return '+a.name+' closer to HOME 0 before continuing.';
    return;
  }
  if(limitAxis<autoAxes.length-1){
    limitAxis+=1;
    showScreen('auto-limits');
    return;
  }
  try{
    await act('/auto/cal-done');
    showScreen('automatic');
  }catch(e){}
}
async function cancelLimits(){
  try{await act('/auto/cal-cancel')}catch(e){}
  showScreen('automatic');
}
async function plannerDryRun(){
  try{
    await act('/auto/dry-run');
    renderPreview();
  }catch(e){renderPreview()}
}
async function startTeach(){
  const name=document.getElementById('teach-name').value||'';
  try{await act('/teach/start',{name});renderTeach()}catch(e){renderTeach()}
}
function teachManual(){showScreen('controls')}
async function saveTeach(){
  try{await act('/teach/save');renderTeach()}catch(e){renderTeach()}
}
async function cancelTeach(){
  try{await act('/teach/cancel');renderTeach()}catch(e){renderTeach()}
}

async function post(path,data={}){
  const r=await fetch(path,{method:'POST',headers:{
    'Content-Type':'application/x-www-form-urlencoded',
    'X-Seizo-Control':'guided-v1'
  },body:new URLSearchParams(data)});
  let obj={};try{obj=await r.json()}catch(e){}
  if(!r.ok)throw new Error(obj.error||('HTTP '+r.status));
  return obj;
}
async function act(path,data={}){
  document.getElementById('busy').style.display='block';
  try{return await post(path,data)}
  catch(e){document.getElementById('message').textContent='ERROR: '+e.message;throw e}
  finally{document.getElementById('busy').style.display='none';await refresh(false)}
}
async function armNow(){
  try{
    await act('/arm');
    testBack='summary';
    currentTest=firstUnfinished(latest);
    showScreen(currentTest<tests.length?'test':'summary');
  }catch(e){}
}
async function stopNow(){
  try{await act('/stop')}catch(e){}
  showScreen('start');
}
function move(key){return act('/move',{key}).catch(()=>{})}
async function verifyNano(){try{await act('/nano-probe')}catch(e){}}
function flip(axis){return act('/flip',{axis}).catch(()=>{})}
async function runTestMove(dir){
  const t=tests[currentTest];
  await move(dir<0?t.neg:t.pos);
}
async function finishTest(outcome){
  try{
    await act('/report',{component:componentNames[currentTest],outcome});
    currentTest=firstUnfinished(latest);
    showScreen(currentTest<tests.length?'test':testBack);
  }catch(e){
    document.getElementById('test-result').textContent='Test both movement buttons first.';
  }
}
async function retestNextFail(){
  try{
    const r=await act('/retest-next-fail');
    testBack='summary';
    currentTest=firstUnfinished(latest);
    showScreen(currentTest<tests.length?'test':'summary');
  }catch(e){}
}
function chip(id,text,ok){
  const e=document.getElementById(id);e.textContent=text;e.className='chip '+(ok?'good':'bad');
}
function setAutoBadge(id,text,cls){
  const e=document.getElementById(id);e.textContent=text;e.className='badge '+cls;
}
async function refresh(navigate=true){
  try{
    const r=await fetch('/api/status',{cache:'no-store'});
    const s=await r.json();latest=s;
    chip('uno',s.uno_port?'Uno READY':'Uno missing',!!s.uno_port);
    chip('nano',s.nano_verified?'Nano VERIFIED':(s.nano_ports.length?'Nano USB ONLY':'Nano missing'),!!s.nano_verified);
    chip('cams',(s.camera_overhead&&s.camera_wrist)?'2 CAMERAS LIVE':'Camera issue',s.camera_overhead&&s.camera_wrist);
    document.getElementById('message').textContent=(s.armed?'ARMED · ':'DISARMED · ')+s.message;
    document.getElementById('dirs').textContent='Current reverse settings: Base '+s.invert.X+' · Reach '+s.invert.Y+' · Height '+s.invert.Z;
    if(lastScreen==='summary')renderSummary();
    if(lastScreen==='automatic')renderAutomatic();
    if(lastScreen==='auto-home')renderAutoHome();
    if(lastScreen==='auto-limits')renderLimit();
    if(lastScreen==='auto-return')renderReturn();
    if(lastScreen==='auto-preview')renderPreview();
    if(lastScreen==='teach')renderTeach();
    if(navigate && lastScreen==='start' && s.armed){
      currentTest=firstUnfinished(s);
      showScreen(currentTest<tests.length?'test':'summary');
    }
  }catch(e){
    document.getElementById('message').textContent='Website status error: '+e.message;
  }
}
refresh();setInterval(()=>refresh(false),2000);
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        return

    def origin_ok(self):
        host = self.headers.get("Host", "")
        try:
            parsed = urlsplit("http://" + host)
            name = parsed.hostname
            if not name or parsed.username or parsed.password or parsed.path:
                return False
            allowed = name in {
                "localhost", "127.0.0.1", "seizo-pi", "seizo-pi.local",
                socket.gethostname(), socket.gethostname() + ".local",
            }
            if not allowed:
                ip = ipaddress.ip_address(name)
                allowed = (ip.is_private or ip.is_loopback) and not ip.is_unspecified
            if not allowed or parsed.port != PORT:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin == "http://" + host
        except (ValueError, TypeError):
            return False

    def send_bytes(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' http:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, code, payload):
        self.send_bytes(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if not self.origin_ok():
            return self.send_json(403, {"error": "Open Seizo from its local Pi address."})
        if self.path == "/":
            return self.send_bytes(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if self.path == "/healthz":
            return self.send_json(200, {
                "ok": True,
                "release": WEB_RELEASE,
                "page_marker": PAGE_MARKER,
                "page_bytes": len(PAGE.encode("utf-8")),
            })
        if self.path == "/api/status":
            return self.send_json(200, STATE.status())
        return self.send_error(404)

    def do_POST(self):
        if not self.origin_ok():
            return self.send_json(403, {"error": "Cross-origin control request blocked."})
        if self.headers.get("X-Seizo-Control") != "guided-v1":
            return self.send_json(403, {"error": "Missing Seizo control header."})
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            return self.send_json(415, {"error": "Form body required."})
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            return self.send_json(400, {"error": "Invalid request length."})
        if n < 0 or n > 2048:
            return self.send_json(413, {"error": "Request too large."})
        q = parse_qs(self.rfile.read(n).decode("utf-8", errors="replace"))
        try:
            if self.path == "/arm":
                STATE.arm()
            elif self.path == "/stop":
                STATE.stop_now()
            elif self.path == "/move":
                STATE.step(q.get("key", [""])[0])
            elif self.path == "/nano-probe":
                STATE.nano_probe_now()
            elif self.path == "/vector":
                STATE.vector_move(
                    q.get("x", ["0"])[0],
                    q.get("y", ["0"])[0],
                    q.get("z", ["0"])[0],
                )
            elif self.path == "/speed":
                STATE.set_speed_mode(q.get("mode", ["normal"])[0])
            elif self.path == "/report":
                STATE.report_component(q.get("component", [""])[0], q.get("outcome", [""])[0])
            elif self.path == "/flip":
                STATE.flip_axis(q.get("axis", [""])[0])
            elif self.path == "/reset-test":
                STATE.reset_test()
            elif self.path == "/retest-next-fail":
                STATE.retest_next_failed()
            elif self.path == "/auto/home":
                STATE.set_home_reference()
            elif self.path == "/auto/home-clear":
                STATE.clear_home_reference()
            elif self.path == "/auto/cal-start":
                STATE.start_limit_calibration(q.get("reset", ["0"])[0] == "1")
            elif self.path == "/auto/limit":
                STATE.capture_limit(q.get("axis", [""])[0], q.get("bound", [""])[0])
            elif self.path == "/auto/cal-done":
                STATE.finish_limit_calibration()
            elif self.path == "/auto/cal-cancel":
                STATE.cancel_limit_calibration()
            elif self.path == "/auto/limits-clear":
                STATE.clear_limits()
            elif self.path == "/auto/dry-run":
                STATE.planner_dry_run()
            elif self.path == "/teach/start":
                STATE.start_teaching(q.get("name", [""])[0])
            elif self.path == "/teach/save":
                STATE.save_teaching()
            elif self.path == "/teach/cancel":
                STATE.cancel_teaching()
            else:
                return self.send_error(404)
            return self.send_json(200, STATE.status())
        except Exception as exc:
            STATE.message = "ERROR: " + type(exc).__name__ + ": " + str(exc)
            return self.send_json(409, {"ok": False, "error": STATE.message})

    def do_HEAD(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        return self.send_error(404)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Seizo manual test: http://seizo-pi.local:{PORT}/")
    try:
        server.serve_forever()
    finally:
        STATE.stop_now()
        server.server_close()


if __name__ == "__main__":
    main()
