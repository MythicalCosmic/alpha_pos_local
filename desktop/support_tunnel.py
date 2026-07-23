"""Restricted outbound SSH tunnel for authorized live support.

The tunnel deliberately exposes the *complete* local PostgreSQL service and
the local POS API to loopback ports on an operator-controlled relay. Nothing
binds to the public interface of the till or relay. Access control lives at
both SSH layers: a per-install private key on the till and a restricted relay
account whose authorized key may listen only on the configured loopback ports.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from desktop import config_store


logger = logging.getLogger('desktop.support_tunnel')
SUPPORT_DIR = config_store.DATA_DIR / 'support_tunnel'
PRIVATE_KEY_FILE = SUPPORT_DIR / 'id_ed25519'
KNOWN_HOSTS_FILE = SUPPORT_DIR / 'known_hosts'
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_PROCESS: subprocess.Popen | None = None
_LAST_ERROR = ''
_LAST_CONNECTED_AT: str | None = None
_LAST_EXIT_CODE: int | None = None
_LAST_SESSION_VERIFIED_AT: str | None = None
_LAST_PROBE_AT: str | None = None
_LOCAL_DB_REACHABLE = False
_LOCAL_DB_QUERY_VERIFIED = False
_LOCAL_API_REACHABLE = False
_LAST_PROBE_ERROR = ''
_CONFIG_RE = re.compile(r'^[A-Za-z0-9._:@\[\]-]+$')
_WINDOWS_SID_RE = re.compile(r'^S-\d+(?:-\d+)+$', re.IGNORECASE)


def _truthy(value: Any) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _port(value: Any, name: str) -> int:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'{name} must be an integer') from exc
    if result < 1 or result > 65535:
        raise RuntimeError(f'{name} must be between 1 and 65535')
    return result


def _safe_atom(value: Any, name: str) -> str:
    result = str(value or '').strip()
    if not result or not _CONFIG_RE.fullmatch(result):
        raise RuntimeError(f'{name} contains unsupported characters')
    return result


def _settings() -> dict[str, Any]:
    cfg = config_store.read_config()
    return {
        'enabled': _truthy(cfg.get('SUPPORT_TUNNEL_ENABLED')),
        'host': str(cfg.get('SUPPORT_TUNNEL_HOST') or '').strip(),
        'port': str(cfg.get('SUPPORT_TUNNEL_PORT') or '22').strip(),
        'user': str(cfg.get('SUPPORT_TUNNEL_USER') or '').strip(),
        'remote_db_port': str(
            cfg.get('SUPPORT_TUNNEL_REMOTE_DB_PORT') or '15433'
        ).strip(),
        'remote_api_port': str(
            cfg.get('SUPPORT_TUNNEL_REMOTE_API_PORT') or '18000'
        ).strip(),
        'private_key_b64': str(
            cfg.get('SUPPORT_TUNNEL_PRIVATE_KEY_B64') or ''
        ).strip(),
        'known_host': str(cfg.get('SUPPORT_TUNNEL_KNOWN_HOST') or '').strip(),
        'local_api_port': str(cfg.get('PORT') or '8000').strip(),
    }


def _windows_executable(name: str) -> str:
    """Resolve a Windows system utility without relying on a complete PATH."""
    executable = shutil.which(name)
    if executable:
        return executable
    candidate = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32' / name
    if candidate.exists():
        return str(candidate)
    raise RuntimeError(f'{name} is required to protect the support tunnel key')


def _hidden_run(command: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'text': True,
        'timeout': timeout,
        'check': False,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(command, **kwargs)


def _harden_windows_private_key(path: Path, *, rights='R') -> None:
    """Remove inherited Windows ACEs so OpenSSH will accept ``path``.

    ``os.chmod(0o600)`` does not translate to a private DACL on Windows.  A file
    created below ``%LOCALAPPDATA%`` can therefore inherit access for local
    groups and Windows OpenSSH refuses to load it as an unprotected key.  Work
    with the current account SID rather than a localized/user-controlled name,
    remove inheritance, and grant that SID read access only.
    """
    if os.name != 'nt':
        return
    if rights not in {'R', 'F'}:
        raise ValueError('Windows private-file rights must be R or F')

    whoami = _hidden_run([
        _windows_executable('whoami.exe'), '/user', '/fo', 'csv', '/nh',
    ])
    if whoami.returncode != 0:
        detail = (whoami.stderr or whoami.stdout or '').strip()[-300:]
        raise RuntimeError(
            'could not resolve the Windows account SID for support key ACLs'
            + (f': {detail}' if detail else '')
        )
    try:
        row = next(csv.reader(io.StringIO(whoami.stdout or '')))
        sid = str(row[1]).strip()
    except (IndexError, StopIteration, csv.Error) as exc:
        raise RuntimeError(
            'could not parse the Windows account SID for support key ACLs'
        ) from exc
    if not _WINDOWS_SID_RE.fullmatch(sid):
        raise RuntimeError('Windows returned an invalid account SID for support key ACLs')

    protected = _hidden_run([
        _windows_executable('icacls.exe'), str(path),
        '/inheritance:r', '/grant:r', f'*{sid}:({rights})',
    ])
    if protected.returncode != 0:
        detail = (protected.stderr or protected.stdout or '').strip()[-300:]
        raise RuntimeError(
            'could not restrict the support tunnel private-key ACL'
            + (f': {detail}' if detail else '')
        )


def _write_credentials(settings: dict[str, Any]) -> tuple[Path, Path]:
    encoded = settings['private_key_b64']
    if not encoded:
        raise RuntimeError('support tunnel private key is not configured')
    try:
        private_key = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('support tunnel private key is not valid base64') from exc
    if b'PRIVATE KEY' not in private_key or len(private_key) > 32 * 1024:
        raise RuntimeError('support tunnel private key format is invalid')
    known_host = settings['known_host']
    if not known_host or '\n' in known_host or '\r' in known_host:
        raise RuntimeError('a single pinned SSH known-host entry is required')
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        config_store._write_protected(
            PRIVATE_KEY_FILE,
            private_key.decode('utf-8').rstrip() + '\n',
        )
        _harden_windows_private_key(PRIVATE_KEY_FILE)
    except Exception:
        # Fail closed and do not leave an OpenSSH-rejected, broadly readable
        # duplicate of the imported private key on disk.
        PRIVATE_KEY_FILE.unlink(missing_ok=True)
        raise
    try:
        config_store._write_protected(KNOWN_HOSTS_FILE, known_host + '\n')
        # The pinned host key is part of the authentication boundary too.  A
        # locally writable known_hosts file would let another account replace
        # the pin and intercept the full database/API tunnel.
        _harden_windows_private_key(KNOWN_HOSTS_FILE)
    except Exception:
        KNOWN_HOSTS_FILE.unlink(missing_ok=True)
        raise
    return PRIVATE_KEY_FILE, KNOWN_HOSTS_FILE


def _ssh_executable() -> str:
    executable = shutil.which('ssh.exe') or shutil.which('ssh')
    if not executable:
        system_ssh = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32' / 'OpenSSH' / 'ssh.exe'
        if system_ssh.exists():
            executable = str(system_ssh)
    if not executable:
        raise RuntimeError('Windows OpenSSH client is not installed')
    return executable


def _command(settings: dict[str, Any]) -> list[str]:
    host = _safe_atom(settings['host'], 'SUPPORT_TUNNEL_HOST')
    user = _safe_atom(settings['user'], 'SUPPORT_TUNNEL_USER')
    ssh_port = _port(settings['port'], 'SUPPORT_TUNNEL_PORT')
    remote_db = _port(
        settings['remote_db_port'], 'SUPPORT_TUNNEL_REMOTE_DB_PORT',
    )
    remote_api = _port(
        settings['remote_api_port'], 'SUPPORT_TUNNEL_REMOTE_API_PORT',
    )
    local_api = _port(settings['local_api_port'], 'PORT')
    key_file, known_hosts = _write_credentials(settings)
    return [
        _ssh_executable(), '-N', '-T',
        '-p', str(ssh_port),
        '-i', str(key_file),
        '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes',
        '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', f'UserKnownHostsFile={known_hosts}',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'ConnectTimeout=10',
        '-o', 'LogLevel=ERROR',
        '-R', f'127.0.0.1:{remote_db}:127.0.0.1:5433',
        '-R', f'127.0.0.1:{remote_api}:127.0.0.1:{local_api}',
        f'{user}@{host}',
    ]


def _hidden_popen(command: list[str]) -> subprocess.Popen:
    kwargs: dict[str, Any] = {
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.PIPE,
        'text': True,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs['startupinfo'] = startupinfo
    return subprocess.Popen(command, **kwargs)


def _probe_local_targets(settings: dict[str, Any]) -> None:
    """Verify the endpoints the reverse tunnel is publishing.

    A live ``ssh.exe`` PID alone is not proof that PostgreSQL is usable.  The
    database check performs an authenticated query with the exact local role
    used by the desktop runtime.  ``psycopg`` is bundled with Alpha POS; the TCP
    fallback is reported separately and is never presented as query-verified.
    The API probe is diagnostic only -- database access remains available while
    the POS HTTP server is intentionally stopped.
    """
    global _LAST_PROBE_AT, _LOCAL_DB_REACHABLE, _LOCAL_DB_QUERY_VERIFIED
    global _LOCAL_API_REACHABLE, _LAST_PROBE_ERROR

    db_reachable = False
    db_query_verified = False
    api_reachable = False
    errors: list[str] = []
    try:
        with socket.create_connection(('127.0.0.1', 5433), timeout=1.5):
            db_reachable = True
    except OSError as exc:
        errors.append(f'local PostgreSQL is not reachable: {exc}')

    if db_reachable:
        try:
            import psycopg
            with psycopg.connect(
                host='127.0.0.1', port=5433,
                dbname=os.environ.get('DB_NAME') or 'alpha_pos',
                user=os.environ.get('DB_USER') or 'alpha_pos',
                password=os.environ.get('DB_PASSWORD') or 'alpha_pos',
                connect_timeout=2,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT current_database()')
                    row = cursor.fetchone()
                    db_query_verified = bool(row and row[0])
        except Exception as exc:  # noqa: BLE001 - status must remain available
            errors.append(f'local PostgreSQL query failed: {exc}')

    try:
        request = urllib.request.Request(
            f'http://127.0.0.1:{_port(settings["local_api_port"], "PORT")}/healthz',
            headers={'User-Agent': 'AlphaPOS-support-probe/1'},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            api_reachable = response.status == 200
        if not api_reachable:
            errors.append('local POS API health check did not return HTTP 200')
    except Exception as exc:  # noqa: BLE001 - the API may be intentionally off
        errors.append(f'local POS API is not reachable: {exc}')

    with _LOCK:
        _LAST_PROBE_AT = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        _LOCAL_DB_REACHABLE = db_reachable
        _LOCAL_DB_QUERY_VERIFIED = db_query_verified
        _LOCAL_API_REACHABLE = api_reachable
        _LAST_PROBE_ERROR = '; '.join(errors)[:1000]


def _supervisor() -> None:
    global _PROCESS, _LAST_ERROR, _LAST_CONNECTED_AT, _LAST_EXIT_CODE
    global _LAST_SESSION_VERIFIED_AT
    backoff = 3
    while not _STOP.is_set():
        connected_started: float | None = None
        try:
            # Config can be temporarily unavailable while the control panel is
            # atomically replacing .env or while an operator repairs a damaged
            # file. Reading it outside this boundary used to kill the supervisor
            # permanently, so the tunnel never returned until Alpha POS itself
            # was restarted.
            settings = _settings()
            if not settings['enabled']:
                with _LOCK:
                    _LAST_ERROR = ''
                    _LAST_SESSION_VERIFIED_AT = None
                backoff = 3
                _STOP.wait(5)
                continue
            process = _hidden_popen(_command(settings))
            with _LOCK:
                _PROCESS = process
                _LAST_ERROR = ''
                _LAST_CONNECTED_AT = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                _LAST_EXIT_CODE = None
                _LAST_SESSION_VERIFIED_AT = None
            connected_started = time.monotonic()
            next_probe = connected_started
            while not _STOP.wait(1):
                code = process.poll()
                if code is None:
                    now = time.monotonic()
                    # ``Popen`` only proves ssh.exe started. Keep the UI in
                    # CONNECTING through OpenSSH's ten-second connect timeout;
                    # surviving beyond it with ExitOnForwardFailure enabled is
                    # our fail-closed evidence that authentication and both
                    # reverse listeners completed.
                    if now - connected_started >= 12 and _LAST_SESSION_VERIFIED_AT is None:
                        with _LOCK:
                            _LAST_SESSION_VERIFIED_AT = time.strftime(
                                '%Y-%m-%dT%H:%M:%SZ', time.gmtime(),
                            )
                    if now >= next_probe:
                        _probe_local_targets(settings)
                        next_probe = now + 10
                    continue
                _, stderr = process.communicate(timeout=1)
                with _LOCK:
                    _LAST_EXIT_CODE = code
                    _LAST_SESSION_VERIFIED_AT = None
                    _LAST_ERROR = str(
                        stderr or f'ssh exited with code {code}'
                    )[-500:]
                break
        except Exception as exc:  # noqa: BLE001 - reconnect loop owns failures
            with _LOCK:
                _LAST_ERROR = str(exc)[:500]
            logger.warning('support tunnel unavailable: %s', _LAST_ERROR)
        finally:
            with _LOCK:
                process = _PROCESS
                _PROCESS = None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        if not _STOP.is_set():
            _STOP.wait(backoff)
            # Fast authentication/config/forward failures back off instead of
            # spawning ssh every three seconds forever. A connection that stayed
            # healthy for a minute resets recovery to the fast first retry.
            stable = (
                connected_started is not None
                and time.monotonic() - connected_started >= 60
            )
            backoff = 3 if stable else min(backoff * 2, 60)


def start() -> bool:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(
            target=_supervisor, name='support-tunnel', daemon=True,
        )
        _THREAD.start()
    return True


def stop(*, timeout: float = 8.0) -> bool:
    global _THREAD
    _STOP.set()
    with _LOCK:
        process = _PROCESS
        thread = _THREAD
    if process is not None and process.poll() is None:
        process.terminate()
    if thread is not None and thread is not threading.current_thread():
        thread.join(max(0.0, float(timeout)))
    stopped = thread is None or not thread.is_alive()
    if stopped:
        with _LOCK:
            _THREAD = None
    return stopped


def restart() -> bool:
    if stop():
        return start()

    # A config save can arrive while ssh is inside a bounded Windows/OpenSSH
    # call and outlive the UI's stop timeout. Clearing _STOP immediately would
    # let the old supervisor keep running with stale ports/credentials; simply
    # returning leaves support down forever once it eventually exits. Finish the
    # handoff off the request thread and start exactly one fresh supervisor after
    # the old one has really quiesced.
    with _LOCK:
        old_thread = _THREAD

    def restart_after_join() -> None:
        global _THREAD
        if old_thread is not None:
            old_thread.join(30)
        if old_thread is not None and old_thread.is_alive():
            logger.error('support tunnel did not stop; restart was not attempted')
            return
        with _LOCK:
            if _THREAD is old_thread:
                _THREAD = None
        start()

    threading.Thread(
        target=restart_after_join,
        name='support-tunnel-restart',
        daemon=True,
    ).start()
    return True


def set_enabled(enabled: bool) -> dict[str, Any]:
    """Persist and apply the operator-facing support switch immediately."""
    config_store.write_config({
        'SUPPORT_TUNNEL_ENABLED': 'True' if bool(enabled) else 'False',
    })
    restart()
    # Return an immediate, truthful transitional state.  The dashboard polls
    # until ``ready`` only after ssh has stayed alive and the DB query succeeds.
    return status()


def status() -> dict[str, Any]:
    settings = _settings()
    with _LOCK:
        process = _PROCESS
        configured = bool(
            settings['host'] and settings['user']
            and settings['private_key_b64'] and settings['known_host']
        )
        connected = bool(process is not None and process.poll() is None)
        session_verified = bool(connected and _LAST_SESSION_VERIFIED_AT)
        ready = bool(
            settings['enabled'] and session_verified
            and _LOCAL_DB_REACHABLE and _LOCAL_DB_QUERY_VERIFIED
        )
        if not settings['enabled']:
            state = 'off'
        elif not configured:
            state = 'configuration_required'
        elif ready:
            state = 'ready'
        elif connected:
            state = 'degraded' if _LAST_PROBE_AT and _LAST_PROBE_ERROR else 'connecting'
        elif _LAST_ERROR:
            state = 'error'
        else:
            state = 'connecting'
        return {
            'enabled': settings['enabled'],
            'configured': configured,
            'worker_alive': bool(_THREAD is not None and _THREAD.is_alive()),
            'connected': connected,
            'session_verified': session_verified,
            'ready': ready,
            'state': state,
            'relay_host': settings['host'],
            'remote_db': (
                f'127.0.0.1:{settings["remote_db_port"]}'
                if settings['host'] else ''
            ),
            'remote_api': (
                f'127.0.0.1:{settings["remote_api_port"]}'
                if settings['host'] else ''
            ),
            'last_connected_at': _LAST_CONNECTED_AT,
            'session_verified_at': _LAST_SESSION_VERIFIED_AT,
            'last_probe_at': _LAST_PROBE_AT,
            'local_db_reachable': _LOCAL_DB_REACHABLE,
            'local_db_query_verified': _LOCAL_DB_QUERY_VERIFIED,
            'local_api_reachable': _LOCAL_API_REACHABLE,
            'last_probe_error': _LAST_PROBE_ERROR,
            'last_exit_code': _LAST_EXIT_CODE,
            'last_error': _LAST_ERROR,
        }
