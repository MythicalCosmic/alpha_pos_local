"""Append-only local order evidence and direct Telegram export.

This is deliberately a *desktop* evidence channel, independent of Alpha POS
cloud sync. It records complete local order snapshots plus the exact outbound
sync-queue lifecycle before the cloud can acknowledge/delete it. Small cursor-
tracked JSONL segments are delivered directly to Telegram from this process.
The raw dataset never contains Telegram credentials or authentication secrets.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from desktop import config_store


logger = logging.getLogger('desktop.order_audit')

SCHEMA_VERSION = 1
AUDIT_DIR = config_store.DATA_DIR / 'order_audit'
RAW_DATASET = AUDIT_DIR / 'orders.raw.jsonl'
INDEX_FILE = AUDIT_DIR / '.orders.raw.index.json'
_MASK = '\u2022' * 8
_TOKEN_RE = re.compile(r'(?<!\d)\d{5,}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])')
_AUTH_HEADER_RE = re.compile(
    r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}',
)
_CREDENTIAL_TEXT_RE = re.compile(
    r'(?i)\b(password|passwd|secret|token|authorization|api[_-]?key|'
    r'private[_-]?key)\s*[:=]\s*([^\s,;}\]]+)',
)
_URL_SECRET_RE = re.compile(
    r'(?i)([?&](?:token|key|secret|auth|authorization|signature|session|'
    r'credential|api[_-]?key)=)[^&#\s]+',
)
_SWEEP_SECONDS = 300
# Signals capture normal writes immediately. A small rolling rescan repairs a
# missed/bulk header update without repeatedly materializing several busy days
# of orders on a low-powered till.
_RECENT_HOURS = 2
_MAX_PLAIN_TELEGRAM_BYTES = 45 * 1024 * 1024
_AUTO_SEND_SECONDS = 30
_AUTO_SEGMENT_BYTES = 8 * 1024 * 1024
_SENSITIVE_KEY_RE = re.compile(
    r'(?:password|passwd|secret|token|authorization|api[_-]?key|private[_-]?key)',
    re.IGNORECASE,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _safe_attr(obj: Any, name: str, default=None):
    try:
        return getattr(obj, name)
    except (AttributeError, TypeError, ValueError):
        return default


def _scrub_text(value: str) -> str:
    value = _TOKEN_RE.sub('[redacted-token]', str(value))
    value = _AUTH_HEADER_RE.sub(lambda match: f'{match.group(1)} [REDACTED]', value)
    value = _CREDENTIAL_TEXT_RE.sub(
        lambda match: f'{match.group(1)}=[REDACTED]', value,
    )
    return _URL_SECRET_RE.sub(lambda match: f'{match.group(1)}[REDACTED]', value)


def _safe_payment_link(value: Any) -> Any:
    """Retain correlation evidence for gateway links without exporting grants."""
    raw = str(value or '')
    if not raw:
        return raw
    parsed = urlsplit(raw)
    path = parsed.path or ''
    return {
        'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        'scheme': parsed.scheme,
        'host': parsed.hostname or '',
        'path_sha256': hashlib.sha256(path.encode('utf-8')).hexdigest(),
        'path_segment_count': len([part for part in path.split('/') if part]),
    }


def _relation_rows(order: Any, name: str) -> list[Any]:
    manager = _safe_attr(order, name)
    if manager is None:
        return []
    try:
        rows = manager.all() if hasattr(manager, 'all') else manager
        return list(rows)
    except Exception:  # noqa: BLE001 - an optional relation must not stop evidence
        logger.debug('order audit: could not read %s relation', name, exc_info=True)
        return []


def _identity(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {'id': None, 'uuid': None, 'name': None}
    name = _safe_attr(obj, 'name')
    if not name:
        first = _safe_attr(obj, 'first_name', '') or ''
        last = _safe_attr(obj, 'last_name', '') or ''
        name = f'{first} {last}'.strip() or _safe_attr(obj, 'email')
    return {
        'id': _safe_attr(obj, 'pk', _safe_attr(obj, 'id')),
        'uuid': _text(_safe_attr(obj, 'uuid')),
        'name': _text(name),
    }


def _concrete_fields(obj: Any) -> dict[str, Any]:
    """Serialize every stored column on a Django model without recursion.

    Foreign keys are emitted by their ``*_id`` column.  This gives incident
    responders a database-faithful row while avoiding an unbounded graph walk.
    Nested JSON business data is kept, but credential-shaped keys are redacted.
    """
    if obj is None or not hasattr(obj, '_meta'):
        return {}
    values: dict[str, Any] = {}
    model_label = str(getattr(obj._meta, 'label_lower', '')).lower()  # noqa: SLF001
    for field in getattr(obj._meta, 'concrete_fields', ()):  # noqa: SLF001
        name = str(getattr(field, 'attname', None) or field.name)
        try:
            value = getattr(obj, name)
        except Exception:  # noqa: BLE001 - evidence must survive odd descriptors
            value = None
        if model_label == 'couriers.courierpayment' and field.name == 'link':
            values[name] = _safe_payment_link(value)
        else:
            values[name] = _redact_sync_value(value, key=name)
    return values


def _linked_rows(obj: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """Add one-hop forward relation rows for human-readable forensic context."""
    if obj is None or not hasattr(obj, '_meta'):
        return {}
    excluded = exclude or set()
    linked: dict[str, Any] = {}
    for field in getattr(obj._meta, 'concrete_fields', ()):  # noqa: SLF001
        if not getattr(field, 'is_relation', False) or field.name in excluded:
            continue
        relation = _safe_attr(obj, field.name)
        if relation is not None:
            linked[field.name] = _concrete_fields(relation)
    return linked


def _reverse_related_rows(obj: Any, *, nested_depth=0) -> dict[str, Any]:
    if not hasattr(obj, '_meta'):
        return {}
    output: dict[str, Any] = {}
    for relation in getattr(obj._meta, 'related_objects', ()):  # noqa: SLF001
        accessor = relation.get_accessor_name()
        value = _safe_attr(obj, accessor)
        if value is None:
            rows: list[Any] = []
        elif hasattr(value, 'all'):
            try:
                rows = list(value.all())
            except Exception:  # noqa: BLE001
                logger.debug(
                    'order audit: could not read relation %s', accessor,
                    exc_info=True,
                )
                rows = []
        else:
            rows = [value]
        rows.sort(key=lambda row: (_safe_attr(row, 'pk', 0) or 0))
        label = str(getattr(relation.related_model._meta, 'label', accessor))
        output[accessor] = {
            'model': label,
            'rows': [
                {
                    'raw': _concrete_fields(row),
                    'linked': _linked_rows(row, exclude={'order', 'cart'}),
                    **(
                        {'nested_rows': _reverse_related_rows(
                            row, nested_depth=nested_depth - 1,
                        )}
                        if nested_depth > 0 else {}
                    ),
                }
                for row in rows
            ],
        }
    return output


def _all_related_rows(order: Any) -> dict[str, Any]:
    """Capture every visible Order relation plus one nested level (Cart items)."""
    return _reverse_related_rows(order, nested_depth=1)


def _supplemental_order_rows(order: Any) -> dict[str, Any]:
    """Capture order sidecars whose schema intentionally has no reverse FK."""
    meta = _safe_attr(order, '_meta')
    if str(_safe_attr(meta, 'label_lower', '')).lower() != 'base.order':
        return {}
    order_id = _safe_attr(order, 'pk', _safe_attr(order, 'id'))
    order_uuid = _safe_attr(order, 'uuid')
    specs: list[tuple[str, Any, dict[str, Any]]] = []
    try:
        from couriers.models import CourierNotification
        specs.append(('courier_notifications', CourierNotification, {'order_id': order_id}))
    except Exception:  # noqa: BLE001
        pass
    try:
        from notifications.models import (
            LoyaltyRedemption, OrderLoyaltyCredit, OrderNotificationDispatch,
        )
        specs.extend([
            ('loyalty_credits', OrderLoyaltyCredit, {'order_id': order_id}),
            ('loyalty_redemptions', LoyaltyRedemption, {'order_id': order_id}),
            ('notification_dispatches', OrderNotificationDispatch, {'order_id': order_id}),
        ])
    except Exception:  # noqa: BLE001
        pass
    try:
        from base.models import AuditLog, SyncQueueRecord
        specs.append((
            'audit_logs', AuditLog,
            {'target_type__iexact': 'Order', 'target_id': order_id},
        ))
        if order_uuid:
            specs.append((
                'pending_sync_queue_rows', SyncQueueRecord,
                {'record_uuid': order_uuid},
            ))
    except Exception:  # noqa: BLE001
        pass

    output: dict[str, Any] = {}
    for key, model, filters in specs:
        try:
            rows = list(model._default_manager.filter(**filters).order_by('pk'))
        except Exception:  # noqa: BLE001
            logger.debug('order audit: sidecar %s unavailable', key, exc_info=True)
            rows = []
        output[key] = {
            'model': str(model._meta.label),
            'rows': [
                {'raw': _concrete_fields(row), 'linked': _linked_rows(row)}
                for row in rows
            ],
        }
    return output


def _line_total(item: Any) -> str:
    try:
        quantity = Decimal(str(_safe_attr(item, 'quantity', 0) or 0))
        price = Decimal(str(_safe_attr(item, 'price', 0) or 0))
        discount = Decimal(str(_safe_attr(item, 'discount_amount', 0) or 0))
        return str((quantity * price) - discount)
    except Exception:  # noqa: BLE001
        return '0'


def serialize_order(order: Any) -> dict[str, Any]:
    """Return a stable, JSON-ready money/sync snapshot for one local order."""
    items = []
    for item in sorted(_relation_rows(order, 'items'), key=lambda row: row.pk or 0):
        product = _safe_attr(item, 'product')
        items.append({
            'raw': _concrete_fields(item),
            'id': _safe_attr(item, 'pk', _safe_attr(item, 'id')),
            'uuid': _text(_safe_attr(item, 'uuid')),
            'product': {**_identity(product), 'raw': _concrete_fields(product)},
            'quantity': _safe_attr(item, 'quantity'),
            'original_price': _text(_safe_attr(item, 'original_price')),
            'unit_price': _text(_safe_attr(item, 'price')),
            'discount_amount': _text(_safe_attr(item, 'discount_amount')),
            'calculated_line_total': _line_total(item),
            'detail': _text(_safe_attr(item, 'detail')),
            'ready_at': _iso(_safe_attr(item, 'ready_at')),
            'is_deleted': bool(_safe_attr(item, 'is_deleted', False)),
            'sync_version': _safe_attr(item, 'sync_version'),
            'synced_at': _iso(_safe_attr(item, 'synced_at')),
        })

    payments = []
    by_tender: dict[str, Decimal] = defaultdict(Decimal)
    for payment in sorted(_relation_rows(order, 'payments'), key=lambda row: row.pk or 0):
        method = str(_safe_attr(payment, 'method', '') or 'UNKNOWN').upper()
        try:
            amount = Decimal(str(_safe_attr(payment, 'amount', 0) or 0))
        except Exception:  # noqa: BLE001
            amount = Decimal('0')
        if not bool(_safe_attr(payment, 'is_deleted', False)):
            by_tender[method] += amount
        payments.append({
            'raw': _concrete_fields(payment),
            'id': _safe_attr(payment, 'pk', _safe_attr(payment, 'id')),
            'uuid': _text(_safe_attr(payment, 'uuid')),
            'method': method,
            'amount': str(amount),
            'payment_action_id': _text(_safe_attr(payment, 'payment_action_id')),
            'line_index': _safe_attr(payment, 'line_index'),
            'created_at': _iso(_safe_attr(payment, 'created_at')),
            'is_deleted': bool(_safe_attr(payment, 'is_deleted', False)),
            'sync_version': _safe_attr(payment, 'sync_version'),
            'synced_at': _iso(_safe_attr(payment, 'synced_at')),
        })

    external_payments = []
    external_by_tender: dict[str, Decimal] = defaultdict(Decimal)
    for payment in sorted(
        _relation_rows(order, 'external_payments'), key=lambda row: row.pk or 0,
    ):
        method = str(_safe_attr(payment, 'method', '') or 'UNKNOWN').upper()
        try:
            amount = Decimal(str(_safe_attr(payment, 'amount', 0) or 0))
        except Exception:  # noqa: BLE001
            amount = Decimal('0')
        if not bool(_safe_attr(payment, 'is_deleted', False)):
            external_by_tender[method] += amount
        external_payments.append({
            'raw': _concrete_fields(payment),
            'id': _safe_attr(payment, 'pk', _safe_attr(payment, 'id')),
            'uuid': _text(_safe_attr(payment, 'uuid')),
            'source': _text(_safe_attr(payment, 'source')),
            'source_id': _text(_safe_attr(payment, 'source_id')),
            'method': method,
            'amount': str(amount),
            'occurred_at': _iso(_safe_attr(payment, 'occurred_at')),
            'is_deleted': bool(_safe_attr(payment, 'is_deleted', False)),
            'sync_version': _safe_attr(payment, 'sync_version'),
            'synced_at': _iso(_safe_attr(payment, 'synced_at')),
        })

    refunds = []
    for refund in sorted(_relation_rows(order, 'refunds'), key=lambda row: row.pk or 0):
        refunds.append({
            'raw': _concrete_fields(refund),
            'id': _safe_attr(refund, 'pk', _safe_attr(refund, 'id')),
            'uuid': _text(_safe_attr(refund, 'uuid')),
            'amount': _text(_safe_attr(refund, 'amount')),
            'cash_amount': _text(_safe_attr(refund, 'cash_amount')),
            'drawer_cash_amount': _text(_safe_attr(refund, 'drawer_cash_amount')),
            'card_amount': _text(_safe_attr(refund, 'card_amount')),
            'payme_amount': _text(_safe_attr(refund, 'payme_amount')),
            'unknown_amount': _text(_safe_attr(refund, 'unknown_amount')),
            'card_detail': _safe_attr(refund, 'card_detail', {}) or {},
            'refunded_at': _iso(_safe_attr(refund, 'refunded_at')),
            'source': _text(_safe_attr(refund, 'source')),
            'source_id': _text(_safe_attr(refund, 'source_id')),
            'is_deleted': bool(_safe_attr(refund, 'is_deleted', False)),
            'sync_version': _safe_attr(refund, 'sync_version'),
            'synced_at': _iso(_safe_attr(refund, 'synced_at')),
        })

    total = Decimal(str(_safe_attr(order, 'total_amount', 0) or 0))
    internal_tender_total = sum(by_tender.values(), Decimal('0'))
    external_tender_total = sum(external_by_tender.values(), Decimal('0'))
    tender_total = internal_tender_total + external_tender_total
    combined_by_tender: dict[str, Decimal] = defaultdict(Decimal)
    for method, amount in by_tender.items():
        combined_by_tender[method] += amount
    for method, amount in external_by_tender.items():
        combined_by_tender[method] += amount
    # Different backend generations used source, origin, or order_origin. Keep
    # the evidence forward/backward compatible without assuming a migration.
    origin = (_safe_attr(order, 'order_origin') or _safe_attr(order, 'origin')
              or _safe_attr(order, 'source') or 'POS')
    return {
        'raw': _concrete_fields(order),
        'id': _safe_attr(order, 'pk', _safe_attr(order, 'id')),
        'uuid': _text(_safe_attr(order, 'uuid')),
        'display_id': _safe_attr(order, 'display_id'),
        'order_number': _safe_attr(order, 'order_number'),
        'branch_id': _text(_safe_attr(order, 'branch_id', '')) or '',
        'origin': _text(origin),
        'order_origin': _text(_safe_attr(order, 'order_origin')),
        'order_type': _text(_safe_attr(order, 'order_type')),
        'chef_queue_number': _safe_attr(order, 'chef_queue_number'),
        'phone_number': _text(_safe_attr(order, 'phone_number')),
        'delivery_address': _text(_safe_attr(order, 'delivery_address')),
        'description': _text(_safe_attr(order, 'description')),
        'status': _text(_safe_attr(order, 'status')),
        'is_paid': bool(_safe_attr(order, 'is_paid', False)),
        'is_deleted': bool(_safe_attr(order, 'is_deleted', False)),
        'created_at': _iso(_safe_attr(order, 'created_at')),
        'updated_at': _iso(_safe_attr(order, 'updated_at')),
        'paid_at': _iso(_safe_attr(order, 'paid_at')),
        'ready_at': _iso(_safe_attr(order, 'ready_at')),
        'payment_requested_at': _iso(_safe_attr(order, 'payment_requested_at')),
        'subtotal': _text(_safe_attr(order, 'subtotal')),
        'discount_amount': _text(_safe_attr(order, 'discount_amount')),
        'discount_percent': _text(_safe_attr(order, 'discount_percent')),
        'total_amount': str(total),
        'payment_method': _text(_safe_attr(order, 'payment_method')),
        'payment_action_id': _text(_safe_attr(order, 'payment_action_id')),
        'accounting_recorded_at': _iso(_safe_attr(order, 'accounting_recorded_at')),
        'cashier': _identity(_safe_attr(order, 'cashier')),
        'created_by': _identity(_safe_attr(order, 'user')),
        'customer': _identity(_safe_attr(order, 'customer')),
        'delivery_person': _identity(_safe_attr(order, 'delivery_person')),
        'place': _identity(_safe_attr(order, 'place')),
        'table': _identity(_safe_attr(order, 'table')),
        'linked_entities': _linked_rows(order),
        'sync': {
            'version': _safe_attr(order, 'sync_version'),
            'synced_at': _iso(_safe_attr(order, 'synced_at')),
            'pending': _safe_attr(order, 'synced_at') is None,
        },
        'items': items,
        'payments': payments,
        'external_payments': external_payments,
        'refunds': refunds,
        # Database-faithful rows for every installed app relation: fiscal
        # receipts, courier assignment/payments, receipt print job, discounts,
        # stock transactions, source carts, and any future relation are covered.
        'related_rows': _all_related_rows(order),
        'supplemental_rows': _supplemental_order_rows(order),
        'tender_evidence': {
            'by_method': {key: str(by_tender[key]) for key in sorted(by_tender)},
            'external_by_method': {
                key: str(external_by_tender[key]) for key in sorted(external_by_tender)
            },
            'combined_by_method': {
                key: str(combined_by_tender[key]) for key in sorted(combined_by_tender)
            },
            'payment_rows_total': str(internal_tender_total),
            'external_payment_rows_total': str(external_tender_total),
            'combined_payment_rows_total': str(tender_total),
            'order_total': str(total),
            'payment_delta': str(tender_total - total),
            'positive_order_without_payment_rows': bool(
                _safe_attr(order, 'is_paid', False) and total > 0
                and not [p for p in payments if not p['is_deleted']]
                and not [p for p in external_payments if not p['is_deleted']]
            ),
        },
    }


def _snapshot_fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _desktop_version() -> str:
    try:
        from desktop.version import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return 'unknown'


def _runtime_build() -> dict[str, str]:
    """Semantic identity that survives PyInstaller (unlike git rev-parse)."""
    return {
        'desktop_version': _desktop_version(),
        'core_contract': '2026.07.22-sync-evidence-v1',
    }


def _device_id() -> str:
    """Stable non-secret till identity for cross-file reconciliation."""
    return str(
        os.environ.get('DEVICE_ID') or config_store.load_or_generate_device_id()
    )


def _enabled_from_state() -> bool:
    settings = config_store.read_state().get('order_audit') or {}
    return settings.get('enabled', True) is not False


def _auto_send_enabled_from_state() -> bool:
    settings = config_store.read_state().get('order_audit') or {}
    return settings.get('auto_send', True) is not False


def _redact_sync_value(value: Any, *, key: str = '') -> Any:
    """Preserve business evidence while refusing to export credentials.

    User/password hashes and provider tokens can be present in generic sync
    payloads. Their key name and presence are evidence; their value is not
    needed to reconcile money and must never leave the till.
    """
    if key and _SENSITIVE_KEY_RE.search(key):
        return '[REDACTED]'
    if isinstance(value, dict):
        return {
            str(child_key): _redact_sync_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_sync_value(item) for item in value]
    if isinstance(value, (datetime, Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, str):
        return _scrub_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {'encoding': 'hex', 'value': value.hex()}
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            pass
    return str(value)


class OrderAuditCollector:
    def __init__(self, *, dataset: Path = RAW_DATASET, index_file: Path = INDEX_FILE):
        self.dataset = Path(dataset)
        self.index_file = Path(index_file)
        # Raw evidence contains customer/order PII and is deliberately reachable
        # through the owner support workflow. It must not inherit a broad
        # Windows profile ACL. Repair every existing object with the correct
        # directory/file rights before _load_index performs its first read,
        # then let new atomic indexes/exports inherit the owner-only DACL.
        self.dataset.parent.mkdir(parents=True, exist_ok=True)
        config_store._harden_windows_private_path(
            self.dataset.parent, directory=True, recursive=True,
        )
        self._lock = threading.RLock()
        self._fingerprints: dict[str, str] = {}
        self._record_count = 0
        self._last_capture_at: str | None = None
        self._last_export_at: str | None = None
        self._last_auto_send_at: str | None = None
        self._delivery_errors: dict[str, str] = {}
        self._delivery_offsets: dict[str, int] = {}
        self._last_record_sha256 = ''
        self._last_error = ''
        self._index_dirty = 0
        self._index_written_at = 0.0
        self._load_index()

    def _load_index(self) -> None:
        # The index is only a deduplication cache, never the evidence source. If
        # the raw file was intentionally removed, ignore a stale cache and let
        # the startup sweep rebuild a complete dataset.
        if not self.dataset.exists() or self.dataset.stat().st_size == 0:
            return
        data: dict[str, Any] = {}
        try:
            if self.index_file.exists():
                data = json.loads(self.index_file.read_text(encoding='utf-8'))
            self._fingerprints = dict(data.get('fingerprints') or {})
            self._record_count = int(data.get('record_count') or 0)
            self._last_capture_at = data.get('last_capture_at')
            self._last_export_at = data.get('last_export_at')
            self._last_auto_send_at = data.get('last_auto_send_at')
            self._delivery_errors = {
                str(key): str(value)
                for key, value in (data.get('delivery_errors') or {}).items()
                if value
            }
            legacy_error = str(data.get('last_auto_send_error') or '')
            if legacy_error and not self._delivery_errors:
                self._delivery_errors['legacy'] = legacy_error
            self._delivery_offsets = {
                str(key): max(0, int(value or 0))
                for key, value in (data.get('delivery_offsets') or {}).items()
            }
            self._last_record_sha256 = str(data.get('last_record_sha256') or '')
        except Exception:  # noqa: BLE001
            logger.warning('order audit index unreadable; rebuilding safely', exc_info=True)
            data = {}
        # Raw JSONL is the authority. A power loss may happen after its fsync but
        # before the deliberately throttled cache flush. Rebuild whenever the
        # byte boundary disagrees so the next append continues the real chain.
        if int(data.get('dataset_bytes') or -1) != self.dataset.stat().st_size:
            self._rebuild_cache_from_raw()
            self._index_dirty += 1
            self._flush_index(force=True)

    def _rebuild_cache_from_raw(self) -> None:
        fingerprints: dict[str, str] = {}
        record_count = 0
        last_capture_at = None
        last_export_at = None
        last_sha = ''
        with self.dataset.open('rb') as source:
            for raw_line in source:
                if not raw_line.endswith(b'\n'):
                    # Crash-truncated tail is isolated by the next append.
                    continue
                try:
                    record = json.loads(raw_line)
                except (UnicodeDecodeError, ValueError, TypeError):
                    continue
                record_count += 1
                last_capture_at = record.get('captured_at') or last_capture_at
                if record.get('record_type') == 'export_manifest':
                    last_export_at = record.get('captured_at') or last_export_at
                if record.get('record_type') == 'order_snapshot':
                    order = record.get('order') or {}
                    key = order.get('uuid') or f"pk:{order.get('id')}"
                    fingerprint = (record.get('capture') or {}).get('snapshot_sha256')
                    if key and fingerprint:
                        fingerprints[str(key)] = str(fingerprint)
                candidate = (record.get('integrity') or {}).get('record_sha256')
                if candidate:
                    last_sha = str(candidate)
        self._fingerprints = fingerprints
        self._record_count = record_count
        self._last_capture_at = last_capture_at
        self._last_export_at = last_export_at
        self._last_record_sha256 = last_sha

    def _flush_index(self, *, force=False) -> None:
        if not self._index_dirty and not force:
            return
        if not force and self._index_dirty < 10 and time.monotonic() - self._index_written_at < 10:
            return
        payload = {
            'schema_version': SCHEMA_VERSION,
            'record_count': self._record_count,
            'last_capture_at': self._last_capture_at,
            'last_export_at': self._last_export_at,
            'last_auto_send_at': self._last_auto_send_at,
            'last_auto_send_error': self._combined_delivery_error(),
            'delivery_errors': self._delivery_errors,
            'delivery_offsets': self._delivery_offsets,
            'last_record_sha256': self._last_record_sha256,
            'dataset_bytes': self.dataset.stat().st_size if self.dataset.exists() else 0,
            'fingerprints': self._fingerprints,
        }
        config_store._write_protected(
            self.index_file,
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n',
        )
        self._index_dirty = 0
        self._index_written_at = time.monotonic()

    def _append(self, record: dict[str, Any]) -> None:
        record['integrity'] = {
            'previous_record_sha256': self._last_record_sha256 or None,
        }
        canonical = json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            default=str,
        ).encode('utf-8')
        record_sha256 = hashlib.sha256(canonical).hexdigest()
        record['integrity']['record_sha256'] = record_sha256
        encoded = (json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            default=str,
        ) + '\n').encode('utf-8')
        self.dataset.parent.mkdir(parents=True, exist_ok=True)
        # RLock serializes all process threads; O_APPEND plus flush/fsync means a
        # power interruption can lose at most the final partial line, never
        # overwrite an older order snapshot.
        with self.dataset.open('ab', buffering=0) as fh:
            if fh.tell() > 0:
                with self.dataset.open('rb') as check:
                    check.seek(-1, os.SEEK_END)
                    if check.read(1) != b'\n':
                        # Isolate a crash-truncated final record so the next
                        # complete JSON object remains independently readable.
                        fh.write(b'\n')
            remaining = memoryview(encoded)
            while remaining:
                written = fh.write(remaining)
                if not written:
                    raise OSError('short write while appending order audit')
                remaining = remaining[written:]
            os.fsync(fh.fileno())
        self._last_record_sha256 = record_sha256
        _AUTO_WAKE.set()

    def record_event(
        self, record_type: str, payload: dict[str, Any], *, reason: str,
    ) -> bool:
        """Durably append a non-order event such as a queue/HTTP transition."""
        if not _enabled_from_state():
            return False
        try:
            captured_at = _iso(_utc_now())
            record = {
                'schema_version': SCHEMA_VERSION,
                'record_type': str(record_type),
                'event_id': str(uuid.uuid4()),
                'captured_at': captured_at,
                'capture': {
                    'reason': str(reason),
                    **_runtime_build(),
                    'device_id': _device_id(),
                },
                'event': payload,
            }
            with self._lock:
                self._append(record)
                self._record_count += 1
                self._last_capture_at = captured_at
                self._last_error = ''
                self._index_dirty += 1
                self._flush_index()
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = _safe_error(exc)
            logger.exception('order audit lifecycle event capture failed')
            return False

    def delivery_offset(self, chat_id: str) -> int:
        with self._lock:
            return max(0, int(self._delivery_offsets.get(str(chat_id), 0)))

    def mark_delivered(self, chat_id: str, end_offset: int) -> None:
        """Advance only after Telegram confirms receipt (at-least-once)."""
        with self._lock:
            key = str(chat_id)
            current = max(0, int(self._delivery_offsets.get(key, 0)))
            self._delivery_offsets[key] = max(current, int(end_offset))
            self._last_auto_send_at = _iso(_utc_now())
            self._delivery_errors.pop(key, None)
            self._index_dirty += 1
            self._flush_index(force=True)

    def set_auto_send_error(self, error: Any, *, chat_id='configuration') -> None:
        with self._lock:
            key = str(chat_id)
            message = _safe_error(error)
            # A persistent provider/config outage must not rewrite and fsync the
            # index every 30 seconds when its state has not changed.
            if self._delivery_errors.get(key) == message:
                return
            self._delivery_errors[key] = message
            self._index_dirty += 1
            self._flush_index(force=True)

    def clear_auto_send_error(self, chat_id='configuration') -> None:
        with self._lock:
            if self._delivery_errors.pop(str(chat_id), None) is None:
                return
            self._index_dirty += 1
            self._flush_index(force=True)

    def _combined_delivery_error(self) -> str:
        return '; '.join(
            f'{key}: {self._delivery_errors[key]}'
            for key in sorted(self._delivery_errors)
        )[:1000]

    def capture(self, order: Any, *, reason='model_change', force=False) -> bool:
        if not force and not _enabled_from_state():
            return False
        try:
            payload = serialize_order(order)
            key = payload.get('uuid') or f"pk:{payload.get('id')}"
            fingerprint = _snapshot_fingerprint(payload)
            with self._lock:
                if not force and self._fingerprints.get(key) == fingerprint:
                    return False
                captured_at = _iso(_utc_now())
                record = {
                    'schema_version': SCHEMA_VERSION,
                    'record_type': 'order_snapshot',
                    'event_id': str(uuid.uuid4()),
                    'captured_at': captured_at,
                    'capture': {
                        'reason': str(reason),
                        **_runtime_build(),
                        'device_id': _device_id(),
                        'snapshot_sha256': fingerprint,
                    },
                    'order': payload,
                }
                self._append(record)
                self._fingerprints[key] = fingerprint
                self._record_count += 1
                self._last_capture_at = captured_at
                self._index_dirty += 1
                self._last_error = ''
                self._flush_index()
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            logger.exception('order audit capture failed')
            return False

    def flush(self) -> None:
        with self._lock:
            self._flush_index(force=True)

    def status(self, *, chat_ids: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            size = self.dataset.stat().st_size if self.dataset.exists() else 0
            if chat_ids:
                # A newly provisioned recipient starts at byte zero even if an
                # older recipient already acknowledged the complete file.
                slowest_offset = min(
                    max(0, int(self._delivery_offsets.get(str(chat_id), 0)))
                    for chat_id in chat_ids
                )
            else:
                slowest_offset = 0
            return {
                'enabled': _enabled_from_state(),
                'auto_send': _auto_send_enabled_from_state(),
                'dataset': str(self.dataset),
                'exists': self.dataset.exists(),
                'bytes': size,
                'order_count': len(self._fingerprints),
                'record_count': self._record_count,
                'last_capture_at': self._last_capture_at,
                'last_export_at': self._last_export_at,
                'last_auto_send_at': self._last_auto_send_at,
                'last_auto_send_error': self._combined_delivery_error(),
                'delivery_errors': dict(self._delivery_errors),
                'delivery_offsets': dict(self._delivery_offsets),
                'auto_pending_bytes': max(0, size - slowest_offset),
                'last_error': self._last_error,
            }

    def prepare_export(self) -> tuple[Path, dict[str, Any]]:
        """Freeze a byte-for-byte snapshot so Telegram never races an append."""
        export_id = str(uuid.uuid4())
        prepared_at = _iso(_utc_now())
        with self._lock:
            record = {
                'schema_version': SCHEMA_VERSION,
                'record_type': 'export_manifest',
                'event_id': str(uuid.uuid4()),
                'captured_at': prepared_at,
                'export': {
                    'export_id': export_id,
                    'prepared_at': prepared_at,
                    'desktop_version': _desktop_version(),
                    'core_contract': _runtime_build()['core_contract'],
                    'device_id': _device_id(),
                    'orders_indexed': len(self._fingerprints),
                    'records_before_manifest': self._record_count,
                },
            }
            self._append(record)
            self._record_count += 1
            self._last_export_at = prepared_at
            self._index_dirty += 1
            self._flush_index(force=True)
            export_dir = self.dataset.parent / 'exports'
            export_dir.mkdir(parents=True, exist_ok=True)
            stamp = _utc_now().strftime('%Y%m%dT%H%M%SZ')
            target = export_dir / f'alpha-pos-orders-{stamp}-{export_id[:8]}.jsonl'
            with self.dataset.open('rb') as source, target.open('wb') as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        if target.stat().st_size > _MAX_PLAIN_TELEGRAM_BYTES:
            compressed = target.with_suffix(target.suffix + '.gz')
            with target.open('rb') as source, gzip.open(compressed, 'wb', compresslevel=6) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.unlink()
            target = compressed
        return target, {
            'export_id': export_id,
            'prepared_at': prepared_at,
            'orders': len(self._fingerprints),
            'records': self._record_count,
            'bytes': target.stat().st_size,
        }

    def prepare_incremental_export(
        self, chat_id: str, *, max_bytes: int = _AUTO_SEGMENT_BYTES,
    ) -> tuple[Path | None, dict[str, Any]]:
        """Freeze the next newline-aligned raw segment for one recipient.

        The source offset is not advanced here. A caller must invoke
        :meth:`mark_delivered` only after Telegram returns HTTP 200; a crash may
        duplicate a segment but can never silently skip it.
        """
        chat_id = str(chat_id)
        with self._lock:
            size = self.dataset.stat().st_size if self.dataset.exists() else 0
            start = self.delivery_offset(chat_id)
            if start > size:
                # Dataset was intentionally reset. The old cursor cannot point
                # into a new file.
                start = 0
            if start >= size:
                return None, {'start_offset': start, 'end_offset': start, 'bytes': 0}

            with self.dataset.open('rb') as source:
                source.seek(start)
                raw = source.read(max(1, int(max_bytes)))
                if source.tell() < size and not raw.endswith(b'\n'):
                    raw += source.readline()
                end = source.tell()

            # A crash-truncated last record is left pending until a later append
            # isolates it with a newline; never publish half a JSON object.
            last_newline = raw.rfind(b'\n')
            if last_newline < 0:
                return None, {'start_offset': start, 'end_offset': start, 'bytes': 0}
            raw = raw[:last_newline + 1]
            end = start + len(raw)

            export_dir = self.dataset.parent / 'auto'
            export_dir.mkdir(parents=True, exist_ok=True)
            stamp = _utc_now().strftime('%Y%m%dT%H%M%SZ')
            chat_tag = hashlib.sha256(chat_id.encode('utf-8')).hexdigest()[:8]
            target = export_dir / (
                f'alpha-pos-evidence-{stamp}-{chat_tag}-{start}-{end}.jsonl.gz'
            )
            with gzip.open(target, 'wb', compresslevel=6) as output:
                output.write(raw)

        return target, {
            'start_offset': start,
            'end_offset': end,
            'bytes': len(raw),
            'compressed_bytes': target.stat().st_size,
            'sha256': hashlib.sha256(raw).hexdigest(),
        }


_COLLECTOR = OrderAuditCollector()
_CAPTURE_QUEUE: queue.Queue[tuple[int, str]] = queue.Queue()
_PENDING_CAPTURE_LOCK = threading.Lock()
_PENDING_CAPTURES: dict[int, str] = {}
_SYNC_EVENT_QUEUE: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
_START_LOCK = threading.Lock()
_STARTED = False
_STOP = threading.Event()
_AUTO_WAKE = threading.Event()
_THREAD: threading.Thread | None = None
_SENDER_THREAD: threading.Thread | None = None


def get_status() -> dict[str, Any]:
    token, chat_ids = _telegram_delivery_configuration()
    result = _COLLECTOR.status(chat_ids=chat_ids)
    result.update({
        'worker_alive': bool(_THREAD is not None and _THREAD.is_alive()),
        'sender_alive': bool(
            _SENDER_THREAD is not None and _SENDER_THREAD.is_alive()
        ),
        'telegram_configured': bool(token and chat_ids),
        'telegram_token_configured': bool(token),
        'telegram_chat_count': len(chat_ids),
        # Raw JSONL is authoritative; automatic transport compresses newline-
        # aligned segments without changing a byte of the evidence stream.
        'formats': ['JSONL', 'JSONL.GZ'],
    })
    if not result['enabled']:
        result['delivery_state'] = 'off'
    elif not result['auto_send']:
        result['delivery_state'] = 'paused'
    elif not result['telegram_configured']:
        result['delivery_state'] = 'configuration_required'
    elif not result['sender_alive'] or result['last_auto_send_error']:
        result['delivery_state'] = 'error'
    elif result['auto_pending_bytes']:
        result['delivery_state'] = 'pending'
    else:
        result['delivery_state'] = 'delivered'
    return result


def record_local_event(
    event_type: str, payload: dict[str, Any], *, synchronous: bool = True,
) -> bool:
    """Record arbitrary local evidence with redaction and an original hash.

    Checkout request-received events use synchronous fsync so even a view crash
    cannot erase proof that the till accepted the request. Less critical callers
    may enqueue the same safe envelope for the background writer.
    """
    if not _enabled_from_state():
        return False
    original = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        default=str,
    ).encode('utf-8')
    envelope = {
        'payload_sha256': hashlib.sha256(original).hexdigest(),
        'payload': _redact_sync_value(payload),
    }
    if synchronous:
        return _COLLECTOR.record_event(
            'local_http_lifecycle', envelope, reason=str(event_type),
        )
    _SYNC_EVENT_QUEUE.put((str(event_type), envelope))
    return True


def set_enabled(enabled: bool) -> dict[str, Any]:
    def merge(state):
        state['order_audit'] = {
            **(state.get('order_audit') or {}),
            'enabled': bool(enabled),
        }
        return state
    config_store.update_state(merge)
    if enabled:
        request_full_sweep('enabled_backfill')
        _AUTO_WAKE.set()
    return get_status()


def set_auto_send(enabled: bool) -> dict[str, Any]:
    def merge(state):
        state['order_audit'] = {
            **(state.get('order_audit') or {}),
            'auto_send': bool(enabled),
        }
        return state
    config_store.update_state(merge)
    if enabled:
        _AUTO_WAKE.set()
    return get_status()


def _order_queryset(*, recent_hours: int | None = None):
    from base.models import Order
    from django.db.models import Prefetch

    forward = [
        field.name
        for field in Order._meta.concrete_fields
        if getattr(field, 'is_relation', False)
    ]
    prefetches = []
    for relation in Order._meta.related_objects:
        related_model = relation.related_model
        related_forward = [
            field.name
            for field in related_model._meta.concrete_fields
            if getattr(field, 'is_relation', False) and field.name != 'order'
        ]
        related_qs = related_model._default_manager.all()
        if related_forward:
            related_qs = related_qs.select_related(*related_forward)
        prefetches.append(Prefetch(relation.get_accessor_name(), queryset=related_qs))
    qs = (
        Order.objects.select_related(*forward)
        .prefetch_related(*prefetches)
        .order_by('pk')
    )
    if recent_hours is not None:
        try:
            from django.utils import timezone as django_timezone
            qs = qs.filter(updated_at__gte=django_timezone.now() - timedelta(hours=recent_hours))
        except Exception:  # noqa: BLE001
            pass
    return qs


def capture_all_orders(*, reason='full_sweep', recent_hours: int | None = None) -> dict[str, int]:
    if not _enabled_from_state():
        return {'seen': 0, 'captured': 0}
    seen = captured = 0
    for order in _order_queryset(recent_hours=recent_hours).iterator(chunk_size=200):
        # Factory Reset must be able to quiesce this worker before deleting the
        # database and evidence directory.  Bound shutdown even during a large
        # first-run backfill instead of waiting for every historical row.
        if _STOP.is_set():
            break
        seen += 1
        if _COLLECTOR.capture(order, reason=reason):
            captured += 1
    _COLLECTOR.flush()
    return {'seen': seen, 'captured': captured}


def capture_order_id(order_id: int, *, reason='model_change') -> bool:
    try:
        order = _order_queryset().get(pk=order_id)
    except Exception:  # noqa: BLE001 - it may have been hard-deleted
        logger.debug('order audit: order %s unavailable at capture time', order_id)
        return False
    return _COLLECTOR.capture(order, reason=reason)


def request_capture(order_id: int | None, reason: str) -> None:
    if order_id is None or not _enabled_from_state():
        return
    order_id = int(order_id)
    reason = str(reason)
    # A checkout touches Order, every item, payment, stock row and sometimes a
    # fiscal/courier sidecar in one commit. Each signal used to enqueue another
    # full graph serialization for the same final order, producing an unbounded
    # query backlog on a busy till. Coalesce while queued; once the worker pops
    # this id, a genuinely later commit can enqueue it again immediately.
    with _PENDING_CAPTURE_LOCK:
        if order_id in _PENDING_CAPTURES:
            _PENDING_CAPTURES[order_id] = reason
            return
        _PENDING_CAPTURES[order_id] = reason
        _CAPTURE_QUEUE.put((order_id, reason))


def request_full_sweep(reason='manual_sweep') -> None:
    _CAPTURE_QUEUE.put((-1, str(reason)))


def _register_signals() -> None:
    from django.db import transaction
    from django.db.models.signals import post_delete, post_save
    from base.models import Order, SyncState

    def after_commit(order_id, reason):
        transaction.on_commit(lambda: request_capture(order_id, reason))

    def order_changed(sender, instance, **kwargs):
        after_commit(instance.pk, f'{sender.__name__}.save')

    def sync_state_changed(sender, instance, **kwargs):
        snapshot = {
            'key': str(instance.key),
            'value': _redact_sync_value(instance.value, key=str(instance.key)),
            'updated_at': _iso(instance.updated_at),
        }
        transaction.on_commit(
            lambda: _on_sync_evidence('sync_state_saved', snapshot),
        )

    post_save.connect(order_changed, sender=Order, weak=False,
                      dispatch_uid='desktop.order_audit.order.save')
    # Subscribe to every installed reverse Order relation instead of maintaining
    # a brittle hand-written list.  Fiscal receipts, courier assignments,
    # discounts, print jobs, stock rows and future apps therefore trigger a new
    # post-commit snapshot immediately.
    for relation in Order._meta.related_objects:
        sender = relation.related_model
        order_attname = relation.field.attname
        model_label = str(sender._meta.label_lower)

        def related_changed(
            sender, instance, *, _order_attname=order_attname, **kwargs,
        ):
            order_id = _safe_attr(instance, _order_attname)
            if order_id is not None:
                operation = 'delete' if kwargs.get('signal') is post_delete else 'save'
                after_commit(order_id, f'{sender.__name__}.{operation}')

        post_save.connect(
            related_changed, sender=sender, weak=False,
            dispatch_uid=f'desktop.order_audit.{model_label}.save',
        )
        post_delete.connect(
            related_changed, sender=sender, weak=False,
            dispatch_uid=f'desktop.order_audit.{model_label}.delete',
        )

    def connect_sidecar(sender, resolver) -> None:
        model_label = str(sender._meta.label_lower)

        def sidecar_changed(sender, instance, **kwargs):
            try:
                order_id = resolver(instance)
            except Exception:  # noqa: BLE001
                order_id = None
            if order_id is not None:
                operation = 'delete' if kwargs.get('signal') is post_delete else 'save'
                after_commit(order_id, f'{sender.__name__}.{operation}')

        for signal, operation in ((post_save, 'save'), (post_delete, 'delete')):
            signal.connect(
                sidecar_changed, sender=sender, weak=False,
                dispatch_uid=f'desktop.order_audit.{model_label}.{operation}',
            )

    # These models intentionally use hidden FKs or integer correlation IDs and
    # therefore do not appear in Order._meta.related_objects.
    try:
        from couriers.models import CourierNotification
        connect_sidecar(CourierNotification, lambda row: row.order_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        from notifications.models import (
            CartItem, LoyaltyRedemption, OrderLoyaltyCredit,
            OrderNotificationDispatch,
        )
        connect_sidecar(CartItem, lambda row: row.cart.order_id)
        connect_sidecar(LoyaltyRedemption, lambda row: row.order_id)
        connect_sidecar(OrderLoyaltyCredit, lambda row: row.order_id)
        connect_sidecar(OrderNotificationDispatch, lambda row: row.order_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        from base.models import AuditLog
        connect_sidecar(
            AuditLog,
            lambda row: (
                row.target_id
                if str(row.target_type or '').lower() == 'order' else None
            ),
        )
    except Exception:  # noqa: BLE001
        pass
    post_save.connect(sync_state_changed, sender=SyncState, weak=False,
                      dispatch_uid='desktop.order_audit.sync_state.save')

    from base.services.sync.evidence import register_sync_evidence_observer
    register_sync_evidence_observer(_on_sync_evidence)


def _on_sync_evidence(event_type: str, payload: dict[str, Any]) -> None:
    """Fsync an exact core event before the sync engine can discard it."""
    if not _enabled_from_state():
        return
    try:
        original = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            default=str,
        ).encode('utf-8')
        safe_payload = _redact_sync_value(payload)
        envelope = {
            'payload_sha256': hashlib.sha256(original).hexdigest(),
            'payload': safe_payload,
        }
        _COLLECTOR.record_event(
            'sync_lifecycle', envelope, reason=str(event_type),
        )
    except Exception:  # noqa: BLE001 - evidence cannot affect sync
        logger.exception('order audit: could not copy sync evidence event')


def _drain_sync_events(*, limit: int = 250) -> int:
    drained = 0
    while drained < limit:
        try:
            event_type, payload = _SYNC_EVENT_QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            _COLLECTOR.record_event(
                'sync_lifecycle', payload, reason=event_type,
            )
        finally:
            _SYNC_EVENT_QUEUE.task_done()
        drained += 1
    return drained


def _collector_worker() -> None:
    # A full asynchronous bootstrap makes the file immediately useful for
    # historical comparison without delaying the POS window or checkout path.
    try:
        request_full_sweep('startup_backfill')
        next_sweep = time.monotonic() + _SWEEP_SECONDS
        while not _STOP.is_set():
            _drain_sync_events()
            timeout = max(0.1, min(1.0, next_sweep - time.monotonic()))
            try:
                order_id, reason = _CAPTURE_QUEUE.get(timeout=timeout)
            except queue.Empty:
                order_id = None
                reason = ''
            if order_id is not None:
                try:
                    if order_id == -1:
                        capture_all_orders(reason=reason)
                    else:
                        with _PENDING_CAPTURE_LOCK:
                            reason = _PENDING_CAPTURES.pop(order_id, reason)
                        capture_order_id(order_id, reason=reason)
                except Exception:  # noqa: BLE001 - retry/backstop must keep running
                    logger.exception('order audit queued capture failed')
                finally:
                    _CAPTURE_QUEUE.task_done()
            if time.monotonic() >= next_sweep:
                try:
                    capture_all_orders(
                        reason='periodic_backstop', recent_hours=_RECENT_HOURS,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception('order audit periodic sweep failed')
                next_sweep = time.monotonic() + _SWEEP_SECONDS
    finally:
        _drain_sync_events(limit=10000)
        _COLLECTOR.flush()
        # Django connections are thread-local. Closing them from the bridge's
        # request thread is not enough; release this worker's own DB handle so
        # Factory Reset can remove the embedded cluster on Windows.
        try:
            from django.db import connections
            connections.close_all()
        except Exception:  # noqa: BLE001 - shutdown remains best effort here
            logger.debug('order audit: worker DB close failed', exc_info=True)


def start_background_collector() -> bool:
    global _STARTED, _THREAD, _SENDER_THREAD
    with _START_LOCK:
        if _STARTED:
            return False
        _STOP.clear()
        _register_signals()
        thread = threading.Thread(
            target=_collector_worker, name='order-audit', daemon=True,
        )
        sender_thread = threading.Thread(
            target=_auto_sender_worker, name='order-audit-telegram', daemon=True,
        )
        _THREAD = thread
        _SENDER_THREAD = sender_thread
        _STARTED = True
        try:
            thread.start()
            sender_thread.start()
        except Exception:
            _STOP.set()
            _AUTO_WAKE.set()
            _THREAD = None
            _SENDER_THREAD = None
            _STARTED = False
            raise
        _AUTO_WAKE.set()
        logger.info(
            'local order audit started (enabled=%s auto_send=%s)',
            _enabled_from_state(), _auto_send_enabled_from_state(),
        )
        return True


def stop_background_collector(*, timeout=35.0) -> bool:
    """Stop and join the writer before destructive install maintenance.

    Factory Reset is the important caller: it must never report success while
    this thread can recreate ``order_audit/`` or still owns a Postgres handle.
    """
    global _STARTED, _THREAD, _SENDER_THREAD
    with _START_LOCK:
        thread = _THREAD
        sender_thread = _SENDER_THREAD
        if not _STARTED and thread is None and sender_thread is None:
            _COLLECTOR.flush()
            _STARTED = False
            _THREAD = None
            _SENDER_THREAD = None
            return True
        _STOP.set()
        _AUTO_WAKE.set()
    deadline = time.monotonic() + max(0.0, float(timeout))
    for worker in (thread, sender_thread):
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
    stopped = all(
        worker is None or not worker.is_alive()
        for worker in (thread, sender_thread)
    )
    if not stopped:
        logger.error('order audit collector did not stop within %.1f seconds', timeout)
        return False
    with _START_LOCK:
        if _THREAD is thread:
            _THREAD = None
            _SENDER_THREAD = None
            _STARTED = False
    try:
        from base.services.sync.evidence import unregister_sync_evidence_observer
        unregister_sync_evidence_observer(_on_sync_evidence)
    except Exception:  # noqa: BLE001
        logger.debug('order audit: observer unregister failed', exc_info=True)
    return True


def _parse_chat_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = re.split(r'[\s,;]+', str(value or ''))
    out = []
    for part in parts:
        chat_id = str(part or '').strip()
        if chat_id and chat_id not in out:
            out.append(chat_id)
    return out


def _telegram_delivery_configuration() -> tuple[str, list[str]]:
    """Read transport presence without ever exposing the token to the UI."""
    cfg = config_store.read_config()
    token = str(cfg.get('TELEGRAM_BOT_TOKEN') or '').strip()
    # Raw database evidence is materially more sensitive than staff alerts.
    # It must never inherit the broad Notifications recipient list.
    chat_ids = _parse_chat_ids(cfg.get('ORDER_AUDIT_TELEGRAM_CHAT_IDS'))
    # The current Notifications settings persist the token in the local DB.
    # Reuse only that token; recipients remain owner-explicit above.
    if not token:
        try:
            from notifications.models import NotificationSettings
            ns = NotificationSettings.load()
            token = str(ns.bot_token or '').strip()
        except Exception:  # noqa: BLE001 - status remains available before Django
            logger.debug('order audit: local NotificationSettings unavailable', exc_info=True)
    if token == _MASK:
        token = ''
    return token, chat_ids


def _telegram_credentials() -> tuple[str, list[str]]:
    token, chat_ids = _telegram_delivery_configuration()
    if not token:
        raise RuntimeError(
            'Telegram bot token is not configured locally. Add it on the Notifications page.',
        )
    if not chat_ids:
        raise RuntimeError(
            'Dedicated order-audit Telegram chat ID is not configured locally. '
            'Import the owner support configuration before enabling delivery.',
        )
    return token, chat_ids


def _post_telegram_document(
    token: str, chat_id: str, path: Path, caption: str,
) -> None:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - packaged requirements include it
        raise RuntimeError('Direct Telegram export requires the requests package.') from exc
    url = f'https://api.telegram.org/bot{token}/sendDocument'
    with path.open('rb') as document:
        response = requests.post(
            url,
            data={'chat_id': chat_id, 'caption': caption},
            files={'document': (
                path.name, document,
                'application/gzip' if path.suffix == '.gz'
                else 'application/x-ndjson',
            )},
            timeout=(10, 180),
        )
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - non-JSON 200 is not a delivery ACK
        body = None
    if response.status_code != 200 or not isinstance(body, dict) or body.get('ok') is not True:
        try:
            detail = (body or {}).get('description')
        except Exception:  # noqa: BLE001
            detail = None
        raise RuntimeError(
            detail or f'Telegram delivery was not acknowledged (HTTP {response.status_code})'
        )


def _deliver_pending_once() -> dict[str, int]:
    """Attempt one segment per recipient and report progress for tests/status."""
    token, chat_ids = _telegram_credentials()
    _COLLECTOR.clear_auto_send_error('configuration')
    branch = str(config_store.read_config().get('BRANCH_ID') or 'unconfigured')
    result = {'sent': 0, 'failed': 0, 'empty': 0}
    for chat_id in chat_ids:
        if _STOP.is_set():
            break
        path, metadata = _COLLECTOR.prepare_incremental_export(chat_id)
        if path is None:
            result['empty'] += 1
            continue
        try:
            caption = (
                'Alpha POS local raw evidence (automatic)\n'
                f'Branch: {branch}\nDevice: {_device_id()}\n'
                f'Raw bytes: {metadata["start_offset"]}-'
                f'{metadata["end_offset"]}\n'
                f'SHA-256: {metadata["sha256"]}'
            )
            _post_telegram_document(token, chat_id, path, caption)
            _COLLECTOR.mark_delivered(chat_id, metadata['end_offset'])
            result['sent'] += 1
        except Exception as exc:  # noqa: BLE001
            result['failed'] += 1
            _COLLECTOR.set_auto_send_error(exc, chat_id=chat_id)
            logger.warning(
                'automatic order evidence delivery failed for chat %s: %s',
                chat_id, _safe_error(exc),
            )
        finally:
            path.unlink(missing_ok=True)
    return result


def _auto_sender_worker() -> None:
    """Continuously deliver new raw bytes; an ACK is the only cursor advance."""
    last_attempt = 0.0
    try:
        while not _STOP.is_set():
            _AUTO_WAKE.wait(timeout=_AUTO_SEND_SECONDS)
            _AUTO_WAKE.clear()
            if _STOP.is_set():
                break
            # Coalesce a burst of model/sync signals into one small JSONL file
            # instead of producing a Telegram message per database save.
            remaining = _AUTO_SEND_SECONDS - (time.monotonic() - last_attempt)
            if remaining > 0 and _STOP.wait(remaining):
                break
            if not _enabled_from_state() or not _auto_send_enabled_from_state():
                continue
            last_attempt = time.monotonic()
            try:
                _deliver_pending_once()
            except Exception as exc:  # noqa: BLE001
                _COLLECTOR.set_auto_send_error(exc)
                logger.debug(
                    'automatic order evidence delivery deferred: %s',
                    _safe_error(exc),
                )
    finally:
        try:
            from django.db import connections
            connections.close_all()
        except Exception:  # noqa: BLE001
            logger.debug('order audit: sender DB close failed', exc_info=True)


def _safe_error(exc: Any) -> str:
    return _scrub_text(str(exc))[:500]


def send_export_now() -> dict[str, Any]:
    """Send the immutable raw file straight to Telegram, bypassing POS cloud."""
    token, chat_ids = _telegram_credentials()
    path, metadata = _COLLECTOR.prepare_export()
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - packaged requirements include it
        raise RuntimeError('Direct Telegram export requires the requests package.') from exc

    branch = str(config_store.read_config().get('BRANCH_ID') or 'unconfigured')
    caption = (
        f'Alpha POS raw local order audit\n'
        f'Branch: {branch}\nOrders indexed: {metadata["orders"]}\n'
        f'Records: {metadata["records"]}\nPrepared UTC: {metadata["prepared_at"]}'
    )
    sent, failed = [], []
    url = f'https://api.telegram.org/bot{token}/sendDocument'
    for chat_id in chat_ids:
        try:
            with path.open('rb') as document:
                response = requests.post(
                    url,
                    data={'chat_id': chat_id, 'caption': caption},
                    files={'document': (
                        path.name, document,
                        'application/gzip' if path.suffix == '.gz'
                        else 'application/x-ndjson',
                    )},
                    timeout=(10, 180),
                )
            try:
                body = response.json()
            except Exception:  # noqa: BLE001 - non-JSON 200 is not a delivery ACK
                body = None
            if (
                response.status_code != 200
                or not isinstance(body, dict)
                or body.get('ok') is not True
            ):
                try:
                    detail = (body or {}).get('description')
                except Exception:  # noqa: BLE001
                    detail = None
                raise RuntimeError(
                    detail
                    or f'Telegram delivery was not acknowledged '
                       f'(HTTP {response.status_code})'
                )
            sent.append(chat_id)
        except Exception as exc:  # noqa: BLE001
            failed.append({'chat_id': chat_id, 'error': _safe_error(exc)})
            logger.warning('direct order-audit export failed for chat %s: %s',
                           chat_id, _safe_error(exc))
    return {
        'ok': bool(sent) and not failed,
        'partial': bool(sent) and bool(failed),
        'sent_to': sent,
        'failed': failed,
        'file': str(path),
        'filename': path.name,
        **metadata,
    }
