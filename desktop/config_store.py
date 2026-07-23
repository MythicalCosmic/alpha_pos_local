"""Local config + secret management for the desktop app.

Everything the operator enters lives in the persistent data directory's .env
(the same variables settings.py reads). Secrets (SECRET_KEY, license Fernet key)
are generated once and persisted beside it. From source the data directory is
the project root; a frozen build uses %LOCALAPPDATA%\\AlphaPOS. Desktop-only flags
(ToS acceptance and setup signature) live in desktop_state.json.

NOTE: .env holds this ONE business's own fiscal credentials. It is never shared
between installs.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


logger = logging.getLogger('desktop.config')


class ConfigError(RuntimeError):
    """A persistent desktop configuration could not be read safely."""


_IO_LOCK = threading.RLock()
_ACL_LOCK = threading.RLock()
_ENV_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_WINDOWS_SID_RE = re.compile(r'^S-\d+(?:-\d+)+$', re.IGNORECASE)
_WINDOWS_SID: str | None = None
_HARDENED_WINDOWS_PATHS: set[tuple[str, bool, bool]] = set()
_last_env_error = ''
_last_env_keys: tuple[str, ...] = ()
_env_applied = False


def _data_dir() -> Path:
    """Persistent, writable data dir. In a packaged build BASE_DIR is a temp
    extraction dir wiped each launch, so we store DB/secrets/config under
    %LOCALAPPDATA%\\AlphaPOS instead. From source, use the project root.

    CRITICAL (auto-boot bug): LOCALAPPDATA is frequently MISSING from the
    environment when the app is launched from the Startup folder at logon — that
    launch context does not always inherit the full interactive user environment.
    The old fallback `os.environ.get('LOCALAPPDATA') or str(Path.home())` then
    resolved to  <home>\\AlphaPOS  — a DIFFERENT, empty directory than the manual
    launch's  <home>\\AppData\\Local\\AlphaPOS  — so an auto-started till opened a
    brand-new install: no .env, freshly generated secrets, a new empty DB, the
    license UNREGISTERED and the kill switch ON. Derive the canonical
    AppData\\Local path from USERPROFILE/home when LOCALAPPDATA is absent so an
    auto-boot and a manual launch ALWAYS use the same data dir."""
    if getattr(sys, 'frozen', False):
        base = (os.environ.get('LOCALAPPDATA') or '').strip()
        if not base:
            home = (os.environ.get('USERPROFILE') or os.environ.get('HOME')
                    or str(Path.home()))
            base = str(Path(home) / 'AppData' / 'Local')
        return Path(os.path.expandvars(base)).expanduser() / 'AlphaPOS'
    return Path(__file__).resolve().parent.parent


DATA_DIR = _data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = DATA_DIR / '.env'
SECRET_FILE = DATA_DIR / '.secret_key'
FERNET_FILE = DATA_DIR / '.license_fernet_key'
DEVICE_FILE = DATA_DIR / '.device_id'
STATE_FILE = DATA_DIR / 'desktop_state.json'
CREDS_FILE = DATA_DIR / 'admin_credentials.json'
LEGACY_MIGRATION_MARKER = DATA_DIR / '.legacy_env_migrated'
LEGACY_PG_MIGRATION_MARKER = DATA_DIR / '.legacy_pgdata_migrated'
# Marker written by a factory reset so a leftover (locked) DB is wiped on the
# next launch, before Django opens it.
RESET_FLAG = DATA_DIR / '.reset_pending'

# The fields the control-panel config form manages, with sensible defaults.
# Grouped only for the UI; stored flat in .env.
CONFIG_FIELDS = [
    # General
    # Tenant identity is provisioned per restaurant. Never bake one live
    # branch/token into a redistributable installer.
    ('BRANCH_ID', ''),
    ('DEPLOYMENT_MODE', 'local'),
    ('PORT', '8000'),
    # Licensing / control center
    ('LICENSE_CONTROL_CENTER_URL', 'https://control.78.111.91.113.nip.io/'),
    # Self-update: base URL the signed tufup repo is served from (…/updates/metadata/
    # + …/updates/targets/). Read by desktop/updater.py; blank disables updates.
    # Points at the CONTROL CENTER (pos_control serves /updates) — publish a release
    # there once and every till pulls it on next launch. See RELEASES.md.
    ('ALPHA_POS_UPDATE_URL', 'https://control.78.111.91.113.nip.io/updates'),
    # The endpoint may be public knowledge, but enabling sync requires a
    # restaurant-specific branch id + token entered during provisioning.
    ('SYNC_ENABLED', 'False'),
    ('CLOUD_SYNC_URL', 'https://pos.78.111.90.65.nip.io/api/sync'),
    ('CLOUD_SYNC_TOKEN', ''),
    # Optional authorized support tunnel. The relay is outbound-only and its
    # reverse listeners are always bound to relay loopback by support_tunnel.py.
    ('SUPPORT_TUNNEL_ENABLED', 'False'),
    ('SUPPORT_TUNNEL_HOST', ''),
    ('SUPPORT_TUNNEL_PORT', '22'),
    ('SUPPORT_TUNNEL_USER', 'alphapos-support'),
    ('SUPPORT_TUNNEL_REMOTE_DB_PORT', '15433'),
    ('SUPPORT_TUNNEL_REMOTE_API_PORT', '18000'),
    ('SUPPORT_TUNNEL_PRIVATE_KEY_B64', ''),
    ('SUPPORT_TUNNEL_KNOWN_HOST', ''),
    # Telegram (token + chat ids drive real message delivery)
    ('TELEGRAM_BOT_TOKEN', ''),   # staff/internal bot token — set via the desktop panel
    ('TELEGRAM_CHAT_IDS', ''),    # staff chat ids — set via the desktop panel
    # Owner-only recipients for raw order/sync evidence. A blank value disables
    # delivery; raw evidence never falls back to the broader staff recipient list.
    ('ORDER_AUDIT_TELEGRAM_CHAT_IDS', ''),
    # Separate owner-facing LOCAL order/shift notifications. These credentials
    # never fall back to the staff bot or raw-evidence channel, and delivery goes
    # directly from this PC to Telegram rather than through AlphaPOS cloud.
    ('LOCAL_TELEGRAM_AUDIT_ENABLED', 'False'),
    ('LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED', 'True'),
    ('LOCAL_TELEGRAM_ORDER_PAID_ENABLED', 'True'),
    ('LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED', 'True'),
    ('LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT', 'TXT'),
    ('LOCAL_TELEGRAM_AUDIT_BOT_TOKEN', ''),
    ('LOCAL_TELEGRAM_AUDIT_CHAT_IDS', ''),
    ('TELEGRAM_WEBHOOK_SECRET', ''),
    # AI lives on the SERVER edition only (centralized Gemini calls against the
    # cloud's sales/stock data). The desktop/local edition ships NO AI — no keys
    # and no provider config here, so a till never makes its own LLM calls.
    # Fiscalization (this business's OWN identity)
    ('FISCALIZATION_MODE', 'off'),
    ('FISCAL_PROVIDER', 'mock'),
    ('FISCAL_TIN', ''),
    ('FISCAL_PROVIDER_URL', ''),
    ('FISCAL_MERCHANT_ID', ''),
    ('FISCAL_SECRET', ''),
    ('FISCAL_VAT_PERCENT', '0'),
    ('FISCAL_BLOCK_ON_FAILURE', 'false'),
]

SECRET_KEYS = {
    'FISCAL_SECRET', 'CLOUD_SYNC_TOKEN', 'TELEGRAM_BOT_TOKEN',
    'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN',
    'TELEGRAM_WEBHOOK_SECRET', 'SUPPORT_TUNNEL_PRIVATE_KEY_B64',
}


def _windows_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable:
        return executable
    candidate = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32' / name
    if candidate.exists():
        return str(candidate)
    raise ConfigError(f'{name} is required to protect desktop secrets')


def _hidden_windows_command(command: list[str]) -> subprocess.CompletedProcess:
    kwargs = {
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'text': True,
        'timeout': 10,
        'check': False,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(command, **kwargs)


def _current_windows_sid() -> str:
    global _WINDOWS_SID
    with _ACL_LOCK:
        if _WINDOWS_SID:
            return _WINDOWS_SID
        result = _hidden_windows_command([
            _windows_executable('whoami.exe'), '/user', '/fo', 'csv', '/nh',
        ])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip()[-300:]
            raise ConfigError(
                'Could not resolve the Windows account used to protect desktop secrets'
                + (f': {detail}' if detail else '')
            )
        try:
            sid = str(next(csv.reader(io.StringIO(result.stdout or '')))[1]).strip()
        except (IndexError, StopIteration, csv.Error) as exc:
            raise ConfigError(
                'Could not parse the Windows account used to protect desktop secrets'
            ) from exc
        if not _WINDOWS_SID_RE.fullmatch(sid):
            raise ConfigError('Windows returned an invalid account SID')
        _WINDOWS_SID = sid
        return sid


def _harden_windows_private_path(
    path: Path, *, directory: bool = False, recursive: bool = False,
) -> None:
    """Restrict packaged desktop data to the Windows account running Alpha POS.

    POS configuration contains the cloud token, Telegram token and the private
    support-tunnel key. ``chmod(0600)`` does not create a private Windows DACL,
    so files below a broadly inherited profile directory remained readable by
    other local accounts. Harden the parent before creating atomic temp files;
    replacements then inherit the private DACL without spawning ``icacls`` on
    every order-audit index flush.

    Source checkouts are deliberately excluded so a developer test run cannot
    rewrite repository ACLs. Packaged installs always live on the user's NTFS
    LocalAppData volume.
    """
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        return
    path = Path(path)
    if not path.exists():
        return
    try:
        identity = str(path.resolve())
    except OSError:
        identity = str(path.absolute())
    cache_key = (identity.casefold(), bool(directory), bool(recursive))
    with _ACL_LOCK:
        if cache_key in _HARDENED_WINDOWS_PATHS:
            return
        sid = _current_windows_sid()
        rights = '(OI)(CI)F' if directory else 'F'
        command = [
            _windows_executable('icacls.exe'), str(path),
            '/inheritance:r', '/grant:r', f'*{sid}:{rights}',
        ]
        if recursive:
            command.extend(['/T', '/C'])
        result = _hidden_windows_command(command)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip()[-300:]
            raise ConfigError(
                f'Could not restrict access to private Alpha POS data at {path}'
                + (f': {detail}' if detail else '')
            )
        _HARDENED_WINDOWS_PATHS.add(cache_key)


def _write_protected(path: Path, contents: str) -> None:
    """Atomically replace a config/secret file with restrictive permissions.

    Direct ``write_text`` truncates first. A power loss, updater restart, or
    concurrent panel request could therefore leave a partial .env and make the
    next boot use baked defaults for the wrong branch. A same-directory temp
    file plus ``os.replace`` makes the visible update atomic. The short bounded
    retry handles transient Windows antivirus/indexer sharing races.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _harden_windows_private_path(path.parent, directory=True)
    with _IO_LOCK:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent),
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(contents)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            for attempt, delay in enumerate((0.0, 0.05, 0.15)):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(delay)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _read_text(path: Path, *, label: str) -> str:
    try:
        _harden_windows_private_path(path.parent, directory=True)
        _harden_windows_private_path(path)
        # utf-8-sig also accepts ordinary UTF-8 and strips a BOM produced by
        # common Windows editors. Never ignore decoding errors in credentials.
        return path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f'Could not read {label} at {path}: {exc}') from exc


def load_or_generate_secret() -> str:
    if SECRET_FILE.exists():
        value = _read_text(SECRET_FILE, label='secret key').strip()
        if value:
            return value
        logger.warning('secret key file was empty; repairing it')
    key = secrets.token_urlsafe(64)
    _write_protected(SECRET_FILE, key + '\n')
    return key


def load_or_generate_fernet() -> str:
    if FERNET_FILE.exists():
        key = _read_text(FERNET_FILE, label='license encryption key').strip()
        if not key:
            raise ConfigError(
                f'License encryption key is empty at {FERNET_FILE}; restore it '
                'from backup instead of generating a replacement.'
            )
        try:
            from cryptography.fernet import Fernet
            Fernet(key.encode('ascii'))
        except (ValueError, UnicodeError) as exc:
            raise ConfigError(
                f'License encryption key is invalid at {FERNET_FILE}; restore '
                'the original key instead of rotating it.'
            ) from exc
        return key
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode('ascii')
    _write_protected(FERNET_FILE, key + '\n')
    return key


def load_or_generate_device_id() -> str:
    """Stable per-install till id (not a secret) — identifies THIS terminal to the
    cloud presence registry so a delivery order can be auto-dispatched to the
    active cashier on a connected POS. Survives restarts; regenerated only on a
    factory reset (the data dir is wiped)."""
    if DEVICE_FILE.exists():
        existing = _read_text(DEVICE_FILE, label='device id').strip()
        if existing:
            return existing
    device_id = secrets.token_hex(16)
    _write_protected(DEVICE_FILE, device_id + '\n')
    return device_id


def _parse_env_value(raw: str, line_number: int, source_path: Path) -> str:
    value = raw.strip()
    if not value:
        return ''
    if value[0] in ('"', "'"):
        quote = value[0]
        if quote == '"':
            try:
                parsed, end = json.JSONDecoder().raw_decode(value)
            except (ValueError, TypeError) as exc:
                raise ConfigError(
                    f'Invalid quoted value in {source_path} line {line_number}'
                ) from exc
            remainder = value[end:].strip()
            if remainder and not remainder.startswith('#'):
                raise ConfigError(
                    f'Unexpected text after quoted value in {source_path} line {line_number}'
                )
            return str(parsed)
        escaped = False
        end = None
        for index, character in enumerate(value[1:], 1):
            if character == quote and not escaped:
                end = index
                break
            escaped = character == '\\' and not escaped
            if character != '\\':
                escaped = False
        if end is None:
            raise ConfigError(f'Unclosed quote in {source_path} line {line_number}')
        remainder = value[end + 1:].strip()
        if remainder and not remainder.startswith('#'):
            raise ConfigError(
                f'Unexpected text after quoted value in {source_path} line {line_number}'
            )
        return value[1:end].replace("\\'", "'").replace('\\\\', '\\')
    # dotenv-style inline comments start only after whitespace. Tokens such as
    # ``abc#123`` are preserved verbatim.
    return re.split(r'\s+#', value, maxsplit=1)[0].rstrip()


def parse_env_file(path: Path | None = None) -> dict:
    """Parse the canonical desktop .env without silently losing values.

    Supports UTF-8 BOMs, ``export KEY=...``, quoted values and inline comments.
    Invalid non-comment lines are fatal: starting with partial baked defaults
    after damaging a branch/token file can sync the till as the wrong branch.
    """
    source_path = path or ENV_FILE
    data = {}
    if not source_path.exists():
        return data
    with _IO_LOCK:
        text = _read_text(source_path, label='desktop environment')
    for line_number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        if '=' not in line:
            raise ConfigError(
                f'Invalid entry in {source_path} line {line_number}: expected KEY=value'
            )
        key, _, raw_value = line.partition('=')
        key = key.strip()
        if not _ENV_KEY_RE.fullmatch(key):
            raise ConfigError(
                f'Invalid environment key {key!r} in {source_path} line {line_number}'
            )
        data[key] = _parse_env_value(raw_value, line_number, source_path)
    return data


def _legacy_env_candidates() -> tuple[Path, ...]:
    """Known pre-canonical locations, in deterministic precedence order."""
    if not getattr(sys, 'frozen', False):
        return ()
    candidates = [
        # Old frozen fallback when LOCALAPPDATA was absent.
        Path.home() / 'AlphaPOS' / '.env',
    ]
    local = (os.environ.get('LOCALAPPDATA') or '').strip()
    if local:
        candidates.append(Path(os.path.expandvars(local)) / 'AlphaPOS' / '.env')
    candidates.extend([
        Path(sys.executable).resolve().parent / '.env',
        Path.cwd() / '.env',
        Path(__file__).resolve().parent.parent / '.env',
    ])
    canonical = ENV_FILE.resolve()
    unique = []
    seen = {canonical}
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def migrate_legacy_env_if_needed() -> Path | None:
    """Move one valid persisted legacy .env into the canonical data directory.

    The canonical file always wins and is never overwritten. A durable marker
    prevents an undeletable exe-adjacent legacy file from being resurrected
    after an intentional factory reset.
    """
    if ENV_FILE.exists() or LEGACY_MIGRATION_MARKER.exists():
        return None
    recognized = {key for key, _default in CONFIG_FIELDS} | set(_INSTALL_VALUE_FILES)
    for candidate in _legacy_env_candidates():
        if not candidate.is_file():
            continue
        try:
            parsed = parse_env_file(candidate)
        except ConfigError:
            logger.exception('ignoring unreadable legacy environment at %s', candidate)
            continue
        # Avoid importing an unrelated project's .env merely because the app
        # happened to be launched from that directory.
        if len(recognized.intersection(parsed)) < 2:
            logger.warning('ignoring unrelated legacy .env candidate at %s', candidate)
            continue
        contents = _read_text(candidate, label='legacy desktop environment')
        with _IO_LOCK:
            if ENV_FILE.exists():
                return None
            _write_protected(ENV_FILE, contents)
            _write_protected(LEGACY_MIGRATION_MARKER, 'migrated\n')
        try:
            candidate.unlink()
        except OSError:
            # Program Files can be read-only. The marker prevents re-import.
            logger.info('legacy .env migrated but source could not be removed: %s', candidate)
        logger.info('migrated persisted desktop environment into %s', ENV_FILE)
        return candidate
    return None


def read_config() -> dict:
    """Current config values for the form (existing .env merged over defaults)."""
    env = parse_env_file()
    return {k: env.get(k, default) for k, default in CONFIG_FIELDS}


def write_config(values: dict) -> None:
    """Persist the form values into .env, preserving any unmanaged keys."""
    with _IO_LOCK:
        existing = parse_env_file()
        for k, default in CONFIG_FIELDS:
            if k in values and values[k] is not None:
                existing[k] = str(values[k])
            else:
                existing.setdefault(k, default)
        lines = ['# Alpha POS configuration — generated by the desktop control panel',
                 '# This file holds THIS business\'s own settings + fiscal identity.', '']
        for k in sorted(existing):
            value = str(existing[k])
            if '\n' in value or '\r' in value:
                raise ConfigError(f'Configuration value {k} may not contain a newline')
            if (value != value.strip() or re.search(r'\s+#', value)
                    or value.startswith(('"', "'"))):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f'{k}={value}')
        _write_protected(ENV_FILE, '\n'.join(lines) + '\n')


def _wipe_data() -> list:
    """Delete ALL local data — DB, generated secrets, saved config/state, logs,
    static and media — so the next launch is a clean first install. Returns the
    paths actually removed. Best-effort: a file locked by a live DB connection
    is skipped here and finished by consume_reset_pending() on the next launch.
    """
    import shutil
    # The local edition runs embedded Postgres, not SQLite — stop it so its data
    # cluster can be removed, then wipe the cluster. Otherwise a "factory reset"
    # leaves every order / product / user + the prior admin's creds intact (a
    # resale data leak) while .env/secrets DO get deleted -> half-wiped install.
    try:
        from desktop import pg_embedded
        pg_embedded.stop()
    except Exception:
        pass
    targets = [
        DATA_DIR / 'db.sqlite3', DATA_DIR / 'db.sqlite3-wal', DATA_DIR / 'db.sqlite3-shm',
        DATA_DIR / 'pgdata',  # embedded Postgres cluster — re-initialised fresh next launch
        ENV_FILE, SECRET_FILE, FERNET_FILE, DEVICE_FILE, STATE_FILE, CREDS_FILE,
        DATA_DIR / '.control_token',
        DATA_DIR / 'logs', DATA_DIR / 'staticfiles', DATA_DIR / 'private_media',
        DATA_DIR / 'edge-profile', DATA_DIR / 'order_audit',
        DATA_DIR / 'local_telegram_audit',
        DATA_DIR / 'support_tunnel',
    ]
    removed = []
    for p in targets:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                removed.append(str(p))
            elif p.exists():
                p.unlink()
                removed.append(str(p))
        except OSError:
            pass  # locked (live DB) — consume_reset_pending() retries next launch
    return removed


def factory_reset() -> dict:
    """Wipe everything now and arm a pending-reset marker so any file still
    locked by the running process is removed on the next launch."""
    removed = _wipe_data()
    try:
        _write_protected(RESET_FLAG, '1\n')
    except OSError:
        pass
    return {'removed': removed}


def consume_reset_pending() -> bool:
    """If a reset was armed, finish it before Django touches the DB. Runs at the
    very start of apply_env_to_process so the wipe happens in a fresh process
    where nothing holds the sqlite file open."""
    pending = RESET_FLAG.exists()
    if pending:
        _wipe_data()
        critical = [
            DATA_DIR / 'db.sqlite3', DATA_DIR / 'db.sqlite3-wal',
            DATA_DIR / 'db.sqlite3-shm', DATA_DIR / 'pgdata', ENV_FILE,
            SECRET_FILE, FERNET_FILE, DEVICE_FILE, STATE_FILE, CREDS_FILE,
            DATA_DIR / 'order_audit', DATA_DIR / 'local_telegram_audit',
            DATA_DIR / 'support_tunnel',
        ]
        remaining = [path for path in critical if path.exists()]
        if remaining:
            raise ConfigError(
                'Factory reset could not remove locked data: '
                + ', '.join(path.name for path in remaining)
            )
        try:
            RESET_FLAG.unlink(missing_ok=True)
        except OSError as exc:
            raise ConfigError(f'Could not clear factory-reset marker: {exc}') from exc
    return pending


_INSTALL_VALUE_FILES = {
    'SECRET_KEY': SECRET_FILE,
    'LICENSE_FERNET_KEY': FERNET_FILE,
    'DEVICE_ID': DEVICE_FILE,
}


def _resolve_install_value(env: dict, key: str, loader) -> str:
    """Migrate legacy .env-owned identity values into their atomic sidecars.

    Older builds allowed these keys in .env to override the generated files.
    Ignoring that value now would rotate cookie/license/device identity. Preserve
    it once, validate the encryption key, and make the sidecar canonical.
    """
    legacy = str(env.get(key) or '').strip()
    if not legacy:
        return loader()
    if key == 'LICENSE_FERNET_KEY':
        try:
            from cryptography.fernet import Fernet
            Fernet(legacy.encode('ascii'))
        except (ValueError, UnicodeError) as exc:
            raise ConfigError(f'{key} in {ENV_FILE} is invalid') from exc
    target = _INSTALL_VALUE_FILES[key]
    current = ''
    if target.exists():
        current = _read_text(target, label=key).strip()
    if current != legacy:
        _write_protected(target, legacy + '\n')
        logger.info('migrated legacy %s from .env to its persistent sidecar', key)
    return legacy


def apply_env_to_process() -> None:
    """Load .env + the generated secrets into os.environ. MUST run before
    django.setup() so settings.py sees them."""
    global _last_env_error, _last_env_keys, _env_applied
    # Finish any armed factory reset first — before secrets are regenerated.
    try:
        reset_consumed = consume_reset_pending()
        if reset_consumed:
            # Never resurrect an old exe/cwd-adjacent config after the operator
            # deliberately reset this install.
            # Overwrite even a prior split/migrated marker: reset successfully
            # removed canonical data and explicitly authorizes a new empty store.
            _write_protected(LEGACY_MIGRATION_MARKER, 'factory-reset\n')
            _write_protected(LEGACY_PG_MIGRATION_MARKER, 'factory-reset\n')
        else:
            migrate_legacy_env_if_needed()
        env = parse_env_file()
        secret = _resolve_install_value(env, 'SECRET_KEY', load_or_generate_secret)
        fernet = _resolve_install_value(
            env, 'LICENSE_FERNET_KEY', load_or_generate_fernet,
        )
        device = _resolve_install_value(env, 'DEVICE_ID', load_or_generate_device_id)

        frozen = getattr(sys, 'frozen', False)
        port_default = dict(CONFIG_FIELDS).get('PORT', '8000')
        # A packaged launch is governed by its persistent config, not whatever
        # PORT happened to exist in the process that started it.
        port_text = str(env.get(
            'PORT', port_default if frozen else os.environ.get('PORT', port_default),
        ) or port_default)
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ConfigError(f'PORT must be an integer, got {port_text!r}') from exc
        if not 1 <= port <= 65535:
            raise ConfigError(f'PORT must be between 1 and 65535, got {port}')

        # These define the packaged edition and persistent install identity.
        # Force them rather than inheriting an unrelated shell/service env.
        os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
        os.environ['ALPHA_POS_DATA_DIR'] = str(DATA_DIR)
        os.environ['SECRET_KEY'] = secret
        os.environ['LICENSE_FERNET_KEY'] = fernet
        os.environ['DEVICE_ID'] = device

        os.environ.setdefault('DEBUG', 'False')
        os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1')
        os.environ.setdefault('OPEN_LAN', 'True')
        for config_key, default in CONFIG_FIELDS:
            if frozen:
                # The persistent file is authoritative for every managed field,
                # including blank values. Otherwise a packaged app launched from
                # a hostile/stale parent shell can inherit another restaurant's
                # branch/token, and removing a value from .env does not clear the
                # previous in-process value on re-apply.
                os.environ[config_key] = str(env.get(config_key, default))
            elif default != '':
                # Source runs may intentionally override defaults from their
                # shell; explicit .env entries below still take precedence.
                os.environ.setdefault(config_key, default)
        protected = set(_INSTALL_VALUE_FILES) | {
            'DJANGO_SETTINGS_MODULE', 'ALPHA_POS_DATA_DIR',
        }
        for key, value in env.items():
            if key not in protected:
                os.environ[key] = value
        if frozen:
            # DB_* is intentionally editable only through the persistent .env
            # (for the rare external-Postgres deployment). Never let an inherited
            # DB_HOST silently divert a till to another/empty database.
            for key in (
                'DB_ENGINE', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT',
            ):
                if key not in env:
                    os.environ.pop(key, None)
        # A shipped app must never inherit DEBUG=True and re-enable development
        # license bypasses merely because it was launched from a developer shell.
        if frozen:
            os.environ['DEBUG'] = 'False'

        _last_env_error = ''
        _last_env_keys = tuple(sorted(env))
        _env_applied = True
    except Exception as exc:
        _last_env_error = str(exc)
        _env_applied = False
        logger.exception('desktop environment load failed')
        raise
    # The desktop binds the POS to the whole LAN (0.0.0.0), so devices reach it
    # by this machine's LAN IP / hostname. Allow any Host header — this is a
    # trusted-LAN appliance; auth + licensing are the real boundary, not Host
    # validation. (Ensures DHCP IP changes never lock the network out.)
    hosts = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
    if '*' not in hosts:
        hosts.append('*')
        os.environ['ALLOWED_HOSTS'] = ','.join(hosts)


def env_status() -> dict:
    """Non-secret diagnostics for the control panel and support logs."""
    return {
        'path': str(ENV_FILE),
        'exists': ENV_FILE.exists(),
        'loaded': _env_applied and not bool(_last_env_error),
        'error': _last_env_error,
        'key_count': len(_last_env_keys),
    }


def read_state() -> dict:
    if STATE_FILE.exists():
        try:
            with _IO_LOCK:
                return json.loads(_read_text(STATE_FILE, label='desktop state'))
        except (ValueError, ConfigError):
            return {}
    return {}


def write_state(state: dict) -> None:
    _write_protected(STATE_FILE, json.dumps(state, indent=2) + '\n')


def update_state(values) -> dict:
    """Atomically perform a read/modify/write of desktop_state.json."""
    with _IO_LOCK:
        state = read_state()
        if callable(values):
            updated = values(dict(state))
            state = state if updated is None else updated
        else:
            state.update(values or {})
        write_state(state)
        return state


def generate_password(length: int = 14) -> str:
    """Readable random password (no ambiguous chars) for the bootstrap admin."""
    alphabet = string.ascii_letters + string.digits
    for bad in '0O1lI':
        alphabet = alphabet.replace(bad, '')
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def read_admin_creds() -> dict:
    """The first-admin login the desktop app created, so the panel can show it
    (the GUI exe has no console where the bootstrap banner would appear)."""
    if CREDS_FILE.exists():
        try:
            return json.loads(_read_text(CREDS_FILE, label='admin credentials'))
        except (ValueError, ConfigError):
            return {}
    return {}


def write_admin_creds(email: str, password: str) -> None:
    _write_protected(CREDS_FILE, json.dumps({'email': email, 'password': password}, indent=2))


def tos_accepted() -> bool:
    return bool(read_state().get('tos_accepted'))


def accept_tos() -> None:
    update_state({'tos_accepted': True})
