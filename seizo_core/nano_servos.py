"""Arduino Nano USB servo backend for Seizo.

Pi <-> Nano: USB serial @115200.
Nano D9  -> gripper servo signal.
Nano D10 -> wrist servo signal.

Servo power remains external 5V with shared ground.
The Nano is USB-powered from the Pi and must NOT power the servos.
"""
from __future__ import annotations

import glob
import subprocess
import time

from seizo_core.controller_inventory import is_expected_nano_props

BAUD = 115200
HANDSHAKE = "SEIZO_NANO_SERVO_V1"
UNO_SERIAL = "24333313131351101271"

GRIPPER_OPEN_US = 1400
GRIPPER_CLOSE_US = 1600
GRIPPER_BOOTSTRAP_US = 1500

WRIST_HOME_US = 1500
WRIST_STEP_US = 20
WRIST_MIN_US = 1400
WRIST_MAX_US = 1600


class NanoServoError(RuntimeError):
    pass


def _udev(path):
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
                k, v = line.split("=", 1)
                props[k] = v
    return props


def _candidate_ports():
    """Return only USB devices matching the current Nano identity.

    Do not probe every non-Uno serial device. In particular, the still-installed
    ESP32 uses a different USB bridge and must never receive Nano HELLO/PING or
    provisioning traffic while it remains in the robot.
    """
    ports = []
    for path in sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))):
        props = _udev(path)
        if props.get("ID_SERIAL_SHORT") == UNO_SERIAL:
            continue
        if not is_expected_nano_props(props):
            continue
        ports.append(path)
    return ports


def _open_verified_nano(timeout_s=0.8):
    """Open and verify one Seizo Nano, keeping the verified port open.

    This avoids the old double-reset path where discovery opened/closed the Nano
    and NanoServoController immediately opened it again.
    """
    try:
        import serial
    except Exception as exc:
        raise NanoServoError("pyserial unavailable: " + str(exc)) from exc

    for port in _candidate_ports():
        ser = None
        try:
            ser = serial.Serial(port, BAUD, timeout=0.15, write_timeout=0.5)
            time.sleep(1.8)  # allow Nano bootloader/reset to finish
            ser.reset_input_buffer()
            ser.write(b"HELLO\n")
            ser.flush()
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                line = ser.readline().decode("ascii", errors="replace").strip()
                if line == HANDSHAKE:
                    return port, ser
        except Exception:
            pass
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
    raise NanoServoError("No flashed Seizo Nano servo controller found. Run: python3 scripts/provision_nano_servo.py")


def find_nano_port(timeout_s=0.8):
    port, ser = _open_verified_nano(timeout_s=timeout_s)
    try:
        return port
    finally:
        try:
            ser.close()
        except Exception:
            pass


class NanoServoController:
    def __init__(self, port=None):
        try:
            import serial
        except Exception as exc:
            raise NanoServoError("pyserial unavailable: " + str(exc)) from exc

        if port is None:
            self.port, self.ser = _open_verified_nano()
            self.ser.timeout = 0.25
            self.ser.write_timeout = 0.5
        else:
            self.port = port
            self.ser = serial.Serial(self.port, BAUD, timeout=0.25, write_timeout=0.5)
            time.sleep(1.8)
            self._hello()
        self.gripper_us = None
        self.wrist_us = None
        self.active = None
        self.closed = False

    def _hello(self):
        reply = self._command("HELLO")
        if reply != HANDSHAKE:
            raise NanoServoError("Unexpected Nano handshake: " + repr(reply))

    def _command(self, line):
        self.ser.reset_input_buffer()
        self.ser.write((line + "\n").encode("ascii"))
        self.ser.flush()
        reply = self.ser.readline().decode("ascii", errors="replace").strip()
        if not reply:
            raise NanoServoError("No reply from Nano for " + line)
        if reply.startswith("ERR"):
            raise NanoServoError(reply)
        return reply

    def _set(self, channel, pulse_us):
        pulse_us = int(pulse_us)
        if channel == "GRIP":
            if not GRIPPER_OPEN_US <= pulse_us <= GRIPPER_CLOSE_US:
                raise NanoServoError("Gripper pulse outside safe range.")
        elif channel == "WRIST":
            if not WRIST_MIN_US <= pulse_us <= WRIST_MAX_US:
                raise NanoServoError("Wrist pulse outside safe range.")
        else:
            raise NanoServoError("Unknown Nano servo channel.")

        reply = self._command(channel + " " + str(pulse_us))
        self.active = "gripper" if channel == "GRIP" else "wrist"
        if channel == "GRIP":
            self.gripper_us = pulse_us
        else:
            self.wrist_us = pulse_us
        return reply

    def _ensure_gripper_reference(self):
        if self.gripper_us is None:
            self._set("GRIP", GRIPPER_BOOTSTRAP_US)
            time.sleep(0.30)
            return True
        return False

    def _ensure_wrist_reference(self):
        if self.wrist_us is None:
            self._set("WRIST", WRIST_HOME_US)
            time.sleep(0.30)
            return True
        return False

    def gripper_set(self, target):
        first = self._ensure_gripper_reference()
        before = int(self.gripper_us)
        after = GRIPPER_OPEN_US if target == "open" else GRIPPER_CLOSE_US if target == "close" else None
        if after is None:
            raise NanoServoError("Gripper target must be open or close.")
        self._set("GRIP", after)
        return {"type":"gripper_set","target":target,"from_us":before,"to_us":after,
                "bootstrap_used":first,"backend":"nano","port":self.port}

    def gripper_to_us(self, pulse_us):
        self._ensure_gripper_reference()
        before = int(self.gripper_us)
        target = int(pulse_us)
        self._set("GRIP", target)
        return {"type":"gripper_set","from_us":before,"to_us":target,
                "backend":"nano","port":self.port}

    def wrist_step(self, direction):
        if direction not in (-1, 1):
            raise NanoServoError("Wrist direction must be -1 or +1.")
        first = self._ensure_wrist_reference()
        before = int(self.wrist_us)
        after = before + direction * WRIST_STEP_US
        self._set("WRIST", after)
        return {"type":"wrist_set","from_us":before,"to_us":after,
                "delta_us":after-before,"bootstrap_used":first,
                "backend":"nano","port":self.port}

    def wrist_to_us(self, pulse_us):
        self._ensure_wrist_reference()
        before = int(self.wrist_us)
        target = int(pulse_us)
        self._set("WRIST", target)
        return {"type":"wrist_set","from_us":before,"to_us":target,
                "backend":"nano","port":self.port}

    def snapshot(self):
        return {"backend":"nano","port":self.port,"active_servo_signal":self.active,
                "gripper_command_us":self.gripper_us,"wrist_command_us":self.wrist_us,
                "gripper_nano_pin":"D9","wrist_nano_pin":"D10",
                "actual_position_measured":False}

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        try:
            self._command("OFF ALL")
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass
