"""Direct, local Telegram audit notifications for one restaurant install.

This channel is intentionally independent from AlphaPOS cloud sync and from the
server edition's notification pipeline.  Paid-order messages and shift-close
reports are produced from the local database, persisted in a small local
outbox, and POSTed straight to Telegram's Bot API.

The bot token is read only from the protected per-install ``.env`` managed by
``desktop.config_store``.  It is never returned by this module, written to the
outbox, included in a report, or logged.
"""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from desktop import config_store


logger = logging.getLogger('desktop.local_telegram_audit')

MASK = '\u2022' * 8
AUDIT_DIR = config_store.DATA_DIR / 'local_telegram_audit'
OUTBOX_PATH = AUDIT_DIR / 'outbox.sqlite3'

REPORT_MAX_BYTES = 4 * 1024 * 1024
REPORT_MAX_ORDERS = 25_000
REPORT_MAX_REFUNDS = 10_000
REPORT_MAX_EXPENSES = 10_000
REPORT_MAX_SETTLEMENT_ROWS = 64
REPORT_QUERY_CHUNK = 500
REPORT_STALE_SECONDS = 24 * 60 * 60
REPORT_MAX_STALE_FILES = 32
POLL_SECONDS = 15.0
RECORDED_ORDER_SETTLE_SECONDS = 3.0
MAX_RETRY_SECONDS = 3600.0
SENT_RETENTION_SECONDS = 90 * 24 * 60 * 60
RECONCILE_SECONDS = 30.0
RECONCILE_SETTLE_SECONDS = 30.0
RECONCILE_OVERLAP_SECONDS = 5 * 60.0
RECONCILE_BATCH = 250
WORKER_RECOVERY_INITIAL_SECONDS = 1.0
WORKER_RECOVERY_MAX_SECONDS = 30.0

_TOKEN_RE = re.compile(r'(?<!\d)\d{5,15}:[A-Za-z0-9_-]{20,128}')
_CHAT_ID_RE = re.compile(r'(?:-?\d{1,32}|@[A-Za-z0-9_]{5,32})\Z')
_DB_LOCK = threading.RLock()
_START_LOCK = threading.RLock()
_STOP = threading.Event()
_WAKE = threading.Event()
_THREAD: threading.Thread | None = None
_STARTED = False


class LocalTelegramAuditError(RuntimeError):
    """Safe, operator-facing failure from the local notification channel."""


@dataclass(frozen=True)
class AuditConfig:
    enabled: bool
    order_recorded: bool
    order_paid: bool
    shift_reports: bool
    report_format: str
    token: str = field(repr=False)
    chat_ids: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_ids)

    @property
    def order_notifications(self) -> bool:
        return self.order_recorded or self.order_paid


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def parse_chat_ids(value: Any) -> list[str]:
    """Normalize and validate Telegram numeric IDs or ``@channel`` handles."""
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = re.split(r'[\s,;]+', str(value or ''))
    result: list[str] = []
    for part in parts:
        chat_id = str(part or '').strip()
        if not chat_id:
            continue
        if not _CHAT_ID_RE.fullmatch(chat_id):
            raise LocalTelegramAuditError(
                f'Invalid Telegram chat ID {chat_id!r}. Use a numeric ID '
                '(groups can start with -) or an @channel handle.',
            )
        if chat_id not in result:
            result.append(chat_id)
    return result


def _validate_token(token: str) -> str:
    token = str(token or '').strip()
    if not token:
        return ''
    if '\n' in token or '\r' in token or not _TOKEN_RE.fullmatch(token):
        raise LocalTelegramAuditError(
            'The Telegram bot token format is invalid. Paste the full token '
            'from BotFather.',
        )
    return token


def load_config() -> AuditConfig:
    raw = config_store.read_config()
    report_format = str(
        raw.get('LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT') or 'TXT',
    ).strip().upper()
    if report_format not in {'TXT', 'MD'}:
        report_format = 'TXT'
    token = str(raw.get('LOCAL_TELEGRAM_AUDIT_BOT_TOKEN') or '').strip()
    if token == MASK:
        token = ''
    try:
        chat_ids = tuple(parse_chat_ids(
            raw.get('LOCAL_TELEGRAM_AUDIT_CHAT_IDS'),
        ))
    except LocalTelegramAuditError:
        # A hand-edited malformed .env must not crash desktop startup.  Keep the
        # channel visibly unconfigured until the operator corrects it in the UI.
        chat_ids = ()
    return AuditConfig(
        enabled=_as_bool(raw.get('LOCAL_TELEGRAM_AUDIT_ENABLED')),
        order_recorded=_as_bool(
            raw.get('LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED'), True,
        ),
        order_paid=_as_bool(
            raw.get('LOCAL_TELEGRAM_ORDER_PAID_ENABLED'), True,
        ),
        shift_reports=_as_bool(
            raw.get('LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED'), True,
        ),
        report_format=report_format,
        token=token,
        chat_ids=chat_ids,
    )


_ENV_TO_FORM_FIELD = {
    'LOCAL_TELEGRAM_AUDIT_ENABLED': 'enabled',
    'LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED': 'order_recorded',
    'LOCAL_TELEGRAM_ORDER_PAID_ENABLED': 'order_paid',
    'LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED': 'shift_reports',
    'LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT': 'report_format',
    'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': 'bot_token',
    'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'chat_ids',
}


def configuration_values_from_environment(
    values: dict[str, Any] | None,
) -> dict[str, Any]:
    """Translate imported ``.env`` keys into the validated panel contract."""
    source = dict(values or {})
    return {
        form_field: source[env_key]
        for env_key, form_field in _ENV_TO_FORM_FIELD.items()
        if env_key in source
    }


def prepare_configuration_update(
    values: dict[str, Any] | None,
    *,
    current: dict[str, Any] | None = None,
    moment: datetime | None = None,
) -> dict[str, str]:
    """Validate an update and establish scan boundaries before it is visible.

    Both the dedicated screen and JSON support-bundle import use this function.
    Keeping the transition logic here prevents an imported false->true switch
    from replaying orders created while the owner explicitly had notifications
    disabled.
    """
    values = dict(values or {})
    current = dict(
        config_store.read_config() if current is None else current,
    )
    clean: dict[str, str] = {}

    if 'enabled' in values:
        clean['LOCAL_TELEGRAM_AUDIT_ENABLED'] = (
            'True' if _as_bool(values['enabled']) else 'False'
        )
    if 'order_recorded' in values:
        clean['LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED'] = (
            'True' if _as_bool(values['order_recorded']) else 'False'
        )
    if 'order_paid' in values:
        clean['LOCAL_TELEGRAM_ORDER_PAID_ENABLED'] = (
            'True' if _as_bool(values['order_paid']) else 'False'
        )
    if 'shift_reports' in values:
        clean['LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED'] = (
            'True' if _as_bool(values['shift_reports']) else 'False'
        )
    if 'report_format' in values:
        report_format = str(values.get('report_format') or '').strip().upper()
        if report_format not in {'TXT', 'MD'}:
            raise LocalTelegramAuditError('Shift report format must be TXT or MD.')
        clean['LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT'] = report_format
    if 'chat_ids' in values:
        clean['LOCAL_TELEGRAM_AUDIT_CHAT_IDS'] = ','.join(
            parse_chat_ids(values.get('chat_ids')),
        )
    if 'bot_token' in values:
        candidate = str(values.get('bot_token') or '').strip()
        # Blank and the UI mask both mean "keep the protected current secret".
        if candidate and candidate != MASK:
            clean['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'] = _validate_token(candidate)
        else:
            clean['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'] = str(
                current.get('LOCAL_TELEGRAM_AUDIT_BOT_TOKEN') or '',
            )

    was_enabled = _as_bool(current.get('LOCAL_TELEGRAM_AUDIT_ENABLED'))
    will_be_enabled = _as_bool(
        clean.get(
            'LOCAL_TELEGRAM_AUDIT_ENABLED',
            current.get('LOCAL_TELEGRAM_AUDIT_ENABLED'),
        ),
    )
    transition_moment = moment or datetime.now(dt_timezone.utc)
    if will_be_enabled and not was_enabled:
        # Establish the lower bound before the setting becomes observable. This
        # prevents first/re-enable from turning the OFF interval into an
        # unintended historical blast. Existing pending outbox rows are kept.
        _reset_enable_watermark(transition_moment)
    else:
        reenabled_kinds = []
        for env_key, kind in (
            ('LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED', 'recorded'),
            ('LOCAL_TELEGRAM_ORDER_PAID_ENABLED', 'paid'),
            ('LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED', 'shift'),
        ):
            if (
                _as_bool(clean.get(env_key, current.get(env_key)))
                and not _as_bool(current.get(env_key))
            ):
                reenabled_kinds.append(kind)
        if reenabled_kinds:
            _reset_kind_cursors(reenabled_kinds, transition_moment)
    return clean


def save_configuration(values: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and persist only this feature's per-install settings."""
    current = config_store.read_config()
    clean = prepare_configuration_update(values, current=current)
    config_store.write_config(clean)
    wake()
    return get_status()


def _safe_error(exc: Any, *, token: str = '') -> str:
    text = str(exc or 'Unknown Telegram delivery error')
    if token:
        text = text.replace(token, '[redacted-token]')
    text = _TOKEN_RE.sub('[redacted-token]', text)
    # Keep errors concise and single-line so neither logs nor UI become an
    # accidental transport dump.
    return ' '.join(text.replace('\r', ' ').replace('\n', ' ').split())[:500]


def _masked_chat(chat_id: str) -> str:
    chat_id = str(chat_id or '')
    if len(chat_id) <= 4:
        return '*' * len(chat_id)
    return f'***{chat_id[-4:]}'


def cleanup_stale_reports(*, now: float | None = None) -> int:
    """Remove only this module's abandoned plaintext report files.

    Successful deliveries delete immediately. This startup pass handles a hard
    process/OS crash, retaining a short troubleshooting window but bounding the
    number of plaintext artifacts on disk.
    """
    directory = AUDIT_DIR / 'reports'
    if not directory.exists():
        return 0
    now = time.time() if now is None else float(now)
    candidates: list[tuple[float, Path]] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        logger.warning('could not inspect stale local Telegram reports')
        return 0
    for path in entries:
        if (
            not path.is_file()
            or not path.name.startswith('alpha-pos-shift-')
            or path.suffix.lower() not in {'.txt', '.md'}
        ):
            continue
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    removed = 0
    survivors: list[tuple[float, Path]] = []
    for modified, path in candidates:
        if modified <= now - REPORT_STALE_SECONDS:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                logger.warning('could not remove stale local Telegram report %s', path.name)
        else:
            survivors.append((modified, path))
    # Keep the newest bounded set even if many recent crash artifacts exist.
    for _modified, path in sorted(survivors, reverse=True)[REPORT_MAX_STALE_FILES:]:
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            logger.warning('could not prune local Telegram report %s', path.name)
    return removed


def _connect() -> sqlite3.Connection:
    OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(OUTBOX_PATH), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=15000')
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS deliveries (
            event_key TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            object_pk INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            sent_at REAL,
            last_error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (event_key, chat_id)
        )
        """,
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_local_telegram_delivery_due
        ON deliveries(state, next_attempt_at, created_at)
        """,
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    )
    connection.commit()
    return connection


def _meta_get(key: str) -> str:
    with _DB_LOCK:
        connection = _connect()
        try:
            row = connection.execute(
                'SELECT value FROM metadata WHERE key=?',
                (key,),
            ).fetchone()
            return str(row['value']) if row else ''
        finally:
            connection.close()


def _meta_set_many(values: dict[str, Any], *, only_missing: bool = False) -> None:
    clause = 'INSERT OR IGNORE' if only_missing else 'INSERT OR REPLACE'
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                for key, value in values.items():
                    connection.execute(
                        f'{clause} INTO metadata(key, value) VALUES (?, ?)',
                        (str(key), str(value)),
                    )
        finally:
            connection.close()


def _watermark_values(moment: datetime) -> dict[str, str]:
    stamp = moment.astimezone(dt_timezone.utc).isoformat()
    return {
        'enabled_since': stamp,
        'recorded_cursor_time': stamp,
        'recorded_cursor_pk': '0',
        'paid_cursor_time': stamp,
        'paid_cursor_pk': '0',
        'shift_cursor_time': stamp,
        'shift_cursor_pk': '0',
    }


def _reset_enable_watermark(moment: datetime | None = None) -> datetime:
    """Start a fresh scan epoch without deleting already queued evidence."""
    moment = moment or datetime.now(dt_timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_timezone.utc)
    _meta_set_many(_watermark_values(moment))
    return moment.astimezone(dt_timezone.utc)


def _reset_kind_cursors(
    kinds: list[str] | tuple[str, ...] | set[str],
    moment: datetime | None = None,
) -> datetime:
    """Skip a notification kind's OFF interval without deleting its outbox."""
    allowed = {'recorded', 'paid', 'shift'}
    selected = {str(kind) for kind in kinds}
    if not selected or not selected.issubset(allowed):
        raise ValueError('local Telegram cursor kind is invalid')
    moment = moment or datetime.now(dt_timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_timezone.utc)
    stamp = moment.astimezone(dt_timezone.utc).isoformat()
    values: dict[str, str] = {}
    for kind in sorted(selected):
        values[f'{kind}_cursor_time'] = stamp
        values[f'{kind}_cursor_pk'] = '0'
    _meta_set_many(values)
    return moment.astimezone(dt_timezone.utc)


def _ensure_enable_watermark(moment: datetime | None = None) -> datetime:
    """Persist the first-enable lower bound and both scan cursors."""
    moment = moment or datetime.now(dt_timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_timezone.utc)
    stamp = moment.astimezone(dt_timezone.utc).isoformat()
    _meta_set_many(_watermark_values(moment), only_missing=True)
    raw = _meta_get('enabled_since') or stamp
    return _parse_utc_datetime(raw, fallback=moment)


def _parse_utc_datetime(value: Any, *, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        return parsed.astimezone(dt_timezone.utc)
    except (TypeError, ValueError):
        return fallback.astimezone(dt_timezone.utc)


def _reset_inflight() -> None:
    """Recover rows claimed just before a process crash."""
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE deliveries SET state='pending' WHERE state='sending'",
                )
        finally:
            connection.close()


def _insert_delivery(
    *,
    event_key: str,
    chat_id: str,
    kind: str,
    object_pk: int,
    payload: dict[str, Any],
    delay_seconds: float = 0,
) -> bool:
    now = time.time()
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO deliveries (
                        event_key, chat_id, kind, object_pk, payload_json,
                        state, attempts, next_attempt_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (
                        event_key, chat_id, kind, int(object_pk),
                        json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                        now + max(0.0, float(delay_seconds)), now,
                    ),
                )
                inserted = cursor.rowcount == 1
        finally:
            connection.close()
    if inserted:
        wake()
    return inserted


def _next_delivery(config: AuditConfig) -> dict[str, Any] | None:
    """Claim the oldest currently eligible row without discarding deferred rows.

    Turning a notification type off or removing a recipient pauses matching
    outbox evidence. It does not mark that evidence delivered/suppressed.
    """
    kinds = []
    if config.order_recorded:
        kinds.append('order_recorded')
    if config.order_paid:
        # ``order`` is accepted for compatibility with any pre-release outbox
        # row created while this feature was being introduced.
        kinds.extend(['order_paid', 'order'])
    if config.shift_reports:
        kinds.append('shift')
    if not kinds or not config.chat_ids:
        return None
    kind_marks = ','.join('?' for _ in kinds)
    chat_marks = ','.join('?' for _ in config.chat_ids)
    now = time.time()
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                row = connection.execute(
                    f"""
                    SELECT event_key, chat_id, kind, object_pk, payload_json,
                           attempts, created_at
                    FROM deliveries
                    WHERE state IN ('pending', 'failed') AND next_attempt_at <= ?
                      AND kind IN ({kind_marks})
                      AND chat_id IN ({chat_marks})
                    ORDER BY created_at, event_key, chat_id
                    LIMIT 1
                    """,
                    (now, *kinds, *config.chat_ids),
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    """
                    UPDATE deliveries SET state='sending'
                    WHERE event_key=? AND chat_id=?
                    """,
                    (row['event_key'], row['chat_id']),
                )
                result = dict(row)
        finally:
            connection.close()
    try:
        result['payload'] = json.loads(result.pop('payload_json'))
    except (TypeError, ValueError, json.JSONDecodeError):
        result['payload'] = {}
    return result


def _mark_sent(event_key: str, chat_id: str) -> None:
    now = time.time()
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET state='sent', sent_at=?, last_error=''
                    WHERE event_key=? AND chat_id=?
                    """,
                    (now, event_key, chat_id),
                )
                connection.execute(
                    """
                    DELETE FROM deliveries
                    WHERE state IN ('sent', 'suppressed')
                      AND COALESCE(sent_at, created_at) < ?
                    """,
                    (now - SENT_RETENTION_SECONDS,),
                )
        finally:
            connection.close()


def _mark_suppressed(event_key: str, chat_id: str) -> None:
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET state='suppressed', sent_at=?, last_error=''
                    WHERE event_key=? AND chat_id=?
                    """,
                    (time.time(), event_key, chat_id),
                )
        finally:
            connection.close()


def _mark_failed(row: dict[str, Any], exc: Any, *, token: str) -> str:
    attempts = int(row.get('attempts') or 0) + 1
    delay = min(MAX_RETRY_SECONDS, 5.0 * (2 ** min(attempts - 1, 10)))
    error = _safe_error(exc, token=token)
    with _DB_LOCK:
        connection = _connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET state='failed', attempts=?, next_attempt_at=?,
                        last_error=?
                    WHERE event_key=? AND chat_id=?
                    """,
                    (
                        attempts, time.time() + delay, error,
                        row['event_key'], row['chat_id'],
                    ),
                )
        finally:
            connection.close()
    return error


def _iso_from_epoch(value: Any) -> str | None:
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(float(value), tz=dt_timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _configuration_state(config: AuditConfig) -> str:
    if not config.enabled:
        return 'disabled'
    if not config.token:
        return 'missing_token'
    if not config.chat_ids:
        return 'missing_chat_ids'
    if not config.order_recorded and not config.order_paid and not config.shift_reports:
        return 'no_events_selected'
    return 'ready'


def get_status() -> dict[str, Any]:
    config = load_config()
    counts = {'pending': 0, 'failed': 0}
    last_sent = None
    last_error = ''
    try:
        with _DB_LOCK:
            connection = _connect()
            try:
                rows = connection.execute(
                    """
                    SELECT state, COUNT(*) AS count
                    FROM deliveries
                    WHERE state IN ('pending', 'failed', 'sending')
                    GROUP BY state
                    """,
                ).fetchall()
                for row in rows:
                    if row['state'] == 'failed':
                        counts['failed'] += int(row['count'])
                    else:
                        counts['pending'] += int(row['count'])
                last_sent = connection.execute(
                    "SELECT MAX(sent_at) AS value FROM deliveries WHERE state='sent'",
                ).fetchone()['value']
                error_row = connection.execute(
                    """
                    SELECT last_error FROM deliveries
                    WHERE state='failed' AND last_error != ''
                    ORDER BY created_at DESC LIMIT 1
                    """,
                ).fetchone()
                if error_row:
                    last_error = str(error_row['last_error'] or '')
            finally:
                connection.close()
    except (OSError, sqlite3.Error) as exc:
        last_error = _safe_error(exc, token=config.token)

    state = _configuration_state(config)
    return {
        'enabled': config.enabled,
        'order_recorded': config.order_recorded,
        'order_paid': config.order_paid,
        'order_notifications': config.order_notifications,
        'shift_reports': config.shift_reports,
        'report_format': config.report_format,
        'token_configured': bool(config.token),
        'chat_ids': list(config.chat_ids),
        'chat_count': len(config.chat_ids),
        'configured': config.configured,
        'configuration_state': state,
        'delivery_state': (
            'error' if counts['failed'] else
            ('pending' if counts['pending'] else state)
        ),
        'pending_count': counts['pending'],
        'retrying_count': counts['failed'],
        'last_sent_at': _iso_from_epoch(last_sent),
        'last_error': last_error,
        'worker_alive': bool(_THREAD and _THREAD.is_alive()),
        'direct_transport': True,
    }


def _format_datetime(value: Any) -> str:
    if value is None:
        return '\u2014'
    try:
        from django.utils import timezone
        if timezone.is_naive(value):
            value = timezone.make_aware(value)
        value = timezone.localtime(value)
    except Exception:  # noqa: BLE001 - safe fallback for pure unit tests
        pass
    try:
        offset = value.strftime('%z')
        offset = f'{offset[:3]}:{offset[3:]}' if len(offset) == 5 else offset
        zone = value.strftime('%Z')
        suffix = ' '.join(part for part in (zone, offset) if part)
        return value.strftime('%Y-%m-%d %H:%M:%S') + (f' {suffix}' if suffix else '')
    except Exception:  # noqa: BLE001
        return str(value)


def _money(value: Any) -> str:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal('0.01'))
        return f'{amount:,.2f}'
    except Exception:  # noqa: BLE001
        return str(value or '0.00')


def _person_name(person: Any) -> str:
    if person is None:
        return '\u2014'
    try:
        full = person.get_full_name()
    except (AttributeError, TypeError):
        full = ''
    full = str(full or '').strip()
    if full:
        return full
    first = str(getattr(person, 'first_name', '') or '').strip()
    last = str(getattr(person, 'last_name', '') or '').strip()
    return f'{first} {last}'.strip() or str(
        getattr(person, 'email', '') or getattr(person, 'pk', '\u2014'),
    )


def _order_reference(order: Any) -> str:
    number = getattr(order, 'order_number', None)
    if number is None:
        number = getattr(order, 'display_id', None)
    return f'#{number}' if number is not None else str(
        getattr(order, 'uuid', None) or getattr(order, 'pk', '\u2014'),
    )


def _shift_for_order(order: Any, *, event_at: Any = None) -> Any:
    event_at = event_at or getattr(order, 'paid_at', None) or getattr(
        order, 'created_at', None,
    )
    operator_id = getattr(order, 'cashier_id', None) or getattr(
        order, 'user_id', None,
    )
    if event_at is None or operator_id is None:
        return None
    from django.db.models import Q
    from base.models import Shift

    query = Shift.objects.filter(
        is_deleted=False,
        user_id=operator_id,
        start_time__lte=event_at,
    ).filter(Q(end_time__gt=event_at) | Q(end_time__isnull=True))
    branch_id = getattr(order, 'branch_id', None)
    if branch_id:
        query = query.filter(branch_id=branch_id)
    return query.select_related('user').order_by('-start_time', '-id').first()


def format_recorded_order_message(order: Any, shift: Any = None) -> str:
    """Build the finalized header-level order-created comparison alert."""
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    uuid_value = str(getattr(order, 'uuid', '') or '')
    branch = str(getattr(order, 'branch_id', '') or 'unconfigured')
    operator = getattr(order, 'cashier', None) or getattr(order, 'user', None)
    lines = [
        '\U0001f195 <b>Order recorded locally</b>',
        f'Order reference / name: <b>{esc(_order_reference(order))}</b>',
        f'Identifier: <code>{esc(uuid_value or getattr(order, "pk", "\u2014"))}</code>',
        f'Cost / subtotal: {esc(_money(getattr(order, "subtotal", 0)))} UZS',
        f'Discount: {esc(_money(getattr(order, "discount_amount", 0)))} UZS',
        f'Current total: <b>{esc(_money(getattr(order, "total_amount", 0)))} UZS</b>',
        f'Type / status: {esc(getattr(order, "order_type", "\u2014"))} / '
        f'{esc(getattr(order, "status", "\u2014"))}',
        f'Recorded exactly: {esc(_format_datetime(getattr(order, "created_at", None)))}',
        f'Operator: {esc(_person_name(operator))}',
    ]
    if shift is not None:
        shift_uuid = str(getattr(shift, 'uuid', '') or '')
        shift_ref = f'#{getattr(shift, "pk", "\u2014")}'
        if shift_uuid:
            shift_ref += f' / {shift_uuid}'
        lines.extend([
            f'Shift: <code>{esc(shift_ref)}</code>',
            f'Shift opened: {esc(_format_datetime(getattr(shift, "start_time", None)))}',
        ])
    else:
        lines.append('Shift: unavailable')
    lines.append(f'Branch: <code>{esc(branch)}</code>')
    return '\n'.join(lines)


def format_order_message(order: Any, shift: Any = None) -> str:
    """Build the concise paid-order alert. Product/item data is never read."""
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    uuid_value = str(getattr(order, 'uuid', '') or '')
    payment = str(getattr(order, 'payment_method', '') or 'UNSPECIFIED')
    branch = str(getattr(order, 'branch_id', '') or 'unconfigured')
    cashier = getattr(order, 'cashier', None)
    lines = [
        '\U0001f9fe <b>Order paid</b>',
        f'Order reference / name: <b>{esc(_order_reference(order))}</b>',
        f'Identifier: <code>{esc(uuid_value or getattr(order, "pk", "\u2014"))}</code>',
        f'Cost / subtotal: {esc(_money(getattr(order, "subtotal", 0)))} UZS',
        f'Discount: {esc(_money(getattr(order, "discount_amount", 0)))} UZS',
        f'Final total: <b>{esc(_money(getattr(order, "total_amount", 0)))} UZS</b>',
        f'Tender: {esc(payment)}',
        f'Paid exactly: {esc(_format_datetime(getattr(order, "paid_at", None)))}',
        f'Cashier: {esc(_person_name(cashier))}',
    ]
    if shift is not None:
        shift_uuid = str(getattr(shift, 'uuid', '') or '')
        shift_ref = f'#{getattr(shift, "pk", "\u2014")}'
        if shift_uuid:
            shift_ref += f' / {shift_uuid}'
        lines.extend([
            f'Shift: <code>{esc(shift_ref)}</code>',
            f'Shift opened: {esc(_format_datetime(getattr(shift, "start_time", None)))}',
        ])
    else:
        lines.append('Shift: unavailable')
    lines.append(f'Branch: <code>{esc(branch)}</code>')
    return '\n'.join(lines)


def _order_event_key(order: Any) -> str:
    stable = (
        getattr(order, 'payment_action_id', None)
        or getattr(order, 'paid_at', None)
        or getattr(order, 'uuid', None)
        or getattr(order, 'pk', None)
    )
    return f'order-paid:{getattr(order, "uuid", getattr(order, "pk", ""))}:{stable}'


def _recorded_order_event_key(order: Any) -> str:
    return f'order-recorded:{getattr(order, "uuid", getattr(order, "pk", ""))}'


def enqueue_recorded_order(order_pk: int) -> int:
    config = load_config()
    if not config.enabled or not config.order_recorded or not config.chat_ids:
        return 0
    from base.models import Order

    try:
        order = Order.objects.get(pk=order_pk, is_deleted=False)
    except Order.DoesNotExist:
        return 0
    enabled_since = _ensure_enable_watermark()
    created_at = order.created_at
    if created_at is None:
        return 0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=dt_timezone.utc)
    if created_at.astimezone(dt_timezone.utc) < enabled_since:
        return 0
    event_key = _recorded_order_event_key(order)
    inserted = 0
    for chat_id in config.chat_ids:
        inserted += int(_insert_delivery(
            event_key=event_key,
            chat_id=chat_id,
            kind='order_recorded',
            object_pk=order.pk,
            payload={},
            delay_seconds=RECORDED_ORDER_SETTLE_SECONDS,
        ))
    return inserted


def enqueue_order(order_pk: int) -> int:
    config = load_config()
    if not config.enabled or not config.order_paid or not config.chat_ids:
        return 0
    from base.models import Order

    try:
        order = Order.objects.select_related('cashier').get(
            pk=order_pk, is_deleted=False, is_paid=True,
        )
    except Order.DoesNotExist:
        return 0
    if order.paid_at is None:
        return 0
    paid_at = order.paid_at
    if paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=dt_timezone.utc)
    if paid_at.astimezone(dt_timezone.utc) < _ensure_enable_watermark():
        return 0
    shift = _shift_for_order(order)
    message = format_order_message(order, shift)
    event_key = _order_event_key(order)
    inserted = 0
    for chat_id in config.chat_ids:
        inserted += int(_insert_delivery(
            event_key=event_key,
            chat_id=chat_id,
            kind='order_paid',
            object_pk=order.pk,
            payload={'message': message},
        ))
    return inserted


def _shift_event_key(shift: Any) -> str:
    stable = getattr(shift, 'end_time', None) or getattr(shift, 'uuid', None)
    return f'shift-ended:{getattr(shift, "uuid", getattr(shift, "pk", ""))}:{stable}'


def enqueue_shift(shift_pk: int) -> int:
    config = load_config()
    if not config.enabled or not config.shift_reports or not config.chat_ids:
        return 0
    from base.models import Shift

    try:
        shift = Shift.objects.get(
            pk=shift_pk,
            is_deleted=False,
            status__in=[Shift.Status.ENDED, Shift.Status.COMPLETED],
        )
    except Shift.DoesNotExist:
        return 0
    if shift.end_time is None:
        return 0
    end_time = shift.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=dt_timezone.utc)
    if end_time.astimezone(dt_timezone.utc) < _ensure_enable_watermark():
        return 0
    event_key = _shift_event_key(shift)
    inserted = 0
    for chat_id in config.chat_ids:
        inserted += int(_insert_delivery(
            event_key=event_key,
            chat_id=chat_id,
            kind='shift',
            object_pk=shift.pk,
            payload={'report_format': config.report_format},
        ))
    return inserted


def _cursor(kind: str, enabled_since: datetime) -> tuple[datetime, int]:
    raw_time = _meta_get(f'{kind}_cursor_time')
    cursor_time = _parse_utc_datetime(raw_time, fallback=enabled_since)
    if cursor_time < enabled_since:
        cursor_time = enabled_since
    try:
        cursor_pk = max(0, int(_meta_get(f'{kind}_cursor_pk') or 0))
    except (TypeError, ValueError):
        cursor_pk = 0
    return cursor_time, cursor_pk


def _advance_cursor(kind: str, event_time: datetime, pk: int) -> None:
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=dt_timezone.utc)
    _meta_set_many({
        f'{kind}_cursor_time': event_time.astimezone(dt_timezone.utc).isoformat(),
        f'{kind}_cursor_pk': str(int(pk)),
    })


def _reconcile_recorded_orders(
    *,
    enabled_since: datetime,
    horizon: datetime,
) -> dict[str, int]:
    from django.db.models import Q
    from base.models import Order

    cursor_time, cursor_pk = _cursor('recorded', enabled_since)
    query = Order.objects.filter(
        is_deleted=False,
        created_at__gte=enabled_since,
        created_at__lte=horizon,
    ).filter(
        Q(created_at__gt=cursor_time)
        | Q(created_at=cursor_time, pk__gt=cursor_pk),
    ).order_by('created_at', 'pk')
    rows = list(query.values_list('pk', 'created_at')[:RECONCILE_BATCH])
    scanned = inserted = 0
    for pk, created_at in rows:
        inserted += enqueue_recorded_order(pk)
        scanned += 1
        _advance_cursor('recorded', created_at, pk)

    overlap_start = max(
        enabled_since,
        horizon - timedelta(seconds=RECONCILE_OVERLAP_SECONDS),
    )
    overlap = Order.objects.filter(
        is_deleted=False,
        created_at__gte=overlap_start,
        created_at__lte=horizon,
    ).order_by('-created_at', '-pk').values_list('pk', flat=True)[:RECONCILE_BATCH]
    for pk in overlap:
        inserted += enqueue_recorded_order(pk)
    return {'scanned': scanned, 'inserted': inserted}


def _reconcile_paid_orders(
    *,
    enabled_since: datetime,
    horizon: datetime,
) -> dict[str, int]:
    from django.db.models import Q
    from base.models import Order

    cursor_time, cursor_pk = _cursor('paid', enabled_since)
    query = Order.objects.filter(
        is_deleted=False,
        is_paid=True,
        paid_at__isnull=False,
        paid_at__gte=enabled_since,
        paid_at__lte=horizon,
    ).filter(
        Q(paid_at__gt=cursor_time)
        | Q(paid_at=cursor_time, pk__gt=cursor_pk),
    ).order_by('paid_at', 'pk')
    rows = list(query.values_list('pk', 'paid_at')[:RECONCILE_BATCH])
    scanned = inserted = 0
    for pk, paid_at in rows:
        inserted += enqueue_order(pk)
        scanned += 1
        _advance_cursor('paid', paid_at, pk)

    # A short overlapping pass catches a transaction that allocated its primary
    # key early but committed after the main keyset cursor moved past its event
    # timestamp. Stable event keys make this safely repeatable.
    overlap_start = max(
        enabled_since,
        horizon - timedelta(seconds=RECONCILE_OVERLAP_SECONDS),
    )
    overlap = Order.objects.filter(
        is_deleted=False,
        is_paid=True,
        paid_at__isnull=False,
        paid_at__gte=overlap_start,
        paid_at__lte=horizon,
    ).order_by('-paid_at', '-pk').values_list('pk', flat=True)[:RECONCILE_BATCH]
    for pk in overlap:
        inserted += enqueue_order(pk)
    return {'scanned': scanned, 'inserted': inserted}


def _reconcile_shifts(
    *,
    enabled_since: datetime,
    horizon: datetime,
) -> dict[str, int]:
    from django.db.models import Q
    from base.models import Shift

    cursor_time, cursor_pk = _cursor('shift', enabled_since)
    query = Shift.objects.filter(
        is_deleted=False,
        status__in=[Shift.Status.ENDED, Shift.Status.COMPLETED],
        end_time__isnull=False,
        end_time__gte=enabled_since,
        end_time__lte=horizon,
    ).filter(
        Q(end_time__gt=cursor_time)
        | Q(end_time=cursor_time, pk__gt=cursor_pk),
    ).order_by('end_time', 'pk')
    rows = list(query.values_list('pk', 'end_time')[:RECONCILE_BATCH])
    scanned = inserted = 0
    for pk, end_time in rows:
        inserted += enqueue_shift(pk)
        scanned += 1
        _advance_cursor('shift', end_time, pk)

    overlap_start = max(
        enabled_since,
        horizon - timedelta(seconds=RECONCILE_OVERLAP_SECONDS),
    )
    overlap = Shift.objects.filter(
        is_deleted=False,
        status__in=[Shift.Status.ENDED, Shift.Status.COMPLETED],
        end_time__isnull=False,
        end_time__gte=overlap_start,
        end_time__lte=horizon,
    ).order_by('-end_time', '-pk').values_list('pk', flat=True)[:RECONCILE_BATCH]
    for pk in overlap:
        inserted += enqueue_shift(pk)
    return {'scanned': scanned, 'inserted': inserted}


def reconcile_committed_events(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Repair the commit-to-callback crash gap with a bounded local scan."""
    config = load_config()
    if not config.enabled:
        return {'state': 'disabled', 'orders': {}, 'shifts': {}}
    if not config.chat_ids:
        # No destination exists yet. Crucially, do not advance either cursor;
        # once recipients are saved, every post-enable event remains eligible.
        return {'state': 'missing_chat_ids', 'orders': {}, 'shifts': {}}
    enabled_since = _ensure_enable_watermark()
    now = now or datetime.now(dt_timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt_timezone.utc)
    horizon = now.astimezone(dt_timezone.utc) - timedelta(
        seconds=RECONCILE_SETTLE_SECONDS,
    )
    if horizon <= enabled_since:
        return {'state': 'settling', 'orders': {}, 'shifts': {}}
    orders = {
        'recorded': (
            _reconcile_recorded_orders(
                enabled_since=enabled_since,
                horizon=horizon,
            )
            if config.order_recorded else {}
        ),
        'paid': (
            _reconcile_paid_orders(
                enabled_since=enabled_since,
                horizon=horizon,
            )
            if config.order_paid else {}
        ),
    }
    shifts = (
        _reconcile_shifts(enabled_since=enabled_since, horizon=horizon)
        if config.shift_reports else {}
    )
    return {'state': 'ok', 'orders': orders, 'shifts': shifts}


def _on_order_saved(sender, instance, using=None, **kwargs) -> None:
    if getattr(instance, 'is_deleted', False):
        return
    config = load_config()
    if not config.enabled or not config.order_notifications:
        return
    from django.db import transaction
    if config.order_recorded:
        transaction.on_commit(
            lambda pk=instance.pk: enqueue_recorded_order(pk),
            using=using,
            robust=True,
        )
    if (
        config.order_paid
        and getattr(instance, 'is_paid', False)
        and getattr(instance, 'paid_at', None) is not None
    ):
        transaction.on_commit(
            lambda pk=instance.pk: enqueue_order(pk),
            using=using,
            robust=True,
        )


def _on_shift_saved(sender, instance, using=None, **kwargs) -> None:
    status = str(getattr(instance, 'status', '') or '').upper()
    if (
        getattr(instance, 'is_deleted', False)
        or status != 'ENDED'
        or getattr(instance, 'end_time', None) is None
    ):
        return
    config = load_config()
    if not config.enabled or not config.shift_reports:
        return
    from django.db import transaction
    transaction.on_commit(
        lambda pk=instance.pk: enqueue_shift(pk),
        using=using,
        robust=True,
    )


def _register_signals() -> None:
    from django.db.models.signals import post_save
    from base.models import Order, Shift
    post_save.connect(
        _on_order_saved,
        sender=Order,
        weak=False,
        dispatch_uid='desktop.local_telegram_audit.order_paid',
    )
    post_save.connect(
        _on_shift_saved,
        sender=Shift,
        weak=False,
        dispatch_uid='desktop.local_telegram_audit.shift_ended',
    )


def _unregister_signals() -> None:
    try:
        from django.db.models.signals import post_save
        from base.models import Order, Shift
        post_save.disconnect(
            sender=Order,
            dispatch_uid='desktop.local_telegram_audit.order_paid',
        )
        post_save.disconnect(
            sender=Shift,
            dispatch_uid='desktop.local_telegram_audit.shift_ended',
        )
    except Exception:  # noqa: BLE001 - shutdown must remain best effort
        logger.debug('local Telegram audit signal disconnect failed', exc_info=True)


def _telegram_ack(response: Any, *, token: str) -> None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = None
    if (
        getattr(response, 'status_code', None) == 200
        and isinstance(body, dict)
        and body.get('ok') is True
    ):
        return
    detail = body.get('description') if isinstance(body, dict) else ''
    if not detail:
        detail = (
            'Telegram did not acknowledge the delivery '
            f'(HTTP {getattr(response, "status_code", "unknown")})'
        )
    raise LocalTelegramAuditError(_safe_error(detail, token=token))


def _post_message(token: str, chat_id: str, text: str) -> None:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - packaged dependency
        raise LocalTelegramAuditError(
            'Direct Telegram delivery requires the requests package.',
        ) from exc
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data={
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': 'true',
            },
            timeout=(10, 45),
        )
    except Exception as exc:  # noqa: BLE001
        raise LocalTelegramAuditError(_safe_error(exc, token=token)) from exc
    _telegram_ack(response, token=token)


def _post_document(
    token: str,
    chat_id: str,
    path: Path,
    *,
    caption: str,
    report_format: str,
) -> None:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - packaged dependency
        raise LocalTelegramAuditError(
            'Direct Telegram delivery requires the requests package.',
        ) from exc
    mime = 'text/markdown' if report_format == 'MD' else 'text/plain'
    try:
        with path.open('rb') as document:
            response = requests.post(
                f'https://api.telegram.org/bot{token}/sendDocument',
                data={'chat_id': chat_id, 'caption': caption},
                files={'document': (path.name, document, mime)},
                timeout=(10, 90),
            )
    except Exception as exc:  # noqa: BLE001
        raise LocalTelegramAuditError(_safe_error(exc, token=token)) from exc
    _telegram_ack(response, token=token)


def _add_money(target: dict[str, Decimal], source: dict[str, Any]) -> None:
    for key in target:
        target[key] += Decimal(str(source.get(key) or 0))


def _chunked_tender_breakdown(
    order_qs: Any,
) -> tuple[dict[str, Decimal], dict[str, Decimal], Decimal]:
    """Canonical tender arithmetic in bounded batches instead of one giant list."""
    from base.models import Order
    from base.services.tender import (
        BUCKETS,
        CARD_METHODS,
        breakdown_sources_for_orders,
        empty_detail,
        empty_split,
    )

    split = empty_split()
    detail = empty_detail()
    drawer_cash = Decimal('0')
    batch: list[int] = []
    iterator = order_qs.order_by('id').values_list('id', flat=True).iterator(
        chunk_size=REPORT_QUERY_CHUNK,
    )
    for order_id in iterator:
        batch.append(order_id)
        if len(batch) < REPORT_QUERY_CHUNK:
            continue
        part_split, part_detail, part_drawer = breakdown_sources_for_orders(
            Order.objects.filter(id__in=batch),
        )
        _add_money(split, {key: part_split[key] for key in BUCKETS})
        _add_money(detail, {key: part_detail[key] for key in CARD_METHODS})
        drawer_cash += part_drawer
        batch.clear()
    if batch:
        part_split, part_detail, part_drawer = breakdown_sources_for_orders(
            Order.objects.filter(id__in=batch),
        )
        _add_money(split, {key: part_split[key] for key in BUCKETS})
        _add_money(detail, {key: part_detail[key] for key in CARD_METHODS})
        drawer_cash += part_drawer
    return split, detail, drawer_cash


def _report_order_query(shift: Any) -> Any:
    from django.db.models import Q
    from base.models import Order
    end = shift.end_time
    return Order.objects.filter(
        is_deleted=False,
        cashier_id=shift.user_id,
        branch_id=shift.branch_id,
    ).filter(
        Q(created_at__gte=shift.start_time, created_at__lt=end)
        | Q(paid_at__gte=shift.start_time, paid_at__lt=end),
    ).distinct()


def _paid_shift_orders(shift: Any) -> Any:
    from base.models import Order
    return Order.objects.filter(
        is_deleted=False,
        cashier_id=shift.user_id,
        branch_id=shift.branch_id,
        is_paid=True,
        paid_at__gte=shift.start_time,
        paid_at__lt=shift.end_time,
    )


class _BoundedWriter:
    def __init__(self, handle: Any, limit: int):
        self.handle = handle
        self.limit = max(512, int(limit))
        self.bytes_written = 0
        self.truncated = False

    def line(self, text: Any = '') -> bool:
        blob = (str(text) + '\n').encode('utf-8')
        if self.bytes_written + len(blob) > self.limit:
            self.truncated = True
            return False
        self.handle.write(blob)
        self.bytes_written += len(blob)
        return True

    def truncation_marker(self) -> None:
        marker = '\n[Report truncated at the configured safe size limit.]\n'.encode(
            'utf-8',
        )
        if self.bytes_written + len(marker) <= self.limit:
            self.handle.write(marker)
            self.bytes_written += len(marker)


def _report_line_for_order(row: dict[str, Any], *, markdown: bool) -> str:
    number = row.get('order_number')
    if number is None:
        number = row.get('display_id')
    ref = f'#{number}' if number is not None else str(row.get('uuid') or row['id'])
    cashier = ' '.join(filter(None, (
        str(row.get('cashier__first_name') or '').strip(),
        str(row.get('cashier__last_name') or '').strip(),
    ))) or str(row.get('cashier__email') or '\u2014')
    content = (
        f'{ref} | UUID {row.get("uuid") or "\u2014"} | '
        f'created {_format_datetime(row.get("created_at"))} | '
        f'paid {_format_datetime(row.get("paid_at"))} | '
        f'{row.get("status") or "\u2014"} / {row.get("order_type") or "\u2014"} | '
        f'cost {_money(row.get("subtotal"))} UZS | '
        f'discount {_money(row.get("discount_amount"))} UZS | '
        f'final total {_money(row.get("total_amount"))} UZS | '
        f'tender {row.get("payment_method") or "UNSPECIFIED"} | cashier {cashier}'
    )
    if markdown:
        content = content.replace('|', '\\|')
        return f'- {content}'
    return content


def _single_report_line(value: Any) -> str:
    return ' '.join(str(value or '').replace('\r', ' ').replace('\n', ' ').split())


def _report_line_for_expense(row: dict[str, Any], *, markdown: bool) -> str:
    from cashbox.models import CashboxExpense

    reference = str(row.get('uuid') or row.get('id') or '\u2014')
    creator = ' '.join(filter(None, (
        str(row.get('created_by__first_name') or '').strip(),
        str(row.get('created_by__last_name') or '').strip(),
    ))) or str(row.get('created_by__email') or '\u2014')
    recipient = ' '.join(filter(None, (
        str(row.get('recipient_user__first_name') or '').strip(),
        str(row.get('recipient_user__last_name') or '').strip(),
    )))
    if not recipient:
        recipient = str(
            row.get('recipient_user__email')
            or row.get('recipient_supplier__name')
            or '\u2014'
        )
    comment = _single_report_line(
        CashboxExpense.visible_comment(row.get('comment')),
    ) or '\u2014'
    content = (
        f'{reference} | paid {_format_datetime(row.get("created_at"))} | '
        f'amount {_money(row.get("amount"))} UZS | '
        f'category {_single_report_line(row.get("category__name")) or "\u2014"} | '
        f'paid by {_single_report_line(creator)} | '
        f'recipient {_single_report_line(recipient)} | '
        f'comment {comment}'
    )
    if markdown:
        content = content.replace('|', '\\|')
        return f'- {content}'
    return content


def _report_line_for_refund(row: dict[str, Any], *, markdown: bool) -> str:
    number = row.get('order__order_number')
    if number is None:
        number = row.get('order__display_id')
    order_uuid = str(row.get('order__uuid') or '\u2014')
    order_ref = f'#{number}' if number is not None else order_uuid
    detail = row.get('card_detail')
    if not isinstance(detail, dict):
        detail = {}
    card_detail = ', '.join(
        f'{method} {_money(detail.get(method))} UZS'
        for method in ('UZCARD', 'HUMO', 'CARD')
        if Decimal(str(detail.get(method) or 0)) != 0
    ) or '\u2014'
    reason = _single_report_line(row.get('reason'))[:500] or '\u2014'
    source_id = _single_report_line(row.get('source_id'))[:160] or '\u2014'
    content = (
        f'{row.get("uuid") or row.get("id") or "\u2014"} | '
        f'order {order_ref} / {order_uuid} | '
        f'refunded {_format_datetime(row.get("refunded_at"))} | '
        f'source {_single_report_line(row.get("source")) or "\u2014"} / '
        f'{source_id} | '
        f'total {_money(row.get("amount"))} UZS | '
        f'cash {_money(row.get("cash_amount"))} UZS | '
        f'drawer cash {_money(row.get("drawer_cash_amount"))} UZS | '
        f'card {_money(row.get("card_amount"))} UZS | '
        f'Payme {_money(row.get("payme_amount"))} UZS | '
        f'unknown {_money(row.get("unknown_amount"))} UZS | '
        f'card detail {card_detail} | reason {reason}'
    )
    if markdown:
        content = content.replace('|', '\\|')
        return f'- {content}'
    return content


def build_shift_report(
    shift_pk: int,
    *,
    report_format: str = 'TXT',
    output_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Stream a bounded UTF-8 close report to disk and return its metadata."""
    from django.db.models import Sum
    from django.db.models.functions import Substr
    from base.models import OrderRefund, Shift
    from base.services.tender import (
        BUCKETS,
        CARD_METHODS,
        breakdown_for_refunds,
    )
    from cashbox.models import CashboxExpense, ShiftPaymentTotal

    report_format = str(report_format or 'TXT').upper()
    if report_format not in {'TXT', 'MD'}:
        report_format = 'TXT'
    markdown = report_format == 'MD'
    try:
        shift = Shift.objects.select_related('user').get(
            pk=shift_pk, is_deleted=False,
        )
    except Shift.DoesNotExist as exc:
        raise LocalTelegramAuditError('The closed shift no longer exists locally.') from exc
    if shift.end_time is None:
        raise LocalTelegramAuditError('The shift has no closing time yet.')

    paid_orders = _paid_shift_orders(shift)
    gross_split, gross_detail, gross_drawer_cash = _chunked_tender_breakdown(
        paid_orders,
    )
    refunds = OrderRefund.objects.filter(
        is_deleted=False,
        shift=shift,
        branch_id=shift.branch_id,
    )
    refund_count = refunds.count()
    refund_split, refund_detail = breakdown_for_refunds(refunds)
    from base.services.order_refund import refund_totals
    refund_money = refund_totals(refunds)
    net_split = {
        key: gross_split[key] - refund_split[key] for key in BUCKETS
    }
    net_detail = {
        key: gross_detail[key] - refund_detail[key] for key in CARD_METHODS
    }
    recomputed_revenue = sum(net_split.values(), Decimal('0'))
    recomputed_drawer_cash = (
        gross_drawer_cash - refund_money['drawer_cash_amount']
    )
    revenue_difference = Decimal(str(shift.total_revenue or 0)) - recomputed_revenue
    drawer_difference = (
        Decimal(str(shift.cash_collected or 0)) - recomputed_drawer_cash
    )
    orders = _report_order_query(shift)
    total_rows = orders.count()
    paid_count = paid_orders.count()
    expenses = CashboxExpense.objects.filter(
        shift=shift,
        branch_id=shift.branch_id,
        is_deleted=False,
    )
    expense_count = expenses.count()
    expense_total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    drawer_after_expenses = recomputed_drawer_cash - expense_total
    settlement_rows = ShiftPaymentTotal.objects.filter(
        shift=shift,
        branch_id=shift.branch_id,
        is_deleted=False,
    ).order_by('method', 'id')
    settlement_count = settlement_rows.count()

    directory = Path(output_dir) if output_dir is not None else AUDIT_DIR / 'reports'
    directory.mkdir(parents=True, exist_ok=True)
    suffix = '.md' if markdown else '.txt'
    stamp = shift.end_time.strftime('%Y%m%d-%H%M%S')
    temporary = tempfile.NamedTemporaryFile(
        mode='wb',
        prefix=f'alpha-pos-shift-{shift.pk}-{stamp}-',
        suffix=suffix,
        dir=str(directory),
        delete=False,
    )
    path = Path(temporary.name)
    writer = _BoundedWriter(temporary, REPORT_MAX_BYTES)
    rows_written = 0
    refunds_written = 0
    expenses_written = 0
    settlements_written = 0
    try:
        writer.line('# Alpha POS local shift audit' if markdown else 'ALPHA POS LOCAL SHIFT AUDIT')
        writer.line()
        writer.line(
            'Generated directly on this restaurant PC. No AlphaPOS cloud/server '
            'transport was used. Product lines are intentionally excluded.',
        )
        writer.line()
        if markdown:
            writer.line('## Shift')
        else:
            writer.line('SHIFT')
            writer.line('-----')
        writer.line(f'Shift ID: {shift.pk}')
        writer.line(f'Shift UUID: {getattr(shift, "uuid", "\u2014")}')
        writer.line(f'Branch: {shift.branch_id or "unconfigured"}')
        writer.line(f'Cashier: {_person_name(shift.user)}')
        writer.line(f'Status: {shift.status}')
        writer.line(f'Opened exactly: {_format_datetime(shift.start_time)}')
        writer.line(f'Closed exactly: {_format_datetime(shift.end_time)}')
        writer.line(f'Orders represented: {total_rows}')
        writer.line(f'Orders paid in money window: {paid_count}')
        writer.line()
        if markdown:
            writer.line('## Money and tender summary')
        else:
            writer.line('MONEY AND TENDER SUMMARY')
            writer.line('------------------------')
        for key in BUCKETS:
            writer.line(
                f'{key.upper()}: gross {_money(gross_split[key])} UZS | '
                f'refund {_money(refund_split[key])} UZS | '
                f'net {_money(net_split[key])} UZS',
            )
        writer.line(
            'CARD DETAIL: '
            + ' | '.join(
                f'{key} net {_money(net_detail[key])} UZS'
                for key in CARD_METHODS
            ),
        )
        writer.line(
            f'GROSS TOTAL: {_money(sum(gross_split.values(), Decimal("0")))} UZS',
        )
        writer.line(
            f'REFUNDS TOTAL: {_money(sum(refund_split.values(), Decimal("0")))} UZS',
        )
        writer.line(
            f'RECOMPUTED NET REVENUE: {_money(recomputed_revenue)} UZS',
        )
        writer.line(f'Frozen shift revenue: {_money(shift.total_revenue)} UZS')
        writer.line(
            f'FROZEN MINUS RECOMPUTED REVENUE: {_money(revenue_difference)} UZS',
        )
        writer.line(
            f'RECOMPUTED DRAWER CASH: {_money(recomputed_drawer_cash)} UZS',
        )
        writer.line(f'Frozen drawer cash: {_money(shift.cash_collected)} UZS')
        writer.line(
            f'FROZEN MINUS RECOMPUTED DRAWER CASH: {_money(drawer_difference)} UZS',
        )
        writer.line(f'CASHBOX EXPENSES TOTAL: {_money(expense_total)} UZS')
        writer.line(
            f'RECOMPUTED DRAWER AFTER EXPENSES: {_money(drawer_after_expenses)} UZS',
        )
        writer.line()
        if markdown:
            writer.line('## Frozen tender reconciliation')
        else:
            writer.line('FROZEN TENDER RECONCILIATION')
            writer.line('----------------------------')
        writer.line(f'Settlement rows: {settlement_count}')
        settlement_values = settlement_rows.values(
            'method', 'expected_amount', 'counted_amount', 'difference',
            'confirmed_amount', 'created_at', 'updated_at',
        )[:REPORT_MAX_SETTLEMENT_ROWS]
        for row in settlement_values:
            line = (
                f'{row["method"]} | expected {_money(row["expected_amount"])} UZS | '
                f'counted {_money(row["counted_amount"])} UZS | '
                f'difference {_money(row["difference"])} UZS | '
                f'confirmed {_money(row["confirmed_amount"])} UZS | '
                f'frozen {_format_datetime(row["created_at"])} | '
                f'updated {_format_datetime(row["updated_at"])}'
            )
            if markdown:
                line = '- ' + line.replace('|', '\\|')
            if not writer.line(line):
                break
            settlements_written += 1
        if settlement_count > REPORT_MAX_SETTLEMENT_ROWS:
            writer.truncated = True
        if settlement_count == 0:
            writer.line('No frozen tender reconciliation rows were found.')
        writer.line()
        if markdown:
            writer.line('## Refund events')
        else:
            writer.line('REFUND EVENTS')
            writer.line('-------------')
        writer.line(
            f'Refunds recorded: {refund_count} | '
            f'total {_money(refund_money["amount"])} UZS',
        )
        refund_values = refunds.order_by('refunded_at', 'id').annotate(
            report_reason=Substr('reason', 1, 500),
        ).values(
            'id', 'uuid', 'order__uuid', 'order__order_number',
            'order__display_id', 'refunded_at', 'source', 'source_id',
            'amount', 'cash_amount', 'drawer_cash_amount', 'card_amount',
            'payme_amount', 'unknown_amount', 'card_detail', 'report_reason',
        )[:REPORT_MAX_REFUNDS]
        for row in refund_values.iterator(chunk_size=REPORT_QUERY_CHUNK):
            row['reason'] = row.pop('report_reason', '')
            if not writer.line(_report_line_for_refund(row, markdown=markdown)):
                break
            refunds_written += 1
        if refund_count > REPORT_MAX_REFUNDS:
            writer.truncated = True
        if refund_count == 0:
            writer.line('No refund events were recorded.')
        writer.line()
        if markdown:
            writer.line('## Cashbox expenses')
        else:
            writer.line('CASHBOX EXPENSES')
            writer.line('----------------')
        writer.line(
            f'Expenses recorded: {expense_count} | '
            f'total {_money(expense_total)} UZS',
        )
        expense_values = expenses.order_by('created_at', 'id').annotate(
            report_comment=Substr('comment', 1, 1000),
        ).values(
            'id', 'uuid', 'amount', 'report_comment', 'created_at', 'category__name',
            'created_by__first_name', 'created_by__last_name',
            'created_by__email', 'recipient_user__first_name',
            'recipient_user__last_name', 'recipient_user__email',
            'recipient_supplier__name',
        )[:REPORT_MAX_EXPENSES]
        for row in expense_values.iterator(chunk_size=REPORT_QUERY_CHUNK):
            row['comment'] = row.pop('report_comment', '')
            if not writer.line(_report_line_for_expense(row, markdown=markdown)):
                break
            expenses_written += 1
        if expense_count > REPORT_MAX_EXPENSES:
            writer.truncated = True
        if expense_count == 0:
            writer.line('No cashbox expenses were recorded.')
        writer.line()
        if markdown:
            writer.line('## Shift orders')
        else:
            writer.line('SHIFT ORDERS')
            writer.line('------------')

        values = orders.order_by('created_at', 'id').values(
            'id', 'uuid', 'order_number', 'display_id', 'created_at', 'paid_at',
            'status', 'order_type', 'subtotal', 'discount_amount',
            'discount_percent', 'total_amount', 'payment_method',
            'cashier__first_name', 'cashier__last_name', 'cashier__email',
        ).iterator(chunk_size=REPORT_QUERY_CHUNK)
        for row in values:
            if rows_written >= REPORT_MAX_ORDERS:
                writer.truncated = True
                break
            if not writer.line(_report_line_for_order(row, markdown=markdown)):
                break
            rows_written += 1
        if writer.truncated:
            writer.truncation_marker()
    except BaseException:
        temporary.close()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                'could not remove incomplete local Telegram report %s',
                path.name,
            )
        raise
    finally:
        if not temporary.closed:
            temporary.close()

    return path, {
        'shift_id': shift.pk,
        'shift_uuid': str(getattr(shift, 'uuid', '') or ''),
        'orders_total': total_rows,
        'orders_written': rows_written,
        'paid_orders': paid_count,
        'refunds_total': refund_count,
        'refunds_written': refunds_written,
        'refund_amount': str(
            Decimal(str(refund_money['amount'])).quantize(Decimal('0.01')),
        ),
        'expenses_total': expense_count,
        'expenses_written': expenses_written,
        'expense_amount': str(
            Decimal(str(expense_total)).quantize(Decimal('0.01')),
        ),
        'settlements_total': settlement_count,
        'settlements_written': settlements_written,
        'bytes': path.stat().st_size,
        'truncated': writer.truncated,
        'report_format': report_format,
    }


def _deliver_row(row: dict[str, Any], config: AuditConfig) -> None:
    kind = row['kind']
    if row['chat_id'] not in config.chat_ids:
        raise LocalTelegramAuditError('The queued recipient is currently paused.')
    if kind == 'order_recorded':
        if not config.order_recorded:
            raise LocalTelegramAuditError('Recorded-order notifications are paused.')
        from base.models import Order
        try:
            order = Order.objects.select_related('cashier', 'user').get(
                pk=row['object_pk'],
            )
        except Order.DoesNotExist as exc:
            raise LocalTelegramAuditError(
                'The queued local order no longer exists.',
            ) from exc
        # The staff bot's order.new event is emitted after its item batch. Match
        # that lifecycle point without exporting product rows or names.
        if not order.items.filter(is_deleted=False).exists():
            raise LocalTelegramAuditError(
                'The recorded order is still waiting for finalized totals.',
            )
        shift = _shift_for_order(order, event_at=order.created_at)
        _post_message(
            config.token,
            row['chat_id'],
            format_recorded_order_message(order, shift),
        )
    elif kind in {'order_paid', 'order'}:
        if not config.order_paid:
            raise LocalTelegramAuditError('Paid-order notifications are paused.')
        message = str((row.get('payload') or {}).get('message') or '').strip()
        if not message:
            raise LocalTelegramAuditError('The queued order message is empty.')
        _post_message(config.token, row['chat_id'], message)
    elif kind == 'shift':
        if not config.shift_reports:
            raise LocalTelegramAuditError('Shift reports are paused.')
        report_format = str(
            (row.get('payload') or {}).get('report_format')
            or config.report_format
        ).upper()
        path, metadata = build_shift_report(
            row['object_pk'],
            report_format=report_format,
        )
        try:
            suffix = ' (truncated safely)' if metadata['truncated'] else ''
            caption = (
                f'Alpha POS local shift #{metadata["shift_id"]} audit\n'
                f'Orders: {metadata["orders_total"]}{suffix}'
            )
            _post_document(
                config.token,
                row['chat_id'],
                path,
                caption=caption,
                report_format=metadata['report_format'],
            )
        finally:
            path.unlink(missing_ok=True)
    else:
        raise LocalTelegramAuditError(f'Unknown local audit event kind: {kind}')
    _mark_sent(row['event_key'], row['chat_id'])


def deliver_pending_once() -> dict[str, Any]:
    """Deliver at most one due outbox row; useful for worker and unit tests."""
    config = load_config()
    state = _configuration_state(config)
    if state != 'ready':
        return {'sent': 0, 'failed': 0, 'state': state}
    row = _next_delivery(config)
    if row is None:
        return {'sent': 0, 'failed': 0, 'state': 'empty'}
    try:
        _deliver_row(row, config)
        return {'sent': 1, 'failed': 0, 'state': 'sent'}
    except Exception as exc:  # noqa: BLE001
        error = _mark_failed(row, exc, token=config.token)
        logger.warning(
            'local Telegram audit delivery failed for chat %s: %s',
            _masked_chat(row['chat_id']),
            error,
        )
        return {'sent': 0, 'failed': 1, 'state': 'failed', 'error': error}


def send_test_message() -> dict[str, Any]:
    """Send a real direct transport test without writing a fake audit event."""
    config = load_config()
    state = _configuration_state(config)
    if state != 'ready':
        raise LocalTelegramAuditError(
            {
                'disabled': 'Enable local Telegram audit first.',
                'missing_token': 'Add the local Telegram bot token first.',
                'missing_chat_ids': 'Add at least one Telegram chat ID first.',
                'no_events_selected': 'Enable order alerts or shift reports first.',
            }.get(state, 'Local Telegram audit is not ready.'),
        )
    sent: list[str] = []
    failed: list[dict[str, str]] = []
    text = (
        '\u2705 <b>Alpha POS local audit test</b>\n'
        'This message was sent directly from the restaurant PC to Telegram.\n'
        'No AlphaPOS cloud/server transport was used.'
    )
    for chat_id in config.chat_ids:
        try:
            _post_message(config.token, chat_id, text)
            sent.append(chat_id)
        except Exception as exc:  # noqa: BLE001
            failed.append({
                'chat_id': chat_id,
                'error': _safe_error(exc, token=config.token),
            })
    return {
        'ok': bool(sent) and not failed,
        'partial': bool(sent) and bool(failed),
        'sent': sent,
        'failed': failed,
    }


def _worker() -> None:
    next_reconcile = 0.0
    recovery_delay = WORKER_RECOVERY_INITIAL_SECONDS
    try:
        while not _STOP.is_set():
            try:
                config = load_config()
                now_monotonic = time.monotonic()
                if config.enabled:
                    _ensure_enable_watermark()
                    if now_monotonic >= next_reconcile:
                        try:
                            reconcile_committed_events()
                        except Exception:  # noqa: BLE001 - retry sweep next interval
                            logger.exception(
                                'local Telegram audit reconciliation sweep failed',
                            )
                        next_reconcile = now_monotonic + RECONCILE_SECONDS
                if _configuration_state(config) == 'ready':
                    result = deliver_pending_once()
                    if result.get('state') not in {'empty', 'disabled'}:
                        recovery_delay = WORKER_RECOVERY_INITIAL_SECONDS
                        continue
                wait_for = POLL_SECONDS
                if config.enabled:
                    wait_for = min(
                        wait_for,
                        max(0.2, next_reconcile - time.monotonic()),
                    )
                recovery_delay = WORKER_RECOVERY_INITIAL_SECONDS
            except Exception:  # noqa: BLE001 - the durable worker must self-heal
                logger.exception(
                    'local Telegram audit worker cycle failed; retrying',
                )
                wait_for = recovery_delay
                recovery_delay = min(
                    WORKER_RECOVERY_MAX_SECONDS,
                    max(
                        WORKER_RECOVERY_INITIAL_SECONDS,
                        recovery_delay * 2,
                    ),
                )
            _WAKE.wait(max(0.0, wait_for))
            _WAKE.clear()
    finally:
        try:
            from django.db import connections
            connections.close_all()
        except Exception:  # noqa: BLE001
            logger.debug('local Telegram audit worker DB close failed', exc_info=True)


def start_background_notifier() -> bool:
    global _STARTED, _THREAD
    with _START_LOCK:
        if _STARTED and _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _WAKE.clear()
        _register_signals()
        cleanup_stale_reports()
        _reset_inflight()
        thread = threading.Thread(
            target=_worker,
            name='local-telegram-audit',
            daemon=True,
        )
        _THREAD = thread
        _STARTED = True
        try:
            thread.start()
        except Exception:
            _THREAD = None
            _STARTED = False
            _unregister_signals()
            raise
        logger.info(
            'local Telegram audit worker started (state=%s, recipients=%d)',
            _configuration_state(load_config()),
            len(load_config().chat_ids),
        )
        return True


def stop_background_notifier(*, timeout: float = 35.0) -> bool:
    global _STARTED, _THREAD
    with _START_LOCK:
        thread = _THREAD
        if not _STARTED and thread is None:
            _unregister_signals()
            return True
        _STOP.set()
        _WAKE.set()
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=max(0.0, float(timeout)))
    if thread is not None and thread.is_alive():
        logger.error(
            'local Telegram audit worker did not stop within %.1f seconds',
            timeout,
        )
        return False
    with _START_LOCK:
        if _THREAD is thread:
            _THREAD = None
            _STARTED = False
    _unregister_signals()
    return True


def wake() -> None:
    _WAKE.set()
