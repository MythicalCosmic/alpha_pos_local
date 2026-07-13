"""Embedded Postgres lifecycle for the packaged desktop app.

The local edition runs on Postgres (not SQLite). Rather than make the operator
install Postgres, the build bundles the portable Postgres binaries and this module
brings a private instance up on launch and shuts it down on exit — the same job
`start_local.ps1` does for a from-source run, but in-process so the frozen .exe is
self-contained.

Data lives under %LOCALAPPDATA%\\AlphaPOS\\pgdata (NOT in the bundle's temp dir,
which PyInstaller wipes each launch, and NOT in OneDrive). A loopback-only instance
on port 5433, trust auth — it's never exposed off the machine.

No-op (returns False) when DB_HOST points at an external Postgres, or during a
from-source run without portable binaries. A frozen desktop build fails closed
when its required database cannot be started; silently falling through to
SQLite would open a different data store and make completed orders look lost.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger('desktop.pg_embedded')

PG_PORT = '5433'
PG_DB = 'alpha_pos'
PG_USER = 'alpha_pos'
PG_PASSWORD = 'alpha_pos'

_started = False
_configured_embedded = False
_migration_warning = ''
_recovery_warning = ''
_last_error = ''
_START_LOCK = threading.RLock()


class EmbeddedPostgresError(RuntimeError):
    """The packaged app cannot safely open its required local database."""

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
    # One canonical location for config, secrets AND the database. The former
    # independent fallback used ``~/AlphaPOS`` when LOCALAPPDATA was missing,
    # while config_store correctly used ``~/AppData/Local/AlphaPOS``. A Startup
    # launch could therefore read the manual launch's .env but open a completely
    # different database (or vice versa). Import is lazy, so no Django startup
    # cost is introduced here.
    from desktop import config_store
    d = config_store.DATA_DIR / 'pgdata'
    d.parent.mkdir(parents=True, exist_ok=True)
    return d


def _legacy_data_candidates(canonical: Path) -> tuple[Path, ...]:
    """Pre-canonical embedded-cluster locations in deterministic order."""
    if not getattr(sys, 'frozen', False):
        return ()
    candidates = [
        # The exact fallback used before config_store and Postgres shared a path.
        Path.home() / 'AlphaPOS' / 'pgdata',
        Path(sys.executable).resolve().parent / 'pgdata',
        Path.cwd() / 'pgdata',
    ]
    seen = {canonical.resolve()}
    result = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return tuple(result)


def _migrate_legacy_cluster(canonical: Path) -> Path | None:
    """Move a sole legacy cluster when canonical storage is not initialized.

    If both locations contain a cluster, canonical wins and neither is modified:
    merging PostgreSQL data directories is unsafe. The diagnostic remains
    visible for support/manual reconciliation.
    """
    global _migration_warning
    from desktop import config_store

    _migration_warning = ''
    marker = config_store.LEGACY_PG_MIGRATION_MARKER
    marker_state = ''
    if marker.exists():
        try:
            marker_state = marker.read_text(encoding='utf-8').strip()
        except OSError as exc:
            raise EmbeddedPostgresError(
                f'Cannot read PostgreSQL migration marker {marker}: {exc}'
            ) from exc
        # Keep re-evaluating a split marker so the warning remains visible until
        # support reconciles/removes the legacy cluster. Completed migration and
        # reset markers permanently prevent stale data from being resurrected.
        if marker_state == 'factory-reset':
            return None
        if marker_state == 'migrated':
            if not (canonical / 'PG_VERSION').is_file():
                raise EmbeddedPostgresError(
                    'PostgreSQL migration is recorded as complete, but the '
                    f'canonical cluster is missing: {canonical}'
                )
            return None
        if marker_state != 'split-detected':
            raise EmbeddedPostgresError(
                f'Unrecognized PostgreSQL migration marker value: {marker_state!r}'
            )
    legacy_clusters = [
        path for path in _legacy_data_candidates(canonical)
        if (path / 'PG_VERSION').is_file()
    ]
    canonical_ready = (canonical / 'PG_VERSION').is_file()
    if marker_state == 'split-detected' and not canonical_ready:
        raise EmbeddedPostgresError(
            'Canonical PostgreSQL cluster disappeared after a split-cluster '
            'condition was recorded; refusing to promote potentially stale legacy data.'
        )
    if canonical_ready:
        if legacy_clusters:
            _migration_warning = (
                'Both canonical and legacy PostgreSQL clusters exist; using '
                f'{canonical} and leaving legacy cluster(s) untouched: '
                + ', '.join(str(path) for path in legacy_clusters)
            )
            logger.error(_migration_warning)
            config_store._write_protected(marker, 'split-detected\n')
        return None
    if canonical.exists():
        if any(canonical.iterdir()):
            raise EmbeddedPostgresError(
                f'Canonical PostgreSQL directory is incomplete/non-empty: {canonical}'
            )
        # Windows cannot os.replace() a source directory over even an empty
        # destination directory. Removing a proven-empty target preserves all
        # legacy data and lets the following directory rename stay atomic.
        try:
            canonical.rmdir()
        except OSError as exc:
            raise EmbeddedPostgresError(
                f'Could not remove empty PostgreSQL migration target {canonical}: {exc}'
            ) from exc
    if not legacy_clusters:
        return None

    source = legacy_clusters[0]
    if len(legacy_clusters) > 1:
        raise EmbeddedPostgresError(
            'Multiple legacy PostgreSQL clusters found; refusing to guess: '
            + ', '.join(str(path) for path in legacy_clusters)
        )
    pid_file = source / 'postmaster.pid'
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding='utf-8').splitlines()[0].strip())
        except (OSError, ValueError, IndexError) as exc:
            raise EmbeddedPostgresError(
                f'Cannot validate legacy PostgreSQL lock at {pid_file}'
            ) from exc
        if _pid_alive(pid):
            raise EmbeddedPostgresError(
                f'Legacy PostgreSQL cluster is still running (pid {pid}); '
                'refusing to move live data.'
            )
    canonical.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Both known locations are on the user's system drive; os.replace is an
        # atomic directory rename and intentionally refuses cross-volume copies.
        os.replace(source, canonical)
    except OSError as exc:
        raise EmbeddedPostgresError(
            f'Could not atomically migrate PostgreSQL data from {source} to '
            f'{canonical}: {exc}'
        ) from exc
    config_store._write_protected(marker, 'migrated\n')
    logger.warning('migrated legacy PostgreSQL cluster from %s to %s', source, canonical)
    return source


def migration_status() -> dict:
    """Small launcher-safe diagnostic exposed by the control panel."""
    warnings = [value for value in (_migration_warning, _recovery_warning) if value]
    return {'warning': ' | '.join(warnings), 'error': _last_error}


def detect_stranded_sqlite() -> dict:
    """Read-only evidence check for databases created by the old startup race.

    Never imports or deletes anything. Counts are exposed so support can identify
    tills requiring deliberate reconciliation with canonical PostgreSQL.
    """
    global _recovery_warning
    _recovery_warning = ''
    if not getattr(sys, 'frozen', False):
        return {}
    from desktop import config_store
    legacy = config_store.DATA_DIR / 'db.sqlite3'
    try:
        if not legacy.is_file() or legacy.stat().st_size <= 0:
            return {}
        import sqlite3
        connection = sqlite3.connect(legacy.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            order_table = 'base_order' if 'base_order' in tables else None
            queue_table = next((name for name in (
                'sync_queue_record', 'base_syncqueuerecord',
            ) if name in tables), None)
            counts = {
                'orders': int(connection.execute(
                    f'SELECT COUNT(*) FROM "{order_table}"'
                ).fetchone()[0]) if order_table else 0,
                'sync_queue': int(connection.execute(
                    f'SELECT COUNT(*) FROM "{queue_table}"'
                ).fetchone()[0]) if queue_table else 0,
                'unsynced_orders': 0,
            }
            if order_table:
                order_columns = {
                    row[1] for row in connection.execute(
                        f'PRAGMA table_info("{order_table}")'
                    )
                }
                if 'synced_at' in order_columns:
                    counts['unsynced_orders'] = int(connection.execute(
                        f'SELECT COUNT(*) FROM "{order_table}" WHERE synced_at IS NULL'
                    ).fetchone()[0])
        finally:
            connection.close()
        if any(counts.values()):
            _recovery_warning = (
                'Recovery evidence found in legacy SQLite database; do not delete it. '
                f'orders={counts["orders"]}, unsynced_orders={counts["unsynced_orders"]}, '
                f'sync_queue={counts["sync_queue"]}, '
                f'path={legacy}. Contact support to reconcile with PostgreSQL.'
            )
            logger.error(_recovery_warning)
        return {'path': str(legacy), **counts}
    except Exception as exc:  # noqa: BLE001
        _recovery_warning = (
            f'Legacy SQLite database exists but could not be inspected safely: '
            f'{legacy} ({exc}). Do not delete it; contact support.'
        )
        logger.exception(_recovery_warning)
        return {'path': str(legacy), 'error': str(exc)}


def _run(bin_dir: Path, exe: str, *args, **kw) -> subprocess.CompletedProcess:
    kw.setdefault('creationflags', _NO_WINDOW)   # no console window for the child
    kw.setdefault('timeout', 15)
    return subprocess.run([str(bin_dir / exe), *args], capture_output=True,
                          text=True, **kw)


def _wait_ready(bin_dir: Path, timeout: float = 15.0) -> bool:
    """Poll until the embedded server ACCEPTS connections on its port. A raw TCP
    connect is far cheaper than spawning psql.exe twice a second (each flashed a
    console + cost a process launch); the 0.15s cadence makes a normal start
    return in a fraction of a second instead of the old up-to-60s poll."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', int(PG_PORT)), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _pid_alive(pid: int) -> bool:
    """True if PID is a RUNNING postgres.exe — so we never delete a live lock.
    Uncertain -> True (safe default: don't remove a possibly-live postmaster.pid)."""
    try:
        out = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FI', 'IMAGENAME eq postgres.exe', '/NH'],
            capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=5)
        return 'postgres.exe' in (out.stdout or '').lower()
    except Exception:  # noqa: BLE001
        return True


def _role_exists(bin_dir: Path) -> bool:
    chk = _run(bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
               '-tAc', f"SELECT 1 FROM pg_roles WHERE rolname='{PG_USER}'")
    if chk.returncode != 0:
        raise EmbeddedPostgresError(
            'Could not verify embedded PostgreSQL role: '
            + ((chk.stderr or chk.stdout or 'psql failed').strip()[-1000:])
        )
    return (chk.stdout or '').strip() == '1'


def _database_exists(bin_dir: Path) -> bool:
    chk = _run(bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
               '-tAc', f"SELECT 1 FROM pg_database WHERE datname='{PG_DB}'")
    if chk.returncode != 0:
        raise EmbeddedPostgresError(
            'Could not verify embedded PostgreSQL database: '
            + ((chk.stderr or chk.stdout or 'psql failed').strip()[-1000:])
        )
    return (chk.stdout or '').strip() == '1'


def _connected_data_directory(bin_dir: Path) -> Path:
    """Return the cluster behind PG_PORT, refusing non-Postgres listeners."""
    chk = _run(
        bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
        '-tAc', 'SHOW data_directory',
    )
    value = (chk.stdout or '').strip()
    if chk.returncode != 0 or not value:
        raise EmbeddedPostgresError(
            'Could not identify PostgreSQL listening on the embedded port: '
            + ((chk.stderr or chk.stdout or 'psql failed').strip()[-1000:])
        )
    return Path(value).resolve()


def _log_pg_failure(data: Path) -> None:
    """Surface the REAL Postgres error (tail of pg.log) on a failed start, instead
    of the old silent timeout that left Django dying with 'role does not exist'."""
    try:
        log = data / 'pg.log'
        if log.exists():
            tail = log.read_text(encoding='utf-8', errors='replace').splitlines()[-15:]
            logger.error('embedded Postgres did not become ready. pg.log tail:\n%s',
                         '\n'.join(tail))
        else:
            logger.error('embedded Postgres did not become ready (no pg.log yet)')
    except Exception:  # noqa: BLE001
        logger.error('embedded Postgres did not become ready (pg.log unreadable)')


def _ensure_role_db(bin_dir: Path) -> None:
    """Create whichever app principals are missing and verify each command."""
    if not _role_exists(bin_dir):
        created = _run(
            bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
            '-v', 'ON_ERROR_STOP=1', '-c',
            f"CREATE ROLE {PG_USER} LOGIN PASSWORD '{PG_PASSWORD}' SUPERUSER",
        )
        if created.returncode != 0:
            raise EmbeddedPostgresError(
                'Could not create embedded PostgreSQL role: '
                + ((created.stderr or created.stdout or 'psql failed').strip()[-1000:])
            )
    if not _database_exists(bin_dir):
        created = _run(
            bin_dir, 'psql.exe', '-p', PG_PORT, '-U', 'postgres', '-d', 'postgres',
            '-v', 'ON_ERROR_STOP=1', '-c', f'CREATE DATABASE {PG_DB} OWNER {PG_USER}',
        )
        if created.returncode != 0:
            raise EmbeddedPostgresError(
                'Could not create embedded PostgreSQL database: '
                + ((created.stderr or created.stdout or 'psql failed').strip()[-1000:])
            )


def start() -> bool:
    """Serialize all callers, including early UI diagnostics and boot worker."""
    with _START_LOCK:
        return _start_locked()


def _start_locked() -> bool:
    """Bring the embedded Postgres up + ensure the role/db. Sets DB_* env so the
    Django settings connect to it. Returns True if this module now owns a running
    instance, False if it safely deferred to an explicitly configured external
    database (or a source checkout without portable binaries). Packaged startup
    failures raise EmbeddedPostgresError so Django can never silently select its
    SQLite fallback and present a different set of orders."""
    global _started, _configured_embedded, _last_error
    _last_error = ''
    # Any persistent DB_HOST is an explicit external DB choice, including a
    # perfectly valid localhost:5432 developer/operator instance. The only
    # exception is the exact config this module previously installed in-process.
    configured_host = (os.environ.get('DB_HOST') or '').strip().lower()
    configured_port = str(os.environ.get('DB_PORT') or '5432').strip()
    own_config = (
        _configured_embedded
        and configured_host in {'127.0.0.1', 'localhost'}
        and configured_port == PG_PORT
    )
    db_keys = ('DB_ENGINE', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT')
    has_external_override = any(str(os.environ.get(key) or '').strip() for key in db_keys)
    if has_external_override and not own_config:
        engine = (os.environ.get('DB_ENGINE') or '').strip().lower()
        missing = [key for key in ('DB_ENGINE', 'DB_NAME', 'DB_USER', 'DB_HOST', 'DB_PORT')
                   if not str(os.environ.get(key) or '').strip()]
        if missing or 'postgresql' not in engine:
            message = (
                'External database configuration is incomplete/unsafe; require '
                'PostgreSQL DB_ENGINE, DB_NAME, DB_USER, DB_HOST and DB_PORT. '
                f'Missing: {", ".join(missing) or "valid PostgreSQL DB_ENGINE"}'
            )
            _last_error = message
            raise EmbeddedPostgresError(message)
        try:
            port_number = int(configured_port)
        except ValueError as exc:
            _last_error = f'External DB_PORT must be an integer: {configured_port!r}'
            raise EmbeddedPostgresError(_last_error) from exc
        if not 1 <= port_number <= 65535:
            _last_error = f'External DB_PORT is outside 1..65535: {port_number}'
            raise EmbeddedPostgresError(_last_error)
        logger.info(
            'external PostgreSQL explicitly configured at %s:%s; embedded DB deferred',
            configured_host, configured_port,
        )
        detect_stranded_sqlite()
        return False
    bin_dir = _binaries_dir()
    if not bin_dir:
        message = 'embedded PostgreSQL binaries are missing from this build'
        if getattr(sys, 'frozen', False):
            _last_error = message
            raise EmbeddedPostgresError(message)
        logger.info('%s — source run will use its existing DB config', message)
        return False
    try:
        data = _data_dir()
        _migrate_legacy_cluster(data)
        if data.exists() and not (data / 'PG_VERSION').is_file() and any(data.iterdir()):
            raise EmbeddedPostgresError(
                f'Canonical PostgreSQL directory is incomplete/non-empty: {data}'
            )
        # Recover from a stale lock left by a hard kill (crash / Task Manager /
        # power loss / a double-launch race): a postmaster.pid pointing at a DEAD
        # pid makes pg_ctl refuse to start and _wait_ready burn its whole timeout
        # — the "server sometimes won't start" symptom. Remove it ONLY when the
        # pid is provably not a running postgres (never delete a live lock).
        pid_file = data / 'postmaster.pid'
        if pid_file.exists():
            try:
                stale_pid = int(pid_file.read_text(encoding='utf-8').splitlines()[0].strip())
                if not _pid_alive(stale_pid):
                    pid_file.unlink()
                    logger.warning('removed stale postmaster.pid (pid %s not running)', stale_pid)
            except Exception as exc:  # noqa: BLE001
                raise EmbeddedPostgresError(
                    f'Could not safely evaluate PostgreSQL lock {pid_file}: {exc}'
                ) from exc

        was_initialised = (data / 'PG_VERSION').exists()
        if not was_initialised:
            logger.info('initialising embedded Postgres at %s', data)
            initialized = _run(
                bin_dir, 'initdb.exe', '-D', str(data), '-U', 'postgres',
                '-A', 'trust', '-E', 'UTF8', timeout=60,
            )
            if initialized.returncode != 0 or not (data / 'PG_VERSION').is_file():
                raise EmbeddedPostgresError(
                    'Could not initialize embedded PostgreSQL: '
                    + ((initialized.stderr or initialized.stdout or 'initdb failed')
                       .strip()[-1500:])
                )
            with open(data / 'postgresql.conf', 'a', encoding='utf-8') as f:
                f.write(f'\nport = {PG_PORT}\nlisten_addresses = \'127.0.0.1\'\n')
        # start if not already running. IMPORTANT: do NOT capture pg_ctl's
        # stdout/stderr here — on Windows the daemonized postgres can inherit the
        # pipe and block subprocess.run forever (the app hangs on launch).
        # postgres's own output already goes to -l pg.log; send pg_ctl's to NUL.
        st = _run(bin_dir, 'pg_ctl.exe', '-D', str(data), 'status', timeout=10)
        running = (st.returncode == 0)
        if not running:
            logger.info('starting embedded Postgres')
            try:
                started = subprocess.run(
                    [str(bin_dir / 'pg_ctl.exe'), '-D', str(data),
                     '-l', str(data / 'pg.log'), '-w', 'start'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                started = None
            # Confirm it actually accepts connections (pg_ctl -w is unreliable on
            # Windows); surface pg.log instead of a silent timeout on failure.
            if not _wait_ready(bin_dir, timeout=5 if started is None else 15):
                _log_pg_failure(data)
                result = 'timed out' if started is None else f'exited {started.returncode}'
                raise EmbeddedPostgresError(
                    f'Embedded PostgreSQL failed to become ready (pg_ctl {result}); '
                    f'see {data / "pg.log"}'
                )
            running = True

        # A raw TCP readiness probe can be satisfied by an unrelated service or
        # another PostgreSQL cluster already occupying :5433. Before issuing any
        # CREATE ROLE/DB statements, prove pg_ctl owns the canonical directory
        # and that psql reaches that exact same directory.
        owned = _run(bin_dir, 'pg_ctl.exe', '-D', str(data), 'status', timeout=10)
        if owned.returncode != 0:
            raise EmbeddedPostgresError(
                f'Port {PG_PORT} is accepting connections but the canonical '
                'PostgreSQL cluster is not running; possible port collision.'
            )
        _started = True
        connected_data = _connected_data_directory(bin_dir)
        if os.path.normcase(str(connected_data)) != os.path.normcase(str(data.resolve())):
            raise EmbeddedPostgresError(
                f'Port {PG_PORT} belongs to PostgreSQL data directory '
                f'{connected_data}, not canonical {data.resolve()}; refusing to modify it.'
            )
        detect_stranded_sqlite()

        # From this point the canonical server is accepting connections. Mark it
        # as ours immediately so a later role/database bootstrap failure can
        # still shut it down cleanly instead of leaving an orphan that locks
        # pgdata across retries/reset/update.
        # Role/db are created on first init and PERSIST across restarts. On a warm
        # launch (already running + initialised) just verify (1 cheap query) and
        # only (re)create if missing — instead of the old unconditional double
        # CREATE + verify, saving 3-4 psql.exe spawns on every normal launch.
        if not _role_exists(bin_dir) or not _database_exists(bin_dir):
            _ensure_role_db(bin_dir)
            if not _role_exists(bin_dir) or not _database_exists(bin_dir):
                logger.warning('app role/database still missing after create — retrying once')
                _ensure_role_db(bin_dir)
            if not _role_exists(bin_dir) or not _database_exists(bin_dir):
                raise EmbeddedPostgresError(
                    'Embedded PostgreSQL app role/database is still missing after retry'
                )
        # point Django at it
        os.environ.setdefault('DB_ENGINE', 'django.db.backends.postgresql')
        os.environ['DB_NAME'] = PG_DB
        os.environ['DB_USER'] = PG_USER
        os.environ['DB_PASSWORD'] = PG_PASSWORD
        os.environ['DB_HOST'] = '127.0.0.1'
        os.environ['DB_PORT'] = PG_PORT
        _configured_embedded = True
        _started = True
        logger.info('embedded Postgres ready on 127.0.0.1:%s', PG_PORT)
        return True
    except EmbeddedPostgresError as exc:
        _last_error = str(exc)
        logger.error('embedded PostgreSQL start failed: %s', exc, exc_info=True)
        if _started:
            stop()
        raise
    except Exception as exc:  # noqa: BLE001
        wrapped = EmbeddedPostgresError(f'Embedded PostgreSQL start failed: {exc}')
        _last_error = str(wrapped)
        logger.exception('embedded PostgreSQL start failed')
        if _started:
            stop()
        raise wrapped from exc


def stop() -> bool:
    with _START_LOCK:
        return _stop_locked()


def _stop_locked() -> bool:
    """Stop the canonical embedded cluster, including an orphan after a crash.

    Returns False when a running server could not be stopped. Destructive callers
    use this to avoid deleting a live data directory.
    """
    global _started
    bin_dir = _binaries_dir()
    if not bin_dir:
        return not _started
    data = _data_dir()
    if not (data / 'PG_VERSION').is_file():
        _started = False
        return True
    try:
        status = _run(bin_dir, 'pg_ctl.exe', '-D', str(data), 'status', timeout=10)
        if status.returncode == 3:  # pg_ctl's documented "server is not running"
            _started = False
            return True
        if status.returncode != 0:
            logger.error(
                'could not determine embedded PostgreSQL stop state: %s',
                (status.stderr or status.stdout or 'pg_ctl status failed').strip()[-1000:],
            )
            return False
        stopped = _run(
            bin_dir, 'pg_ctl.exe', '-D', str(data),
            '-m', 'fast', '-w', 'stop', timeout=30,
        )
        if stopped.returncode != 0:
            logger.error(
                'embedded PostgreSQL stop failed: %s',
                (stopped.stderr or stopped.stdout or 'pg_ctl failed').strip()[-1000:],
            )
            return False
        _started = False
        return True
    except Exception:  # noqa: BLE001
        logger.exception('embedded Postgres stop failed')
        return False
