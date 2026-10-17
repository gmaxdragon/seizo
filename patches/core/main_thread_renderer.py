"""Main-thread dispatcher for GPU-backed MuJoCo camera operations on Windows.

GLFW requires window creation/destruction on the operating-system main thread.
Training still runs independently of the browser HTTP service; the HTTP
service itself is hosted on a separate thread.

This dispatch layer never imports physical I/O, serial, GPIO, cameras, or
external network clients. It owns *only* Python callbacks passed by the app.
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class RenderJob:
    def __init__(self, function: Callable):
        self._function = function
        self._done = threading.Event()
        self._cancelled = False
        self._result = None
        self._exception = None
        self._lock = threading.Lock()

    def cancel(self):
        # A running callback cannot be aborted externally. Its own STOP
        # signal must be used. Cancel applies only while waiting in the queue.
        with self._lock:
            if self._done.is_set() or self._function is None:
                return False
            self._cancelled = True
            self._function = None
            self._done.set()
            return True

    def _execute(self):
        with self._lock:
            if self._cancelled or self._done.is_set():
                return
            function = self._function
            self._function = None  # running; no longer cancellable from queue
        try:
            self._result = function()
        except BaseException as exc:
            self._exception = exc
        finally:
            self._done.set()

    def join(self, timeout=None):
        self._done.wait(timeout)

    def is_alive(self):
        return not self._done.is_set()

    def result(self, timeout=None):
        if not self._done.wait(timeout):
            raise TimeoutError("Main-thread render operation timed out.")
        if self._cancelled:
            raise RuntimeError("Main-thread render operation was cancelled.")
        if self._exception is not None:
            raise self._exception
        return self._result


class MainThreadRenderer:
    def __init__(self):
        self._owner = threading.get_ident()
        self._pending = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False

    @property
    def owner_ident(self):
        return self._owner

    def is_owner(self):
        return threading.get_ident() == self._owner

    def submit(self, function):
        if not callable(function):
            raise TypeError("Main-thread task must be callable.")
        with self._lock:
            if self._closed:
                raise RuntimeError("Renderer dispatcher is closed.")
            job = RenderJob(function)
            self._pending.put(job)
        return job

    def call(self, function, timeout=15):
        if self.is_owner():
            return function()
        job = self.submit(function)
        try:
            return job.result(timeout)
        except TimeoutError:
            # Do not later execute a timed-out camera task unexpectedly.
            job.cancel()
            raise RuntimeError(
                "OpenGL rendering is busy on the main thread. "
                "Finish or stop the current training/evaluation and retry."
            ) from None

    def pump(self, timeout=0.25):
        if not self.is_owner():
            raise RuntimeError("Only the process main thread may create/close GPU renderers.")
        try:
            job = self._pending.get(timeout=timeout)
        except queue.Empty:
            return False
        try:
            job._execute()
        finally:
            self._pending.task_done()
        return True

    def close(self):
        with self._lock:
            self._closed = True
        while True:
            try:
                job = self._pending.get_nowait()
            except queue.Empty:
                break
            job.cancel()
            self._pending.task_done()
