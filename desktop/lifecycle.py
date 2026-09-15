"""Backend lifecycle state shared with the desktop shell.

When the POS backend runs as a child of the Tauri shell it has no window of its
own. The shell learns where the control server listens from an atomic *ready
file*, then polls ``GET /lifecycle`` (token protected) for the boot phase and
asks for a bounded stop with ``POST /lifecycle/shutdown``.

Phases, in boot order: ``booting`` (process up, control server bound),
``database`` (embedded Postgres + Django), ``migrating`` (setup/migrations),
``serving`` (POS server bound and setup complete), then ``stopping``.
``error`` means setup keeps failing; the supervisor is still retrying.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger('desktop.lifecycle')

PHASES = ('booting', 'database', 'migrating', 'serving', 'stopping', 'error')


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class Lifecycle:
    """Thread-safe phase holder; the control server reads snapshots of it."""

    def __init__(self):
        self._lock = threading.Lock()
        self._phase = 'booting'
        self._detail = ''
        self._updated_at = _utc_now()
        self._shutdown_handler = None
        self._shutdown_started = False

    def set(self, phase, detail=''):
        if phase not in PHASES:
            raise ValueError(f'unknown lifecycle phase: {phase}')
        with self._lock:
            # Once stopping, boot progress reports must not flip the phase back.
            if self._phase == 'stopping' and phase != 'stopping':
                return
            if phase == self._phase and detail == self._detail:
                return
            self._phase = phase
            self._detail = str(detail or '')
            self._updated_at = _utc_now()
        logger.info('lifecycle phase: %s %s', phase, detail or '')

    def snapshot(self):
        with self._lock:
            return {
                'phase': self._phase,
                'detail': self._detail,
                'updated_at': self._updated_at,
                'pid': os.getpid(),
                'shutdown_requested': self._shutdown_started,
            }

    def set_shutdown_handler(self, handler):
        with self._lock:
            self._shutdown_handler = handler

    def request_shutdown(self):
        """Start the registered shutdown once, off the calling (HTTP) thread.

        Returns True when this call started it, False if it was already running
        or no handler is registered.
        """
        with self._lock:
            if self._shutdown_started or self._shutdown_handler is None:
                return False
            self._shutdown_started = True
            handler = self._shutdown_handler
        self.set('stopping')
        threading.Thread(target=handler, name='lifecycle-shutdown', daemon=True).start()
        return True


STATE = Lifecycle()


def write_ready_file(path, *, port, version):
    """Atomically publish where the control server listens."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        'port': int(port),
        'pid': os.getpid(),
        'version': str(version),
        'written_at': _utc_now(),
    })
    tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    tmp.write_text(payload, encoding='utf-8')
    os.replace(tmp, path)
    return path


def pid_alive(pid):
    """Best-effort liveness check for the parent shell process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch_parent(pid, on_exit, *, interval=1.0, alive=pid_alive):
    """Call ``on_exit`` once the parent shell disappears.

    The Job Object already kills the backend when the shell dies abruptly; this
    watch covers the gentler cases (shell exiting without asking, or a dev run
    without a job) so Postgres still gets a clean stop.
    """
    def run():
        while alive(pid):
            time.sleep(interval)
        logger.warning('parent shell %s exited; stopping backend', pid)
        on_exit()

    thread = threading.Thread(target=run, name='parent-watch', daemon=True)
    thread.start()
    return thread
