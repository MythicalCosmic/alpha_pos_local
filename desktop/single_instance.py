"""Single-instance guard — a Windows named kernel mutex.

The FIRST AlphaPOS process owns the mutex for its whole lifetime; a second launch
(double-click, login auto-start while one is already coming up) sees it already
exists, focuses the running panel and exits — so we NEVER bring up a second
embedded Postgres / uvicorn / window against the same data dir (the old race that
corrupted the cluster and flashed a second window). The kernel releases the mutex
automatically when the owning process dies (even on a hard crash), so a stale
owner self-heals on the next launch.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger('desktop.single_instance')

# Global\\ makes it system-wide (across sessions). Version-suffixed so a future
# protocol change can't collide with an old running build.
_MUTEX_NAME = 'Global\\AlphaPOS_SingleInstance_v1'
_ERROR_ALREADY_EXISTS = 183

# Held for the process lifetime — must NOT be garbage-collected, or the mutex is
# released early and a second instance would be allowed in.
_handles = {}


def acquire(name: str = _MUTEX_NAME, *, wait_seconds: float = 0.0) -> bool:
    """Return True if THIS process is the sole instance, False if another already
    holds the lock. Non-Windows / any failure -> True (fail open, never block).

    ``wait_seconds`` lets a relaunch outlive the previous process, which needs a
    bounded time to stop its database after the window is gone.
    """
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    except Exception:  # noqa: BLE001 — not Windows / ctypes unavailable
        logger.debug('single-instance mutex unavailable; allowing launch', exc_info=True)
        return True
    deadline = time.monotonic() + max(0.0, float(wait_seconds or 0.0))
    waited = False
    while True:
        try:
            ctypes.set_last_error(0)
            handle = kernel32.CreateMutexW(None, False, name)
            if not handle:
                return True  # couldn't create the mutex object — don't block the app
            if ctypes.get_last_error() != _ERROR_ALREADY_EXISTS:
                _handles[name] = handle
                if waited:
                    logger.info('single-instance lock %s became free', name)
                return True
            # Another process owns it. Drop our handle: keeping it would keep the
            # named object alive after the owner exits, so no retry could succeed.
            kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            logger.debug('single-instance mutex check failed; allowing launch', exc_info=True)
            return True
        if time.monotonic() >= deadline:
            return False
        if not waited:
            logger.info('single-instance lock %s is held; waiting for the previous process', name)
            waited = True
        time.sleep(0.25)
