"""Small GRBL compatibility helpers for Seizo's current Arduino controller.

Current proven controller: Grbl 0.9j on Arduino Uno @ 115200.
This module deliberately avoids Grbl 1.1-only $J jogging when the controller is 0.9.
"""
from __future__ import annotations

import time


class GrblError(RuntimeError):
    pass


def read_for(ser, seconds: float) -> bytes:
    end = time.monotonic() + seconds
    data = bytearray()
    while time.monotonic() < end:
        chunk = ser.read(4096)
        if chunk:
            data.extend(chunk)
        else:
            time.sleep(0.01)
    return bytes(data)


def query_status(ser, seconds: float = 0.5) -> str:
    ser.reset_input_buffer()
    ser.write(b"?")
    ser.flush()
    raw = read_for(ser, seconds).decode("ascii", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("<") and line.endswith(">"):
            return line
    return ""


def wait_idle(ser, timeout: float = 6.0) -> str:
    end = time.monotonic() + timeout
    last = ""
    while time.monotonic() < end:
        last = query_status(ser, 0.18)
        if last.lower().startswith("<idle"):
            return last
        if last.lower().startswith(("<alarm", "<hold", "<door")):
            raise GrblError(f"GRBL blocks motion: {last}")
    raise GrblError(f"GRBL did not become Idle: {last or 'no status'}")


def line_expect_ok(ser, line: str, timeout: float = 1.5) -> list[str]:
    ser.reset_input_buffer()
    ser.write((line + "\r\n").encode("ascii"))
    ser.flush()
    end = time.monotonic() + timeout
    lines: list[str] = []
    while time.monotonic() < end:
        raw = ser.readline()
        if not raw:
            time.sleep(0.01)
            continue
        text = raw.decode("ascii", errors="replace").strip()
        if not text:
            continue
        lines.append(text)
        low = text.lower()
        if low == "ok":
            return lines
        if low.startswith("error:") or low.startswith("alarm:"):
            raise GrblError(text)
    raise GrblError(f"No GRBL ok for line: {line!r}; replies={lines[-6:]}")


def read_parser_state(ser) -> str:
    ser.reset_input_buffer()
    ser.write(b"$G\r\n")
    ser.flush()
    raw = read_for(ser, 0.8).decode("ascii", errors="replace")
    return raw


def require_manual_parser_state(ser) -> str:
    raw = read_parser_state(ser)
    upper = raw.upper()
    if "G21" not in upper or "G90" not in upper:
        raise GrblError(f"Manual mode requires current G21/G90 parser state. Raw: {raw[:300]}")
    return raw


def controlled_incremental_move(ser, axis: str, delta_mm: float, feed_mm_min: float) -> dict:
    axis = axis.upper()
    if axis not in {"X", "Y", "Z"}:
        raise GrblError("Unknown axis.")
    if not (0 < abs(delta_mm) <= 3.0):
        raise GrblError("Move exceeds Seizo manual single-command bound.")
    if not (0 < feed_mm_min <= 150):
        raise GrblError("Feed exceeds Seizo manual bound.")

    before = wait_idle(ser, timeout=3.0)
    move_line = f"G91 G21 G1 {axis}{delta_mm:.6f} F{feed_mm_min:.3f}"
    try:
        move_reply = line_expect_ok(ser, move_line, timeout=1.0)
        restore_reply = line_expect_ok(ser, "G90 G0", timeout=1.0)
        after = wait_idle(ser, timeout=4.0)
    except Exception:
        try:
            ser.write(b"!")
            ser.flush()
        except Exception:
            pass
        raise

    return {
        "axis": axis,
        "delta_mm": delta_mm,
        "feed_mm_min": feed_mm_min,
        "status_before": before,
        "status_after": after,
        "move_reply": move_reply[-6:],
        "restore_reply": restore_reply[-6:],
        "physical_motion_verified": False,
    }


def software_hold(ser) -> None:
    try:
        ser.write(b"!")
        ser.flush()
    except Exception:
        pass


def controlled_incremental_vector_move(ser, deltas: dict[str, float], feed_mm_min: float) -> dict:
    """One operator-triggered coordinated G91 move across X/Y/Z.

    This is still manual motion: one request creates one bounded GRBL G1 block.
    GRBL's planner coordinates the participating axes together.
    """
    clean = {}
    for axis in ("X", "Y", "Z"):
        value = float(deltas.get(axis, 0.0))
        if value:
            if abs(value) > 3.0:
                raise GrblError(f"{axis} component exceeds Seizo manual 3 mm bound.")
            clean[axis] = value

    if not clean:
        raise GrblError("Vector move has no non-zero axis.")
    if not (0 < float(feed_mm_min) <= 150.0):
        raise GrblError("Feed exceeds Seizo manual bound.")

    before = wait_idle(ser, timeout=3.0)
    words = " ".join(f"{axis}{value:.6f}" for axis, value in clean.items())
    move_line = f"G91 G21 G1 {words} F{float(feed_mm_min):.3f}"
    try:
        move_reply = line_expect_ok(ser, move_line, timeout=1.0)
        restore_reply = line_expect_ok(ser, "G90 G0", timeout=1.0)
        after = wait_idle(ser, timeout=4.0)
    except Exception:
        try:
            ser.write(b"!")
            ser.flush()
        except Exception:
            pass
        raise

    return {
        "deltas_mm": clean,
        "feed_mm_min": float(feed_mm_min),
        "status_before": before,
        "status_after": after,
        "move_reply": move_reply[-6:],
        "restore_reply": restore_reply[-6:],
        "physical_motion_verified": False,
        "coordinated": True,
    }
