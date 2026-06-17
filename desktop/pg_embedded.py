"""Embedded Postgres lifecycle for the packaged desktop app.

The local edition runs on Postgres (not SQLite). Rather than make the operator
install Postgres, the build bundles the portable Postgres binaries and this module
brings a private instance up on launch and shuts it down on exit — the same job
`start_local.ps1` does for a from-source run, but in-process so the frozen .exe is
self-contained.

Data lives under %LOCALAPPDATA%\\AlphaPOS\\pgdata (NOT in the bundle's temp dir,
which PyInstaller wipes each launch, and NOT in OneDrive). A loopback-only instance
on port 5433, trust auth — it's never exposed off the machine.

No-op (returns False) when the bundled binaries aren't found or DB_HOST already
points at an external Postgres (e.g. a dev run against the workspace _pg, or a
server deployment) — so this never fights an operator-managed database.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger('desktop.pg_embedded')

PG_PORT = '5433'
PG_DB = 'alpha_pos'
PG_USER = 'alpha_pos'
PG_PASSWORD = 'alpha_pos'

_started = False

# The packaged app is a windowless GUI build (console=False), so every console
# child spawned here (postgres, pg_ctl, initdb, psql) would otherwise pop its OWN
# terminal window — and the long-running postgres daemon's window stays open and
# UNCLOSEABLE, while _wait_ready's psql poll flashes a console twice a second.
# CREATE_NO_WINDOW runs them all headless. (Attr exists only on Windows; 0 else.)
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _binaries_dir() -> Path | None:
    """Locate the bundled `pgsql/bin` (initdb/pg_ctl/postgres/psql). PyInstaller
    puts bundled data in sys._MEIPASS / next to the exe; dev runs find it in the
    workspace `_pg`."""
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'pgsql' / 'bin')
    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / 'pgsql' / 'bin')
    # dev: workspace _pg next to the repo
    candidates.append(Path(__file__).resolve().parents[2] / '_pg' / 'pgsql' / 'bin')
    for c in candidates:
        if (c / 'pg_ctl.exe').is_file():
            return c
    return None


def _data_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') or str(Path.home())
    d = Path(base) / 'AlphaPOS' / 'pgdata'
    d.parent.mkdir(parents=True, exist_ok=True)
    return d


def _run(bin_dir: Path, exe: str, *args, **kw) -> subprocess.CompletedProcess:
    kw.setdefault('creationflags', _NO_WINDOW)   # no console window for the child
    return subprocess.run([str(bin_dir / exe), *args], capture_output=True,
                          text=True, **kw)


def _wait_ready(bin_dir: Path, timeout: float = 60.0) -> bool:
    """Poll until the embedded server actually ACCEPTS connections.

    `pg_ctl -w start` is unreliable on Windows, so we confirm readiness with a
    real `SELECT 1` before creating the role/db. Creating them too early used to
    fail silently and leave Django with 'role alpha_pos does not exist' on a
    fresh install."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _run(bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres',
                 '-d', 'postgres', '-tAc', 'SELECT 1')
        if r.returncode == 0 and '1' in (r.stdout or ''):
            return True
        time.sleep(0.5)
    return False


def _ensure_role_db(bin_dir: Path) -> None:
    """Create the app role + database, idempotently. Ignores 'already exists'."""
    _run(bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
         '-c', f"CREATE ROLE {PG_USER} LOGIN PASSWORD '{PG_PASSWORD}' SUPERUSER")
    _run(bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
         '-c', f"CREATE DATABASE {PG_DB} OWNER {PG_USER}")


def start() -> bool:
    """Bring the embedded Postgres up + ensure the role/db. Sets DB_* env so the
    Django settings connect to it. Returns True if this module now owns a running
    instance, False if it deferred (no binaries, or an external DB is configured).
    Never raises — a failure degrades to 'let Django try whatever DB env exists'."""
    global _started
    # Defer if the operator/dev already pointed us at an external Postgres.
    if os.environ.get('DB_HOST') and os.environ.get('DB_HOST') not in ('127.0.0.1', 'localhost'):
        return False
    bin_dir = _binaries_dir()
    if not bin_dir:
        logger.info('embedded Postgres binaries not bundled — using existing DB config')
        return False
    try:
        data = _data_dir()
        if not (data / 'PG_VERSION').exists():
            logger.info('initialising embedded Postgres at %s', data)
            _run(bin_dir, 'initdb.exe', '-D', str(data), '-U', 'postgres',
                 '-A', 'trust', '-E', 'UTF8')
            with open(data / 'postgresql.conf', 'a', encoding='utf-8') as f:
                f.write(f'\nport = {PG_PORT}\nlisten_addresses = \'127.0.0.1\'\n')
        # start if not already running. IMPORTANT: do NOT capture pg_ctl's
        # stdout/stderr here — on Windows the daemonized postgres can inherit the
        # pipe and block subprocess.run forever (the app hangs on launch).
        # postgres's own output already goes to -l pg.log; send pg_ctl's to NUL.
        st = _run(bin_dir, 'pg_ctl.exe', '-D', str(data), 'status')
        if st.returncode != 0:
            logger.info('starting embedded Postgres')
            subprocess.run(
                [str(bin_dir / 'pg_ctl.exe'), '-D', str(data),
                 '-l', str(data / 'pg.log'), '-w', 'start'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
            )
        # Confirm the server actually accepts connections BEFORE creating the
        # role — otherwise the CREATE ROLE races the startup, fails silently, and
        # Django dies with 'role alpha_pos does not exist' on a fresh install.
        if not _wait_ready(bin_dir):
            logger.error('embedded Postgres did not become ready in time')
            return False
        _ensure_role_db(bin_dir)
        # Verify the role landed; retry once if the first attempt was lost.
        chk = _run(bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
                   '-tAc', f"SELECT 1 FROM pg_roles WHERE rolname='{PG_USER}'")
        if '1' not in (chk.stdout or ''):
            logger.warning('app role missing after first attempt — retrying')
            _ensure_role_db(bin_dir)
        # point Django at it
        os.environ.setdefault('DB_ENGINE', 'django.db.backends.postgresql')
        os.environ['DB_NAME'] = PG_DB
        os.environ['DB_USER'] = PG_USER
        os.environ['DB_PASSWORD'] = PG_PASSWORD
        os.environ['DB_HOST'] = '127.0.0.1'
        os.environ['DB_PORT'] = PG_PORT
        _started = True
        logger.info('embedded Postgres ready on 127.0.0.1:%s', PG_PORT)
        return True
    except Exception:  # noqa: BLE001 — never let DB startup crash the launcher
        logger.exception('embedded Postgres start failed; continuing with current DB config')
        return False


def stop() -> None:
    """Stop the embedded Postgres on app exit (only if we started it)."""
    global _started
    if not _started:
        return
    bin_dir = _binaries_dir()
    if bin_dir:
        try:
            _run(bin_dir, 'pg_ctl.exe', '-D', str(_data_dir()), '-m', 'fast', 'stop')
        except Exception:  # noqa: BLE001
            logger.exception('embedded Postgres stop failed')
    _started = False
