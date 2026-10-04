"""Read-only USB controller identity helpers for the current Seizo build.

This module never opens a serial port. It classifies USB metadata only so the
GRBL Uno, Nano servo controller, and still-installed ESP32 are not confused.

A USB match is a candidate identity, not firmware verification. Nano firmware
is verified separately with the SEIZO_NANO_SERVO_V1 HELLO/PING protocol.
"""
from __future__ import annotations

UNO_VID_PID = ("2341", "0043")
UNO_SERIAL = "24333313131351101271"

# Current physical build observed in Seizo telemetry.
NANO_USB_IDS = {("1a86", "7523")}       # CH340/CH341 USB serial used by current Nano
ESP32_USB_IDS = {("10c4", "ea60")}      # CP210x bridge used by still-installed ESP32


def _norm(value) -> str:
    return str(value or "").strip().lower()


def usb_id(props: dict) -> tuple[str, str]:
    props = props if isinstance(props, dict) else {}
    return (_norm(props.get("ID_VENDOR_ID")), _norm(props.get("ID_MODEL_ID")))


def serial_short(props: dict) -> str:
    props = props if isinstance(props, dict) else {}
    return str(props.get("ID_SERIAL_SHORT") or "").strip()


def classify_props(props: dict) -> dict:
    vid, pid = usb_id(props)
    serial = serial_short(props)
    role = "unknown_serial"
    confidence = "unclassified"

    if (vid, pid) == UNO_VID_PID and serial == UNO_SERIAL:
        role = "uno_grbl"
        confidence = "verified_usb_identity"
    elif (vid, pid) in NANO_USB_IDS:
        role = "nano_candidate"
        confidence = "expected_current_usb_identity"
    elif (vid, pid) in ESP32_USB_IDS:
        role = "esp32_candidate"
        confidence = "expected_current_usb_identity"

    return {
        "role": role,
        "confidence": confidence,
        "vendor_id": vid,
        "product_id": pid,
        "serial": serial,
    }


def is_expected_nano_props(props: dict) -> bool:
    return usb_id(props) in NANO_USB_IDS


def is_expected_esp32_props(props: dict) -> bool:
    return usb_id(props) in ESP32_USB_IDS


def is_verified_uno_props(props: dict) -> bool:
    return usb_id(props) == UNO_VID_PID and serial_short(props) == UNO_SERIAL
