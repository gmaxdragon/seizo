#!/usr/bin/env python3
"""Simple, view-only Seizo dual-camera service.

This service intentionally contains NO tracking, target selection, calibration,
or motor-control calls. It exists only to keep the two live camera feeds
available to the manual control website.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8787
WIDTH = 640
HEIGHT = 480
OVERHEAD_SERIAL = "E3D4B871"
WRIST_SERIAL = "2409181858122"


def metadata_for(path):
    name = os.path.basename(path)
    parts = []
    try:
        p = f"/sys/class/video4linux/{name}/name"
        if os.path.exists(p):
            parts.append(open(p, errors="replace").read().strip())
        cur = os.path.realpath(f"/sys/class/video4linux/{name}/device")
        for _ in range(8):
            if not cur or cur == "/":
                break
            for fn in ("manufacturer", "product", "serial"):
                fp = os.path.join(cur, fn)
                if os.path.exists(fp):
                    try:
                        parts.append(open(fp, errors="replace").read().strip())
                    except Exception:
                        pass
            cur = os.path.dirname(cur)
    except Exception:
        pass
    return " | ".join(x for x in parts if x)


class CameraWorker:
    def __init__(self, serial, keyword, label):
        self.serial = serial
        self.keyword = keyword
        self.label = label
        self.lock = threading.Lock()
        self.jpeg = None
        self.seq = 0
        self.stream_id = str(uuid.uuid4())
        self.at = 0.0
        self.path = None
        self.error = "starting"
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="seizo-camera-" + label)
        self.thread.start()

    def _open(self):
        import cv2
        candidates = sorted(
            glob.glob("/dev/video*"),
            key=lambda p: int(p.replace("/dev/video", "")) if p.replace("/dev/video", "").isdigit() else 999,
        )
        for path in candidates:
            meta = metadata_for(path).lower()
            if self.serial.lower() not in meta:
                continue
            cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            for _ in range(6):
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    return cap, path
                time.sleep(0.05)
            cap.release()
        raise RuntimeError(f"{self.label} camera not available")

    def _loop(self):
        import cv2
        cap = None
        bad_reads = 0
        while self.running:
            if cap is None:
                try:
                    cap, path = self._open()
                    with self.lock:
                        self.path = path
                        self.stream_id = str(uuid.uuid4())
                        self.seq = 0
                        self.jpeg = None
                        self.at = 0.0
                        self.error = None
                    bad_reads = 0
                except Exception as exc:
                    with self.lock:
                        self.path = None
                        self.error = str(exc)
                    time.sleep(2.0)
                    continue

            ok, frame = cap.read()
            if not ok or frame is None or not frame.size:
                bad_reads += 1
                if bad_reads >= 20:
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                    with self.lock:
                        self.error = "camera stream became stale; reconnecting"
                    time.sleep(0.5)
                else:
                    time.sleep(0.03)
                continue

            bad_reads = 0
            frame = cv2.resize(frame, (WIDTH, HEIGHT))
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
            if not ok:
                continue
            with self.lock:
                self.jpeg = encoded.tobytes()
                self.seq += 1
                self.at = time.monotonic()
                self.error = None

        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def snapshot(self):
        with self.lock:
            age = None if not self.at else max(0.0, time.monotonic() - self.at)
            return {
                "fresh": self.jpeg is not None and age is not None and age <= 1.5,
                "age_s": None if age is None else round(age, 3),
                "path": self.path,
                "error": self.error,
            }

    def evidence(self):
        """Atomically associate JPEG bytes with source identity and capture age."""
        with self.lock:
            age = None if not self.at else max(0.0, time.monotonic() - self.at)
            meta = {"camera_id": self.serial, "stream_id": self.stream_id,
                    "seq": self.seq, "age_s": age, "width": WIDTH, "height": HEIGHT,
                    "timestamp_kind": "host_decode_monotonic_not_sensor_exposure"}
            if self.jpeg is None or age is None or age > .5 or self.error:
                return None, meta
            return self.jpeg, meta

    def jpeg_bytes(self):
        with self.lock:
            return self.jpeg

    def close(self):
        self.running = False
        try:
            self.thread.join(timeout=2)
        except Exception:
            pass


OVERHEAD = None
WRIST = None  # Camera devices open only in main(), never during imports/tests.


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def send_json(self, payload, code=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def stream(self, worker):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                jpg = worker.jpeg_bytes()
                if jpg is None:
                    time.sleep(0.08)
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(("Content-Length: %d\r\n\r\n" % len(jpg)).encode("ascii"))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(0.04)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self):
        if self.path in ("/frame/overhead.jpg", "/frame/wrist.jpg"):
            worker = OVERHEAD if self.path == "/frame/overhead.jpg" else WRIST
            if worker is None:
                return self.send_json({"error": "camera not started"}, 503)
            jpg, meta = worker.evidence()
            if jpg is None:
                return self.send_json({"error": "no fresh frame", "source": meta}, 503)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Seizo-Frame", json.dumps(meta, separators=(",", ":")))
            self.end_headers()
            try:
                self.wfile.write(jpg)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path == "/status":
            o = OVERHEAD.snapshot()
            w = WRIST.snapshot()
            return self.send_json({
                "mode": "view_only",
                "automation_enabled": False,
                "overhead_fresh": o["fresh"],
                "wrist_fresh": w["fresh"],
                "overhead": o,
                "wrist": w,
            })
        if self.path == "/overhead.mjpg":
            return self.stream(OVERHEAD)
        if self.path == "/wrist.mjpg":
            return self.stream(WRIST)
        if self.path == "/":
            data = (
                "<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Seizo Cameras</title><body style='font-family:system-ui;background:#111;color:white'>"
                "<h2>Seizo Cameras — View Only</h2>"
                "<p>Use the main Seizo site on port 8790. No automatic movement is enabled here.</p>"
                "</body>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        return self.send_error(404)


def main():
    global OVERHEAD, WRIST
    OVERHEAD = CameraWorker(OVERHEAD_SERIAL, "logitech", "overhead")
    WRIST = CameraWorker(WRIST_SERIAL, "icspring", "wrist")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Seizo view-only cameras: http://seizo-pi.local:{PORT}/")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        OVERHEAD.close()
        WRIST.close()


if __name__ == "__main__":
    main()
