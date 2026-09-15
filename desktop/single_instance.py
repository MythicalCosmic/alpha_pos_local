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

logger = logging.getLogger('desktop.single_instance')

# Global\\ makes it system-wide (across sessions). Version-suffixed so a future
# protocol change can't collide with an old running build.
_MUTEX_NAME = 'Global\\AlphaPOS_SingleInstance_v1'
# The windowless backend started by the Tauri shell guards pgdata separately, so
# two backends can never share one embedded cluster even if two shells raced.
BACKEND_MUTEX_NAME = 'Global\\AlphaPOS_Backend_v1'
_ERROR_ALREADY_EXISTS = 183

# Held for the process lifetime — must NOT be garbage-collected, or the mutex is
# released early and a second instance would be allowed in.
_handles = {}


def acquire(name: str = _MUTEX_NAME) -> bool:
    """Return True if THIS process is the sole instance, False if another already
    holds the lock. Non-Windows / any failure -> True (fail open, never block)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True  # couldn't create the mutex object — don't block the app
        _handles[name] = handle
        return kernel32.GetLastError() != _ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 — not Windows / ctypes unavailable
        logger.debug('single-instance mutex unavailable; allowing launch', exc_info=True)
        return True
