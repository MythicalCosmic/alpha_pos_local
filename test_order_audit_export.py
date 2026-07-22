import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from desktop import bridge, order_audit


class Rows(list):
    def all(self):
        return self


def _row(**values):
    return SimpleNamespace(**values)


def _order(pk=1, *, total='100000.00', payment='100000.00'):
    now = datetime(2026, 7, 21, 8, 15, tzinfo=timezone.utc)
    cashier = _row(pk=7, uuid='cashier-uuid', first_name='Madina', last_name='A')
    product = _row(pk=3, uuid='product-uuid', name='Lavash')
    item = _row(
        pk=11, uuid='item-uuid', product=product, quantity=2,
        original_price=Decimal('50000.00'), price=Decimal('50000.00'),
        discount_amount=Decimal('0'), detail='', ready_at=now,
        is_deleted=False, sync_version=2, synced_at=now,
    )
    payment_row = _row(
        pk=12, uuid='payment-uuid', method='CASH', amount=Decimal(payment),
        payment_action_id='action-uuid', line_index=0, created_at=now,
        is_deleted=False, sync_version=1, synced_at=now,
    )
    return _row(
        pk=pk, id=pk, uuid=f'order-{pk}', display_id=42, order_number=742,
        branch_id='restaurant-1', order_origin='POS', order_type='HALL',
        status='READY', is_paid=True, is_deleted=False,
        created_at=now, updated_at=now, paid_at=now, ready_at=now,
        payment_requested_at=None, subtotal=Decimal('100000.00'),
        discount_amount=Decimal('0'), discount_percent=Decimal('0'),
        total_amount=Decimal(total), payment_method='CASH',
        payment_action_id='action-uuid', accounting_recorded_at=now,
        cashier=cashier, user=cashier, synced_at=now, sync_version=4,
        items=Rows([item]), payments=Rows([payment_row]),
        external_payments=Rows([]), refunds=Rows([]),
    )


@pytest.fixture(autouse=True)
def _collector_enabled(monkeypatch):
    monkeypatch.setattr(order_audit, '_enabled_from_state', lambda: True)
    monkeypatch.setattr(order_audit, '_desktop_version', lambda: '1.0.test')
    monkeypatch.setattr(order_audit, '_device_id', lambda: 'test-device')


def test_default_toggle_is_on_when_setting_is_absent(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(order_audit.config_store, 'read_state', lambda: {})
    assert order_audit._enabled_from_state() is True


def test_snapshot_is_complete_append_only_and_deduplicated(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    order = _order()

    assert collector.capture(order, reason='Order.save') is True
    assert collector.capture(order, reason='periodic_backstop') is False

    order.total_amount = Decimal('99000.00')
    order.payments[0].amount = Decimal('99000.00')
    order.sync_version = 5
    assert collector.capture(order, reason='OrderPayment.save') is True

    rows = [json.loads(line) for line in collector.dataset.read_text(
        encoding='utf-8',
    ).splitlines()]
    assert len(rows) == 2
    latest = rows[-1]
    assert latest['schema_version'] == 1
    assert latest['record_type'] == 'order_snapshot'
    assert latest['capture']['reason'] == 'OrderPayment.save'
    assert latest['capture']['snapshot_sha256']
    captured = latest['order']
    assert captured['uuid'] == 'order-1'
    assert captured['order_number'] == 742
    assert captured['created_at'] == '2026-07-21T08:15:00+00:00'
    assert captured['payment_action_id'] == 'action-uuid'
    assert captured['items'][0]['product']['name'] == 'Lavash'
    assert captured['payments'][0]['line_index'] == 0
    assert captured['sync'] == {
        'pending': False,
        'synced_at': '2026-07-21T08:15:00+00:00',
        'version': 5,
    }
    assert captured['tender_evidence']['combined_by_method'] == {
        'CASH': '99000.00',
    }
    assert captured['tender_evidence']['payment_delta'] == '0.00'


def test_external_payment_is_separate_from_drawer_but_in_combined_tender(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    order = _order(total='130000.00', payment='100000.00')
    now = order.created_at
    order.external_payments.append(_row(
        pk=90, uuid='external-payment-uuid', source='COURIER',
        source_id='provider-event-1', method='PAYME', amount=Decimal('30000.00'),
        occurred_at=now, is_deleted=False, sync_version=1, synced_at=now,
    ))

    assert collector.capture(order) is True
    record = json.loads(collector.dataset.read_text(encoding='utf-8'))
    evidence = record['order']['tender_evidence']
    assert evidence['by_method'] == {'CASH': '100000.00'}
    assert evidence['external_by_method'] == {'PAYME': '30000.00'}
    assert evidence['combined_payment_rows_total'] == '130000.00'
    assert evidence['payment_delta'] == '0.00'
    assert record['order']['external_payments'][0]['source_id'] == 'provider-event-1'


def test_parallel_writers_produce_only_complete_json_lines(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    orders = [_order(pk=i) for i in range(1, 17)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collector.capture, orders))
    assert all(results)

    lines = collector.dataset.read_text(encoding='utf-8').splitlines()
    assert len(lines) == len(orders)
    parsed = [json.loads(line) for line in lines]
    assert {row['order']['uuid'] for row in parsed} == {
        f'order-{i}' for i in range(1, 17)
    }


def test_crash_truncated_tail_does_not_corrupt_next_snapshot(tmp_path):
    dataset = tmp_path / 'orders.raw.jsonl'
    dataset.write_bytes(b'{"truncated":')
    collector = order_audit.OrderAuditCollector(
        dataset=dataset,
        index_file=tmp_path / '.index.json',
    )
    assert collector.capture(_order()) is True

    lines = dataset.read_text(encoding='utf-8').splitlines()
    assert lines[0] == '{"truncated":'
    assert json.loads(lines[1])['order']['uuid'] == 'order-1'


def test_direct_telegram_export_uses_local_config_and_never_leaks_token(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    assert collector.capture(_order())
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    token = '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': token,
            'TELEGRAM_CHAT_IDS': '111111111,-100222222',
            'BRANCH_ID': 'restaurant-1',
        },
    )
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'ok': True}

    def post(url, *, data, files, timeout):
        name, stream, content_type = files['document']
        calls.append({
            'url': url,
            'chat_id': data['chat_id'],
            'filename': name,
            'bytes': stream.read(),
            'content_type': content_type,
            'timeout': timeout,
        })
        return Response()

    import requests
    monkeypatch.setattr(requests, 'post', post)

    result = order_audit.send_export_now()
    assert result['ok'] is True
    assert result['sent_to'] == ['111111111', '-100222222']
    assert len(calls) == 2
    assert all(call['url'].endswith(f'/bot{token}/sendDocument') for call in calls)
    assert all(b'export_manifest' in call['bytes'] for call in calls)
    # Credentials are transport-only: neither raw evidence nor API result keeps them.
    assert all(token.encode() not in call['bytes'] for call in calls)
    assert token not in json.dumps(result)


def test_direct_export_fails_clearly_without_local_credentials(monkeypatch):
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_IDS': ''},
    )
    # Avoid a real Django settings access in the fallback for this unit test.
    monkeypatch.setitem(__import__('sys').modules, 'notifications.models', None)
    with pytest.raises(RuntimeError, match='bot token is not configured locally'):
        order_audit._telegram_credentials()


def test_transport_error_redacts_bot_token(tmp_path, monkeypatch):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    collector.capture(_order())
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    token = '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': token,
            'TELEGRAM_CHAT_IDS': '111111111',
            'BRANCH_ID': 'restaurant-1',
        },
    )

    import requests
    monkeypatch.setattr(
        requests, 'post',
        lambda url, **kwargs: (_ for _ in ()).throw(RuntimeError(url)),
    )
    result = order_audit.send_export_now()
    assert result['ok'] is False
    assert '[redacted-token]' in result['failed'][0]['error']
    assert token not in json.dumps(result)


def test_collector_stop_joins_writer_before_reset(monkeypatch):
    started = threading.Event()

    def worker():
        started.set()
        order_audit._STOP.wait(5)

    monkeypatch.setattr(order_audit, '_collector_worker', worker)
    monkeypatch.setattr(order_audit, '_register_signals', lambda: None)
    monkeypatch.setattr(order_audit, '_STARTED', False)
    monkeypatch.setattr(order_audit, '_THREAD', None)
    monkeypatch.setattr(order_audit, '_STOP', threading.Event())

    assert order_audit.start_background_collector() is True
    assert started.wait(1)
    thread = order_audit._THREAD
    assert thread is not None and thread.is_alive()
    assert order_audit.stop_background_collector(timeout=1) is True
    assert not thread.is_alive()
    assert order_audit._STARTED is False
    assert order_audit._THREAD is None


def test_factory_reset_aborts_when_audit_writer_cannot_quiesce(monkeypatch):
    api = bridge.Api.__new__(bridge.Api)
    api.server = _row(stop=lambda **kwargs: {
        'workers_quiescent': True,
    })
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(
        order_audit, 'stop_background_collector', lambda **kwargs: False,
    )
    reset_called = []
    monkeypatch.setattr(
        bridge.config_store, 'factory_reset', lambda: reset_called.append(True),
    )

    result = api.factory_reset(True)

    assert result['ok'] is False
    assert 'audit' in result['error'].lower()
    assert reset_called == []
