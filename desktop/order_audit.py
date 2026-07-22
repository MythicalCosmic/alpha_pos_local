"""Append-only local order evidence and direct Telegram export.

This is deliberately a *desktop* diagnostic, not another sync channel.  It
records complete local order snapshots independently of the cloud receiver so
an operator can compare what the till actually held with what reached the
server.  The raw dataset never contains Telegram credentials and sending uses
Telegram's Bot API directly from the desktop process.
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

from desktop import config_store


logger = logging.getLogger('desktop.order_audit')

SCHEMA_VERSION = 1
AUDIT_DIR = config_store.DATA_DIR / 'order_audit'
RAW_DATASET = AUDIT_DIR / 'orders.raw.jsonl'
INDEX_FILE = AUDIT_DIR / '.orders.raw.index.json'
_MASK = '\u2022' * 8
_TOKEN_RE = re.compile(r'(?<!\d)\d{5,}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])')
_SWEEP_SECONDS = 300
# Signals capture normal writes immediately. A small rolling rescan repairs a
# missed/bulk header update without repeatedly materializing several busy days
# of orders on a low-powered till.
_RECENT_HOURS = 2
_MAX_PLAIN_TELEGRAM_BYTES = 45 * 1024 * 1024


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
            'id': _safe_attr(item, 'pk', _safe_attr(item, 'id')),
            'uuid': _text(_safe_attr(item, 'uuid')),
            'product': _identity(product),
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
        'id': _safe_attr(order, 'pk', _safe_attr(order, 'id')),
        'uuid': _text(_safe_attr(order, 'uuid')),
        'display_id': _safe_attr(order, 'display_id'),
        'order_number': _safe_attr(order, 'order_number'),
        'branch_id': _text(_safe_attr(order, 'branch_id', '')) or '',
        'origin': _text(origin),
        'order_type': _text(_safe_attr(order, 'order_type')),
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
        'shift_id': _safe_attr(order, 'shift_id'),
        'sync': {
            'version': _safe_attr(order, 'sync_version'),
            'synced_at': _iso(_safe_attr(order, 'synced_at')),
            'pending': _safe_attr(order, 'synced_at') is None,
        },
        'items': items,
        'payments': payments,
        'external_payments': external_payments,
        'refunds': refunds,
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
    ).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _desktop_version() -> str:
    try:
        from desktop.version import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return 'unknown'


def _device_id() -> str:
    """Stable non-secret till identity for cross-file reconciliation."""
    return str(
        os.environ.get('DEVICE_ID') or config_store.load_or_generate_device_id()
    )


def _enabled_from_state() -> bool:
    settings = config_store.read_state().get('order_audit') or {}
    return settings.get('enabled', True) is not False


class OrderAuditCollector:
    def __init__(self, *, dataset: Path = RAW_DATASET, index_file: Path = INDEX_FILE):
        self.dataset = Path(dataset)
        self.index_file = Path(index_file)
        self._lock = threading.RLock()
        self._fingerprints: dict[str, str] = {}
        self._record_count = 0
        self._last_capture_at: str | None = None
        self._last_export_at: str | None = None
        self._last_error = ''
        self._index_dirty = 0
        self._index_written_at = 0.0
        self._load_index()

    def _load_index(self) -> None:
        # The index is only a deduplication cache, never the evidence source. If
        # the raw file was intentionally removed, ignore a stale cache and let
        # the startup sweep rebuild a complete dataset.
        if (
            not self.index_file.exists()
            or not self.dataset.exists()
            or self.dataset.stat().st_size == 0
        ):
            return
        try:
            data = json.loads(self.index_file.read_text(encoding='utf-8'))
            self._fingerprints = dict(data.get('fingerprints') or {})
            self._record_count = int(data.get('record_count') or 0)
            self._last_capture_at = data.get('last_capture_at')
            self._last_export_at = data.get('last_export_at')
        except Exception:  # noqa: BLE001
            logger.warning('order audit index unreadable; rebuilding safely', exc_info=True)

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
            'fingerprints': self._fingerprints,
        }
        config_store._write_protected(
            self.index_file,
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n',
        )
        self._index_dirty = 0
        self._index_written_at = time.monotonic()

    def _append(self, record: dict[str, Any]) -> None:
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
                        'desktop_version': _desktop_version(),
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

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                'enabled': _enabled_from_state(),
                'dataset': str(self.dataset),
                'exists': self.dataset.exists(),
                'bytes': self.dataset.stat().st_size if self.dataset.exists() else 0,
                'order_count': len(self._fingerprints),
                'record_count': self._record_count,
                'last_capture_at': self._last_capture_at,
                'last_export_at': self._last_export_at,
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


_COLLECTOR = OrderAuditCollector()
_CAPTURE_QUEUE: queue.Queue[tuple[int, str]] = queue.Queue()
_START_LOCK = threading.Lock()
_STARTED = False
_STOP = threading.Event()
_THREAD: threading.Thread | None = None


def get_status() -> dict[str, Any]:
    return _COLLECTOR.status()


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
    return get_status()


def _order_queryset(*, recent_hours: int | None = None):
    from base.models import Order
    qs = Order.objects.select_related('user', 'cashier').prefetch_related(
        'items__product', 'payments', 'external_payments', 'refunds',
    ).order_by('pk')
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
    _CAPTURE_QUEUE.put((int(order_id), str(reason)))


def request_full_sweep(reason='manual_sweep') -> None:
    _CAPTURE_QUEUE.put((-1, str(reason)))


def _register_signals() -> None:
    from django.db import transaction
    from django.db.models.signals import post_delete, post_save
    from base.models import (
        ExternalOrderPayment, Order, OrderItem, OrderPayment, OrderRefund,
    )

    def after_commit(order_id, reason):
        transaction.on_commit(lambda: request_capture(order_id, reason))

    def order_changed(sender, instance, **kwargs):
        after_commit(instance.pk, f'{sender.__name__}.save')

    def child_changed(sender, instance, **kwargs):
        after_commit(instance.order_id, f'{sender.__name__}.save')

    post_save.connect(order_changed, sender=Order, weak=False,
                      dispatch_uid='desktop.order_audit.order.save')
    post_save.connect(child_changed, sender=OrderItem, weak=False,
                      dispatch_uid='desktop.order_audit.item.save')
    post_save.connect(child_changed, sender=OrderPayment, weak=False,
                      dispatch_uid='desktop.order_audit.payment.save')
    post_save.connect(child_changed, sender=ExternalOrderPayment, weak=False,
                      dispatch_uid='desktop.order_audit.external_payment.save')
    post_save.connect(child_changed, sender=OrderRefund, weak=False,
                      dispatch_uid='desktop.order_audit.refund.save')
    post_delete.connect(child_changed, sender=OrderItem, weak=False,
                        dispatch_uid='desktop.order_audit.item.delete')
    post_delete.connect(child_changed, sender=OrderPayment, weak=False,
                        dispatch_uid='desktop.order_audit.payment.delete')


def _collector_worker() -> None:
    # A full asynchronous bootstrap makes the file immediately useful for
    # historical comparison without delaying the POS window or checkout path.
    try:
        request_full_sweep('startup_backfill')
        next_sweep = time.monotonic() + _SWEEP_SECONDS
        while not _STOP.is_set():
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
    global _STARTED, _THREAD
    with _START_LOCK:
        if _STARTED:
            return False
        _STOP.clear()
        _register_signals()
        thread = threading.Thread(
            target=_collector_worker, name='order-audit', daemon=True,
        )
        _THREAD = thread
        _STARTED = True
        try:
            thread.start()
        except Exception:
            _THREAD = None
            _STARTED = False
            raise
        logger.info('local order audit collector started (enabled=%s)', _enabled_from_state())
        return True


def stop_background_collector(*, timeout=35.0) -> bool:
    """Stop and join the writer before destructive install maintenance.

    Factory Reset is the important caller: it must never report success while
    this thread can recreate ``order_audit/`` or still owns a Postgres handle.
    """
    global _STARTED, _THREAD
    with _START_LOCK:
        thread = _THREAD
        if not _STARTED or thread is None:
            _COLLECTOR.flush()
            _STARTED = False
            _THREAD = None
            return True
        _STOP.set()
    if thread is not threading.current_thread():
        thread.join(timeout=max(0.0, float(timeout)))
    stopped = not thread.is_alive()
    if not stopped:
        logger.error('order audit collector did not stop within %.1f seconds', timeout)
        return False
    with _START_LOCK:
        if _THREAD is thread:
            _THREAD = None
            _STARTED = False
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


def _telegram_credentials() -> tuple[str, list[str]]:
    cfg = config_store.read_config()
    token = str(cfg.get('TELEGRAM_BOT_TOKEN') or '').strip()
    chat_ids = _parse_chat_ids(cfg.get('TELEGRAM_CHAT_IDS'))
    # The current Notifications screen persists its values in the local DB.
    # Read that canonical local fallback, still without contacting AlphaPOS cloud.
    if not token or not chat_ids:
        try:
            from notifications.models import NotificationSettings
            ns = NotificationSettings.load()
            token = token or str(ns.bot_token or '').strip()
            chat_ids = chat_ids or _parse_chat_ids(ns.chat_ids)
        except Exception:  # noqa: BLE001
            logger.debug('order audit: local NotificationSettings unavailable', exc_info=True)
    if not token or token == _MASK:
        raise RuntimeError(
            'Telegram bot token is not configured locally. Add it on the Notifications page.',
        )
    if not chat_ids:
        raise RuntimeError(
            'Telegram chat ID is not configured locally. Add a recipient on the Notifications page.',
        )
    return token, chat_ids


def _safe_error(exc: Any) -> str:
    return _TOKEN_RE.sub('[redacted-token]', str(exc))[:500]


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
            if response.status_code != 200:
                try:
                    detail = (response.json() or {}).get('description')
                except Exception:  # noqa: BLE001
                    detail = None
                raise RuntimeError(detail or f'Telegram HTTP {response.status_code}')
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
