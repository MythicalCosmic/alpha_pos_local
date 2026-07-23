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
import hashlib
import ipaddress
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
_LAST_ATTEMPT_AT: str | None = None
_LAST_CONNECTED_AT: str | None = None
_LAST_EXIT_CODE: int | None = None
_LAST_SESSION_VERIFIED_AT: str | None = None
_LAST_PROBE_AT: str | None = None
_LAST_PROBE_MONOTONIC: float | None = None
_LOCAL_DB_REACHABLE = False
_LOCAL_DB_QUERY_VERIFIED = False
_LOCAL_API_REACHABLE = False
_LAST_DB_PROBE_ERROR = ''
_LAST_API_PROBE_ERROR = ''
_LAST_PROBE_ERROR = ''
_RECONNECT_ATTEMPT = 0
_CURRENT_BACKOFF_SECONDS = 0
_NEXT_RETRY_AT: str | None = None
_PROBE_MAX_AGE_SECONDS = 25.0
_SESSION_VERIFY_AFTER_SECONDS = 12.0
_SSH_USER_RE = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
_DNS_LABEL_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')
_BACKEND_HEALTH_RE = re.compile(
    rb'ok(?: [A-Za-z0-9][A-Za-z0-9._+-]{0,63})?\Z',
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r'(?i)\b(password|passphrase|token|secret|authorization)'
    r'\s*[:=]\s*([^\s;]+)',
)
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


def _utc_now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _utc_after(seconds: float) -> str:
    return time.strftime(
        '%Y-%m-%dT%H:%M:%SZ',
        time.gmtime(time.time() + max(0.0, float(seconds))),
    )


def _ssh_user(value: Any) -> str:
    result = str(value or '').strip()
    if not _SSH_USER_RE.fullmatch(result):
        raise RuntimeError('SUPPORT_TUNNEL_USER is not a safe SSH account name')
    return result


def _ssh_host(value: Any) -> tuple[str, str]:
    """Return ``(destination_host, known_hosts_host)`` for one exact host."""
    raw = str(value or '').strip()
    if not raw or len(raw) > 253 or any(char.isspace() for char in raw):
        raise RuntimeError('SUPPORT_TUNNEL_HOST is not a valid IP address or hostname')
    if raw.startswith('[') and raw.endswith(']'):
        raw = raw[1:-1]
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        if (
            raw.endswith('.')
            or '@' in raw
            or ':' in raw
            or any(not _DNS_LABEL_RE.fullmatch(label) for label in raw.split('.'))
        ):
            raise RuntimeError(
                'SUPPORT_TUNNEL_HOST is not a valid IP address or hostname'
            )
        return raw, raw.lower()
    canonical = address.compressed
    destination = f'[{canonical}]' if address.version == 6 else canonical
    return destination, canonical


def _redact_text(value: Any, settings: dict[str, Any] | None = None) -> str:
    """Return a bounded diagnostic string with configured secrets removed."""
    text = str(value or '')
    secret_values = [
        os.environ.get('DB_PASSWORD', ''),
    ]
    if settings:
        secret_values.append(str(settings.get('private_key_b64') or ''))
    for secret in secret_values:
        if secret and len(secret) >= 4:
            text = text.replace(secret, '[REDACTED]')
    text = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f'{match.group(1)}=[REDACTED]',
        text,
    )
    return text[-1000:]


def _valid_backend_health_body(value: Any) -> bool:
    """Accept only the local backend's bounded, unambiguous health contract."""
    return (
        isinstance(value, bytes)
        and _BACKEND_HEALTH_RE.fullmatch(value) is not None
    )


def _decode_private_key(encoded: str) -> bytes:
    if not encoded:
        raise RuntimeError('support tunnel private key is not configured')
    try:
        private_key = base64.b64decode(encoded, validate=True)
        text = private_key.decode('ascii')
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('support tunnel private key is not valid base64') from exc
    if (
        len(private_key) > 32 * 1024
        or '\x00' in text
        or not text.startswith('-----BEGIN OPENSSH PRIVATE KEY-----\n')
        or not text.rstrip().endswith('-----END OPENSSH PRIVATE KEY-----')
    ):
        raise RuntimeError('support tunnel private key format is invalid')
    return private_key


def _known_host_pin(
    value: Any,
    *,
    host: str,
    ssh_port: int,
) -> tuple[str, str]:
    """Validate one exact Ed25519 host pin and return line + fingerprint."""
    line = str(value or '').strip()
    if not line or '\n' in line or '\r' in line:
        raise RuntimeError('a single pinned SSH known-host entry is required')
    fields = line.split()
    if len(fields) != 3:
        raise RuntimeError('the pinned SSH known-host entry must contain exactly one key')
    expected_host = host if ssh_port == 22 else f'[{host}]:{ssh_port}'
    if fields[0].lower() != expected_host.lower():
        raise RuntimeError('the pinned SSH known-host entry does not match the relay')
    if fields[1] != 'ssh-ed25519':
        raise RuntimeError('the relay host pin must use ssh-ed25519')
    try:
        blob = base64.b64decode(fields[2], validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('the relay host pin is not valid base64') from exc
    algorithm = b'ssh-ed25519'
    algorithm_end = 4 + len(algorithm)
    key_length_end = algorithm_end + 4
    if (
        len(blob) != key_length_end + 32
        or int.from_bytes(blob[:4], 'big') != len(algorithm)
        or blob[4:algorithm_end] != algorithm
        or int.from_bytes(blob[algorithm_end:key_length_end], 'big') != 32
    ):
        raise RuntimeError('the relay host pin is not an Ed25519 public key')
    fingerprint = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
    return line, f'SHA256:{fingerprint}'


def _validate_configuration(settings: dict[str, Any]) -> dict[str, Any]:
    destination_host, known_hosts_host = _ssh_host(settings.get('host'))
    user = _ssh_user(settings.get('user'))
    ssh_port = _port(settings.get('port'), 'SUPPORT_TUNNEL_PORT')
    remote_db = _port(
        settings.get('remote_db_port'),
        'SUPPORT_TUNNEL_REMOTE_DB_PORT',
    )
    remote_api = _port(
        settings.get('remote_api_port'),
        'SUPPORT_TUNNEL_REMOTE_API_PORT',
    )
    if remote_db < 1024 or remote_api < 1024:
        raise RuntimeError('support relay ports must be unprivileged ports')
    if remote_db == remote_api:
        raise RuntimeError('support relay DB and backend ports must be different')
    local_db = _port(
        settings.get('local_db_port') or '5433',
        'DB_PORT',
    )
    local_api = _port(settings.get('local_api_port'), 'PORT')
    private_key = _decode_private_key(str(settings.get('private_key_b64') or ''))
    known_host, fingerprint = _known_host_pin(
        settings.get('known_host'),
        host=known_hosts_host,
        ssh_port=ssh_port,
    )
    return {
        'destination_host': destination_host,
        'known_hosts_host': known_hosts_host,
        'user': user,
        'ssh_port': ssh_port,
        'remote_db_port': remote_db,
        'remote_api_port': remote_api,
        'local_db_port': local_db,
        'local_api_port': local_api,
        'private_key': private_key,
        'known_host': known_host,
        'host_fingerprint': fingerprint,
    }


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
        # The packaged PostgreSQL service normally listens on 5433. Honour an
        # explicitly provisioned local DB_PORT without ever accepting a remote
        # host: reverse forwards always terminate on this till's loopback.
        'local_db_port': str(
            os.environ.get('DB_PORT') or cfg.get('DB_PORT') or '5433'
        ).strip(),
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
    remove inheritance, and grant that SID read access only. Directories need
    inheritable full-control ACEs so future atomic replacements remain writable
    and inherit the same private boundary.
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

    grant = (
        f'*{sid}:(OI)(CI)(F)'
        if path.is_dir()
        else f'*{sid}:({rights})'
    )
    protected = _hidden_run([
        _windows_executable('icacls.exe'), str(path),
        '/inheritance:r', '/grant:r', grant,
    ])
    if protected.returncode != 0:
        detail = (protected.stderr or protected.stdout or '').strip()[-300:]
        raise RuntimeError(
            'could not restrict the support tunnel private-key ACL'
            + (f': {detail}' if detail else '')
        )


def _write_credentials(
    settings: dict[str, Any],
    validated: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    validated = validated or _validate_configuration(settings)
    private_key = validated['private_key']
    known_host = validated['known_host']
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        _harden_windows_private_key(SUPPORT_DIR, rights='F')
    else:
        SUPPORT_DIR.chmod(0o700)
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
        PRIVATE_KEY_FILE.unlink(missing_ok=True)
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
    validated = _validate_configuration(settings)
    key_file, known_hosts = _write_credentials(settings, validated)
    null_config = os.devnull
    return [
        _ssh_executable(),
        # Ignore user/system SSH client configuration so ProxyCommand,
        # LocalCommand, extra identities or hidden forwards cannot be injected.
        '-F', null_config,
        '-N', '-T',
        '-p', str(validated['ssh_port']),
        '-i', str(key_file),
        '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes',
        '-o', 'IdentityAgent=none',
        '-o', 'PreferredAuthentications=publickey',
        '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no',
        '-o', 'GSSAPIAuthentication=no',
        '-o', 'HostbasedAuthentication=no',
        '-o', 'NumberOfPasswordPrompts=0',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', f'UserKnownHostsFile={known_hosts}',
        '-o', f'GlobalKnownHostsFile={null_config}',
        '-o', 'HostKeyAlgorithms=ssh-ed25519',
        '-o', 'UpdateHostKeys=no',
        '-o', 'VerifyHostKeyDNS=no',
        '-o', 'CanonicalizeHostname=no',
        '-o', 'ProxyCommand=none',
        '-o', 'ProxyJump=none',
        '-o', 'PermitLocalCommand=no',
        '-o', 'ControlMaster=no',
        '-o', 'ControlPath=none',
        '-o', 'ForwardAgent=no',
        '-o', 'ForwardX11=no',
        '-o', 'RequestTTY=no',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'TCPKeepAlive=no',
        '-o', 'ConnectionAttempts=1',
        '-o', 'ConnectTimeout=10',
        '-o', 'LogLevel=ERROR',
        '-o', 'EscapeChar=none',
        '-R', (
            f'127.0.0.1:{validated["remote_db_port"]}:'
            f'127.0.0.1:{validated["local_db_port"]}'
        ),
        '-R', (
            f'127.0.0.1:{validated["remote_api_port"]}:'
            f'127.0.0.1:{validated["local_api_port"]}'
        ),
        f'{validated["user"]}@{validated["destination_host"]}',
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
    The API probe is an independent readiness gate. The UI does not report the
    support path fully ready unless both PostgreSQL and the backend health
    endpoint are freshly verified.
    """
    global _LAST_PROBE_AT, _LAST_PROBE_MONOTONIC
    global _LOCAL_DB_REACHABLE, _LOCAL_DB_QUERY_VERIFIED
    global _LOCAL_API_REACHABLE, _LAST_DB_PROBE_ERROR
    global _LAST_API_PROBE_ERROR, _LAST_PROBE_ERROR

    db_reachable = False
    db_query_verified = False
    api_reachable = False
    db_error = ''
    api_error = ''
    db_port = _port(settings.get('local_db_port') or '5433', 'DB_PORT')
    api_port = _port(settings['local_api_port'], 'PORT')
    try:
        with socket.create_connection(('127.0.0.1', db_port), timeout=1.5):
            db_reachable = True
    except OSError as exc:
        db_error = f'local PostgreSQL is not reachable: {exc}'

    if db_reachable:
        try:
            import psycopg
            with psycopg.connect(
                host='127.0.0.1', port=db_port,
                dbname=os.environ.get('DB_NAME') or 'alpha_pos',
                user=os.environ.get('DB_USER') or 'alpha_pos',
                password=os.environ.get('DB_PASSWORD') or 'alpha_pos',
                connect_timeout=2,
                application_name='alphapos_support_readiness',
            ) as connection:
                with connection.cursor() as cursor:
                    # Authentication/liveness only. Do not inspect restaurant
                    # business tables as part of readiness.
                    cursor.execute('SELECT 1')
                    row = cursor.fetchone()
                    db_query_verified = bool(row and row[0] == 1)
        except Exception as exc:  # noqa: BLE001 - status must remain available
            db_error = f'local PostgreSQL authentication probe failed: {exc}'

    try:
        request = urllib.request.Request(
            f'http://127.0.0.1:{api_port}/healthz',
            headers={'User-Agent': 'AlphaPOS-support-probe/1'},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            # The local edition returns ``ok <APP_GIT_SHA>`` while the shared
            # core URLconf returns ``ok``. Read beyond the maximum accepted
            # contract so an overlong or prefixed response cannot be mistaken
            # for this backend merely because its first bytes look familiar.
            body = response.read(128)
            api_reachable = (
                response.status == 200
                and _valid_backend_health_body(body)
            )
        if not api_reachable:
            api_error = 'local POS API health check did not return the expected response'
    except Exception as exc:  # noqa: BLE001 - the API may be intentionally off
        api_error = f'local POS API is not reachable: {exc}'

    db_error = _redact_text(db_error, settings)
    api_error = _redact_text(api_error, settings)
    errors = [error for error in (db_error, api_error) if error]

    with _LOCK:
        _LAST_PROBE_AT = _utc_now()
        _LAST_PROBE_MONOTONIC = time.monotonic()
        _LOCAL_DB_REACHABLE = db_reachable
        _LOCAL_DB_QUERY_VERIFIED = db_query_verified
        _LOCAL_API_REACHABLE = api_reachable
        _LAST_DB_PROBE_ERROR = db_error
        _LAST_API_PROBE_ERROR = api_error
        _LAST_PROBE_ERROR = '; '.join(errors)[:1000]


def _clear_probe_state() -> None:
    global _LAST_PROBE_AT, _LAST_PROBE_MONOTONIC
    global _LOCAL_DB_REACHABLE, _LOCAL_DB_QUERY_VERIFIED
    global _LOCAL_API_REACHABLE, _LAST_DB_PROBE_ERROR
    global _LAST_API_PROBE_ERROR, _LAST_PROBE_ERROR
    with _LOCK:
        _LAST_PROBE_AT = None
        _LAST_PROBE_MONOTONIC = None
        _LOCAL_DB_REACHABLE = False
        _LOCAL_DB_QUERY_VERIFIED = False
        _LOCAL_API_REACHABLE = False
        _LAST_DB_PROBE_ERROR = ''
        _LAST_API_PROBE_ERROR = ''
        _LAST_PROBE_ERROR = ''


def _supervisor() -> None:
    global _PROCESS, _LAST_ERROR, _LAST_ATTEMPT_AT
    global _LAST_CONNECTED_AT, _LAST_EXIT_CODE, _LAST_SESSION_VERIFIED_AT
    global _RECONNECT_ATTEMPT, _CURRENT_BACKOFF_SECONDS, _NEXT_RETRY_AT
    backoff = 3
    while not _STOP.is_set():
        connected_started: float | None = None
        settings: dict[str, Any] = {}
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
                    _RECONNECT_ATTEMPT = 0
                    _CURRENT_BACKOFF_SECONDS = 0
                    _NEXT_RETRY_AT = None
                _clear_probe_state()
                backoff = 3
                _STOP.wait(5)
                continue
            with _LOCK:
                _RECONNECT_ATTEMPT += 1
                _LAST_ATTEMPT_AT = _utc_now()
                _CURRENT_BACKOFF_SECONDS = 0
                _NEXT_RETRY_AT = None
            process = _hidden_popen(_command(settings))
            with _LOCK:
                _PROCESS = process
                _LAST_ERROR = ''
                _LAST_EXIT_CODE = None
                _LAST_SESSION_VERIFIED_AT = None
            connected_started = time.monotonic()
            # Do not authenticate to the restaurant database until OpenSSH has
            # survived its bounded connection window with both forwards
            # accepted. The verified SSH session is the readiness boundary.
            next_probe = connected_started + _SESSION_VERIFY_AFTER_SECONDS
            session_verified = False
            while not _STOP.wait(1):
                code = process.poll()
                if code is None:
                    now = time.monotonic()
                    # ``Popen`` only proves ssh.exe started. Keep the UI in
                    # CONNECTING through OpenSSH's ten-second connect timeout;
                    # surviving beyond it with ExitOnForwardFailure enabled is
                    # our fail-closed evidence that authentication and both
                    # reverse listeners completed.
                    if (
                        now - connected_started >= _SESSION_VERIFY_AFTER_SECONDS
                        and not session_verified
                    ):
                        verified_at = _utc_now()
                        with _LOCK:
                            _LAST_SESSION_VERIFIED_AT = verified_at
                            _LAST_CONNECTED_AT = verified_at
                            _RECONNECT_ATTEMPT = 0
                        session_verified = True
                    if session_verified and now >= next_probe:
                        _probe_local_targets(settings)
                        next_probe = now + 10
                    continue
                _, stderr = process.communicate(timeout=1)
                with _LOCK:
                    _LAST_EXIT_CODE = code
                    _LAST_SESSION_VERIFIED_AT = None
                    _LAST_ERROR = _redact_text(
                        stderr or f'ssh exited with code {code}',
                        settings,
                    )[-500:]
                break
        except Exception as exc:  # noqa: BLE001 - reconnect loop owns failures
            error = _redact_text(exc, settings)
            with _LOCK:
                _LAST_ERROR = error[:500]
            logger.warning('support tunnel unavailable: %s', _LAST_ERROR)
        finally:
            with _LOCK:
                process = _PROCESS
                _PROCESS = None
                _LAST_SESSION_VERIFIED_AT = None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            _clear_probe_state()
        if not _STOP.is_set():
            # Fast authentication/config/forward failures back off instead of
            # spawning ssh every three seconds forever. A connection that stayed
            # healthy for a minute resets recovery to the fast first retry.
            stable = (
                connected_started is not None
                and time.monotonic() - connected_started >= 60
            )
            delay = 3 if stable else backoff
            with _LOCK:
                _CURRENT_BACKOFF_SECONDS = delay
                _NEXT_RETRY_AT = _utc_after(delay)
            _STOP.wait(delay)
            with _LOCK:
                _CURRENT_BACKOFF_SECONDS = 0
                _NEXT_RETRY_AT = None
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
    global _THREAD, _LAST_SESSION_VERIFIED_AT
    global _CURRENT_BACKOFF_SECONDS, _NEXT_RETRY_AT, _RECONNECT_ATTEMPT
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
            _LAST_SESSION_VERIFIED_AT = None
            _CURRENT_BACKOFF_SECONDS = 0
            _NEXT_RETRY_AT = None
            _RECONNECT_ATTEMPT = 0
        _clear_probe_state()
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
    try:
        settings = _settings()
        settings_error = ''
    except Exception as exc:  # noqa: BLE001 - status must remain callable
        settings = {
            'enabled': False,
            'host': '',
            'port': '22',
            'user': '',
            'remote_db_port': '15433',
            'remote_api_port': '18000',
            'private_key_b64': '',
            'known_host': '',
            'local_db_port': '5433',
            'local_api_port': '8000',
        }
        settings_error = _redact_text(exc)

    validated: dict[str, Any] | None = None
    configuration_error = settings_error
    if not configuration_error:
        try:
            validated = _validate_configuration(settings)
        except Exception as exc:  # noqa: BLE001 - report, never crash the UI
            configuration_error = _redact_text(exc, settings)

    with _LOCK:
        process = _PROCESS
        configured = validated is not None
        ssh_process_alive = bool(
            process is not None and process.poll() is None
        )
        session_verified = bool(
            ssh_process_alive and _LAST_SESSION_VERIFIED_AT
        )
        probe_fresh = bool(
            _LAST_PROBE_MONOTONIC is not None
            and time.monotonic() - _LAST_PROBE_MONOTONIC
            <= _PROBE_MAX_AGE_SECONDS
        )
        db_ready = bool(
            settings['enabled'] and configured and session_verified
            and probe_fresh and _LOCAL_DB_REACHABLE
            and _LOCAL_DB_QUERY_VERIFIED
        )
        backend_ready = bool(
            settings['enabled'] and configured and session_verified
            and probe_fresh and _LOCAL_API_REACHABLE
        )
        ready = db_ready and backend_ready
        if not settings['enabled']:
            state = 'off'
        elif not configured:
            state = 'configuration_required'
        elif ready:
            state = 'ready'
        elif db_ready or backend_ready:
            state = 'partial_ready'
        elif session_verified and _LAST_PROBE_AT:
            state = 'degraded'
        elif ssh_process_alive:
            state = 'connecting'
        elif _LAST_ERROR:
            state = 'error'
        else:
            state = 'connecting'

        if not settings['enabled']:
            db_state = backend_state = 'off'
        elif not configured:
            db_state = backend_state = 'configuration_required'
        elif not session_verified:
            db_state = backend_state = 'waiting_for_tunnel'
        elif not probe_fresh:
            db_state = backend_state = 'checking'
        else:
            db_state = 'ready' if db_ready else 'unavailable'
            backend_state = 'ready' if backend_ready else 'unavailable'

        relay_host = (
            validated['known_hosts_host'] if validated is not None else ''
        )
        remote_db = (
            f'127.0.0.1:{validated["remote_db_port"]}'
            if validated is not None else ''
        )
        remote_api = (
            f'127.0.0.1:{validated["remote_api_port"]}'
            if validated is not None else ''
        )
        last_error = _redact_text(_LAST_ERROR, settings)
        last_db_probe_error = _redact_text(
            _LAST_DB_PROBE_ERROR, settings,
        )
        last_api_probe_error = _redact_text(
            _LAST_API_PROBE_ERROR, settings,
        )
        last_probe_error = _redact_text(_LAST_PROBE_ERROR, settings)
        return {
            'enabled': settings['enabled'],
            'configured': configured,
            'worker_alive': bool(_THREAD is not None and _THREAD.is_alive()),
            # ``connected`` retains the legacy field name but now means a
            # verified SSH session rather than merely a running ssh.exe PID.
            'connected': session_verified,
            'ssh_process_alive': ssh_process_alive,
            'session_verified': session_verified,
            'remote_forward_established': session_verified,
            'probe_fresh': probe_fresh,
            'db_ready': db_ready,
            'backend_ready': backend_ready,
            'ready': ready,
            'state': state,
            'db_status': db_state,
            'backend_status': backend_state,
            'db_label': 'DB Ready' if db_ready else 'DB Not Ready',
            'backend_label': (
                'Backend Ready' if backend_ready else 'Backend Not Ready'
            ),
            'readiness': {
                'database': db_state,
                'backend': backend_state,
            },
            'relay_host': relay_host,
            'remote_db': remote_db,
            'remote_api': remote_api,
            'connector_artifact': 'AlphaPOS-Support-Connector.ps1',
            'operator_db': '127.0.0.1:25433',
            'operator_api': 'http://127.0.0.1:28000',
            'operator_readiness_instruction': (
                'Run the support connector only while DB Ready and '
                'Backend Ready are both shown.'
            ),
            'operator_access_warning': (
                'The connector grants full database and backend access. '
                'Protect the inspector key and close the connector when done.'
            ),
            'pinned_host_fingerprint': (
                validated['host_fingerprint'] if validated is not None else ''
            ),
            'configuration_error': configuration_error,
            'last_attempt_at': _LAST_ATTEMPT_AT,
            'last_connected_at': _LAST_CONNECTED_AT,
            'session_verified_at': _LAST_SESSION_VERIFIED_AT,
            'last_probe_at': _LAST_PROBE_AT,
            'local_db_reachable': _LOCAL_DB_REACHABLE,
            'local_db_query_verified': _LOCAL_DB_QUERY_VERIFIED,
            'local_api_reachable': _LOCAL_API_REACHABLE,
            'last_db_probe_error': last_db_probe_error,
            'last_backend_probe_error': last_api_probe_error,
            'last_probe_error': last_probe_error,
            'reconnect_attempt': _RECONNECT_ATTEMPT,
            'retry_backoff_seconds': _CURRENT_BACKOFF_SECONDS,
            'next_retry_at': _NEXT_RETRY_AT,
            'last_exit_code': _LAST_EXIT_CODE,
            'last_error': last_error,
        }
