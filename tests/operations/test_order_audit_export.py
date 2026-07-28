"""Order-audit capture and export tests."""

import json
import gzip
import hashlib
import queue
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.http import JsonResponse
from django.test import RequestFactory

from desktop import bridge, order_audit, order_http_audit


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
    monkeypatch.setattr(order_audit, '_PROCESS_SHUTDOWN', threading.Event())


def test_default_toggle_is_on_when_setting_is_absent(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(order_audit.config_store, 'read_state', lambda: {})
    assert order_audit._enabled_from_state() is True


def test_default_automatic_delivery_is_on_when_setting_is_absent(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(order_audit.config_store, 'read_state', lambda: {})
    assert order_audit._auto_send_enabled_from_state() is True


def test_order_http_audit_wraps_login_transition_guard_after_django_auth():
    from config import settings as local_settings

    auth = local_settings._DJANGO_AUTH_MIDDLEWARE
    audit = local_settings._ORDER_HTTP_AUDIT_MIDDLEWARE
    guard = local_settings._LOGIN_TRANSITION_GUARD_MIDDLEWARE
    simulated = local_settings._with_order_http_audit([
        'before',
        auth,
        guard,
        'after',
    ])
    assert simulated.index(auth) < simulated.index(audit)
    assert simulated.index(audit) + 1 == simulated.index(guard)

    actual = list(settings.MIDDLEWARE)
    assert actual.index(auth) < actual.index(audit)
    if guard in actual:
        assert actual.index(audit) + 1 == actual.index(guard)


def test_repeated_order_signals_coalesce_one_pending_graph_capture(monkeypatch):
    pending_queue = queue.Queue()
    monkeypatch.setattr(order_audit, '_CAPTURE_QUEUE', pending_queue)
    monkeypatch.setattr(order_audit, '_PENDING_CAPTURES', {})

    order_audit.request_capture(42, 'Order.save')
    order_audit.request_capture(42, 'OrderPayment.save')
    order_audit.request_capture(42, 'FiscalReceipt.save')

    assert pending_queue.qsize() == 1
    assert order_audit._PENDING_CAPTURES == {42: 'FiscalReceipt.save'}


def test_database_faithful_rows_keep_all_columns_and_redact_credentials():
    class Field:
        def __init__(self, name, *, attname=None, is_relation=False):
            self.name = name
            self.attname = attname or name
            self.is_relation = is_relation

    obj = _row(
        id=17,
        total_amount=Decimal('639400.00'),
        provider_payload={'receipt': 'abc', 'api_token': 'must-not-leave'},
        private_key='must-not-leave-either',
    )
    obj._meta = _row(concrete_fields=[
        Field('id'),
        Field('total_amount'),
        Field('provider_payload'),
        Field('private_key'),
    ])

    raw = order_audit._concrete_fields(obj)
    assert raw['id'] == 17
    assert raw['total_amount'] == '639400.00'
    assert raw['provider_payload'] == {
        'receipt': 'abc',
        'api_token': '[REDACTED]',
    }
    assert raw['private_key'] == '[REDACTED]'


def test_every_reverse_order_relation_is_captured_with_linked_row():
    class Field:
        def __init__(self, name, *, attname=None, is_relation=False):
            self.name = name
            self.attname = attname or name
            self.is_relation = is_relation

    courier = _row(id=9, name='Courier A', phone='998901112233')
    courier._meta = _row(concrete_fields=[Field('id'), Field('name'), Field('phone')])
    assignment = _row(id=5, order_id=1, courier_id=9, courier=courier, step='ON_WAY')
    assignment._meta = _row(
        label='couriers.DeliveryAssignment',
        concrete_fields=[
            Field('id'),
            Field('order', attname='order_id', is_relation=True),
            Field('courier', attname='courier_id', is_relation=True),
            Field('step'),
        ],
    )
    related_model = _row(_meta=assignment._meta)

    class Relation:
        @staticmethod
        def get_accessor_name():
            return 'courier_delivery'

    Relation.related_model = related_model

    order = _row(courier_delivery=assignment)
    order._meta = _row(related_objects=[Relation()])

    rows = order_audit._all_related_rows(order)
    captured = rows['courier_delivery']['rows'][0]
    assert captured['raw'] == {
        'id': 5,
        'order_id': 1,
        'courier_id': 9,
        'step': 'ON_WAY',
    }
    assert captured['linked']['courier']['phone'] == '998901112233'


def test_free_text_and_gateway_links_never_export_embedded_credentials():
    raw = (
        'provider error Bearer abcdefghijklmnop token=raw-secret '
        'https://pay.example/checkout/invoice-7?signature=signed-grant&ok=1 '
        '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd'
    )
    scrubbed = order_audit._redact_sync_value({'error': raw})
    rendered = json.dumps(scrubbed)
    assert 'abcdefghijklmnop' not in rendered
    assert 'raw-secret' not in rendered
    assert 'signed-grant' not in rendered
    assert 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd' not in rendered

    class Field:
        name = 'link'
        attname = 'link'

    payment = _row(link='https://pay.example/checkout/grant-7?token=grant-secret')
    payment._meta = _row(
        label_lower='couriers.courierpayment', concrete_fields=[Field()],
    )
    evidence = order_audit._concrete_fields(payment)['link']
    assert evidence['host'] == 'pay.example'
    assert evidence['path_sha256']
    assert evidence['path_segment_count'] == 2
    assert evidence['sha256']
    assert 'grant-7' not in json.dumps(evidence)
    assert 'grant-secret' not in json.dumps(evidence)


@pytest.mark.django_db
def test_real_order_raw_keys_match_every_database_column_and_no_fake_shift():
    from base.models import Order, User

    user = User.objects.create(
        first_name='Raw', last_name='Audit', email='raw-audit@example.local',
        password='credential-must-be-redacted', role='CASHIER', status='ACTIVE',
    )
    order = Order.objects.create(
        user=user, cashier=user, total_amount=Decimal('1000.00'),
        subtotal=Decimal('1000.00'), status='PREPARING',
        phone_number='998901234567', delivery_address='Test address',
        description='Test note',
    )
    snapshot = order_audit.serialize_order(order)

    expected = {field.attname for field in Order._meta.concrete_fields}
    assert set(snapshot['raw']) == expected
    assert 'shift_id' not in snapshot
    assert snapshot['phone_number'] == '998901234567'
    assert snapshot['delivery_address'] == 'Test address'
    assert snapshot['description'] == 'Test note'
    assert snapshot['linked_entities']['user']['password'] == '[REDACTED]'
    assert set(snapshot['related_rows']) == {
        relation.get_accessor_name() for relation in Order._meta.related_objects
    }


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


def test_records_form_a_verifiable_hash_chain(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    collector.capture(_order(pk=1))
    collector.capture(_order(pk=2))
    rows = [json.loads(line) for line in collector.dataset.read_text().splitlines()]
    assert rows[0]['integrity']['previous_record_sha256'] is None
    assert rows[1]['integrity']['previous_record_sha256'] == (
        rows[0]['integrity']['record_sha256']
    )
    for row in rows:
        claimed = row['integrity'].pop('record_sha256')
        canonical = json.dumps(
            row, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode()
        import hashlib
        assert hashlib.sha256(canonical).hexdigest() == claimed


def test_rotation_bounds_active_file_and_export_keeps_all_retained_segments(
    tmp_path,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
        max_dataset_bytes=1,
        max_archive_bytes=1024 * 1024,
        archive_retention_days=365,
    )
    for sequence in range(1, 4):
        assert collector.record_event(
            'test_event', {'sequence': sequence}, reason='rotation_test',
        )

    status = collector.status()
    assert status['archive_count'] == 2
    assert status['bytes'] <= max(
        path.stat().st_size for path in collector._evidence_files()
    )
    retained = [
        json.loads(line)
        for path in collector._evidence_files()
        for line in path.read_text(encoding='utf-8').splitlines()
    ]
    assert [row['event']['sequence'] for row in retained] == [1, 2, 3]
    assert retained[0]['integrity']['previous_record_sha256'] is None
    for previous, current in zip(retained, retained[1:]):
        assert current['integrity']['previous_record_sha256'] == (
            previous['integrity']['record_sha256']
        )

    export, metadata = collector.prepare_export()
    exported = [
        json.loads(line)
        for line in export.read_text(encoding='utf-8').splitlines()
    ]
    assert [row['event']['sequence'] for row in exported[:-1]] == [1, 2, 3]
    assert exported[-1]['record_type'] == 'export_manifest'
    assert metadata['segments'] == 4


def test_rotation_preserves_pending_delivery_cursor_per_segment(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
        max_dataset_bytes=1,
        max_archive_bytes=1024 * 1024,
        archive_retention_days=365,
    )
    collector.record_event('test_event', {'sequence': 1}, reason='delivery_test')
    collector.record_event('test_event', {'sequence': 2}, reason='delivery_test')

    first, first_meta = collector.prepare_incremental_export(
        'owner', max_bytes=1,
    )
    assert first_meta['source_kind'] == 'archive'
    with gzip.open(first, 'rb') as source:
        assert json.loads(source.read())['event']['sequence'] == 1
    collector.mark_delivered(
        'owner',
        first_meta['end_offset'],
        source_name=first_meta['source_name'],
    )

    second, second_meta = collector.prepare_incremental_export(
        'owner', max_bytes=1,
    )
    assert second_meta['source_kind'] == 'active'
    with gzip.open(second, 'rb') as source:
        assert json.loads(source.read())['event']['sequence'] == 2


def test_archive_byte_cap_prunes_old_segments(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
        max_dataset_bytes=1,
        max_archive_bytes=0,
        archive_retention_days=365,
    )
    collector.record_event('test_event', {'sequence': 1}, reason='retention_test')
    pruned_hash = json.loads(
        collector.dataset.read_text(encoding='utf-8'),
    )['integrity']['record_sha256']
    collector.record_event('test_event', {'sequence': 2}, reason='retention_test')

    status = collector.status()
    assert status['archive_count'] == 0
    assert status['archive_bytes'] == 0
    assert status['pruned_archive_count'] == 1
    current = json.loads(collector.dataset.read_text(encoding='utf-8'))
    assert current['event']['sequence'] == 2
    # A retained-out predecessor stays represented by its non-recoverable
    # digest, making the policy-created chain gap explicit instead of silent.
    assert current['integrity']['previous_record_sha256'] == pruned_hash


def test_restart_recovers_raw_chain_head_when_cache_lags_after_crash(tmp_path):
    dataset = tmp_path / 'orders.raw.jsonl'
    index = tmp_path / '.index.json'
    collector = order_audit.OrderAuditCollector(dataset=dataset, index_file=index)
    collector.capture(_order(pk=1))
    cached_after_first = json.loads(index.read_text())
    collector.capture(_order(pk=2))
    assert json.loads(index.read_text())['record_count'] == cached_after_first['record_count']

    recovered = order_audit.OrderAuditCollector(dataset=dataset, index_file=index)
    assert recovered.status()['record_count'] == 2
    assert recovered.status()['order_count'] == 2
    prior = json.loads(dataset.read_text().splitlines()[-1])
    recovered.capture(_order(pk=3))
    latest = json.loads(dataset.read_text().splitlines()[-1])
    assert latest['integrity']['previous_record_sha256'] == (
        prior['integrity']['record_sha256']
    )


def test_restart_recovers_only_active_tail_when_archives_are_unchanged(
    tmp_path, monkeypatch,
):
    dataset = tmp_path / 'orders.raw.jsonl'
    index = tmp_path / '.index.json'
    collector = order_audit.OrderAuditCollector(
        dataset=dataset,
        index_file=index,
        max_dataset_bytes=1,
        max_archive_bytes=1024 * 1024,
        archive_retention_days=365,
    )
    collector.record_event('test_event', {'sequence': 1}, reason='tail_test')
    collector.record_event('test_event', {'sequence': 2}, reason='tail_test')
    assert collector.status()['archive_count'] == 1

    # Simulate power loss after the active JSONL fsync but before the
    # deliberately throttled index update.
    collector.max_dataset_bytes = 1024 * 1024
    monkeypatch.setattr(collector, '_flush_index', lambda **_kwargs: None)
    collector.record_event('test_event', {'sequence': 3}, reason='tail_test')

    def full_rebuild_would_delay_startup(_self):
        raise AssertionError('unchanged archives must not be rescanned')

    monkeypatch.setattr(
        order_audit.OrderAuditCollector,
        '_rebuild_cache_from_raw',
        full_rebuild_would_delay_startup,
    )
    recovered = order_audit.OrderAuditCollector(
        dataset=dataset,
        index_file=index,
        max_dataset_bytes=1024 * 1024,
        max_archive_bytes=1024 * 1024,
        archive_retention_days=365,
    )
    assert recovered.status()['record_count'] == 3
    assert recovered.status()['archive_count'] == 1


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
            'TELEGRAM_BOT_TOKEN': '',
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': token,
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '111111111,-100222222',
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


def test_direct_export_redacts_exact_selected_token_from_network_errors(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    assert collector.capture(_order())
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    # Deliberately does not match the generic Telegram-token regex. The exact
    # selected secret must still be removed if requests echoes its URL.
    token = 'malformed:legacy-secret'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': token,
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'owner-a',
            'BRANCH_ID': 'restaurant-1',
        },
    )

    import requests

    def post(url, **_kwargs):
        raise RuntimeError(f'network failure while posting to {url}')

    monkeypatch.setattr(requests, 'post', post)

    result = order_audit.send_export_now()
    serialized = json.dumps({
        'result': result,
        'status': collector.status(chat_ids=['owner-a']),
    })

    assert result['ok'] is False
    assert result['failed']
    assert token not in serialized
    assert '[redacted-token]' in serialized


def test_direct_export_fails_clearly_without_local_credentials(monkeypatch):
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': '',
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': '',
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '',
        },
    )
    with pytest.raises(RuntimeError, match='Open Local Telegram Audit'):
        order_audit._telegram_credentials()


def test_raw_evidence_never_falls_back_to_staff_notification_recipients(monkeypatch):
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd',
            'TELEGRAM_CHAT_IDS': 'staff-chat,manager-chat',
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': '',
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '',
        },
    )
    with pytest.raises(RuntimeError, match='Open Local Telegram Audit'):
        order_audit._telegram_credentials()


def test_raw_evidence_falls_back_to_complete_local_audit_pair(monkeypatch):
    local_token = '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': '',
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': local_token,
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'owner-a, owner-b',
        },
    )

    token, chat_ids, source = (
        order_audit._telegram_delivery_configuration_details()
    )

    assert token == local_token
    assert chat_ids == ['owner-a', 'owner-b']
    assert source == 'local_telegram_audit'


def test_complete_explicit_raw_pair_takes_precedence_over_local_pair(monkeypatch):
    raw_token = '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_raw'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': raw_token,
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': 'raw-owner',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': (
                '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local'
            ),
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'local-owner',
        },
    )

    token, chat_ids, source = (
        order_audit._telegram_delivery_configuration_details()
    )

    assert token == raw_token
    assert chat_ids == ['raw-owner']
    assert source == 'dedicated_order_audit'


def test_database_notification_token_completes_explicit_raw_pair(monkeypatch):
    db_token = '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_database'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': '',
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': 'raw-owner',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': (
                '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local'
            ),
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'local-owner',
        },
    )
    monkeypatch.setattr(
        order_audit, '_notification_settings_bot_token', lambda: db_token,
    )

    token, chat_ids, source = (
        order_audit._telegram_delivery_configuration_details()
    )

    assert token == db_token
    assert chat_ids == ['raw-owner']
    assert source == 'dedicated_order_audit'


@pytest.mark.parametrize(
    ('config', 'expected'),
    [
        (
            {
                # A legacy raw token must not borrow Local Audit recipients.
                'TELEGRAM_BOT_TOKEN': (
                    '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_raw'
                ),
                'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
                'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': '',
                'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'local-owner',
            },
            ('', [], 'unconfigured'),
        ),
        (
            {
                # A Local Audit token must not borrow dedicated raw recipients.
                'TELEGRAM_BOT_TOKEN': '',
                'ORDER_AUDIT_TELEGRAM_CHAT_IDS': 'raw-owner',
                'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': (
                    '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local'
                ),
                'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '',
            },
            ('', [], 'unconfigured'),
        ),
        (
            {
                # An incomplete explicit pair may safely fall back to a
                # complete Local Telegram Audit pair, still without mixing.
                'TELEGRAM_BOT_TOKEN': (
                    '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_raw'
                ),
                'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
                'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': (
                    '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local'
                ),
                'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'local-owner',
            },
            (
                '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local',
                ['local-owner'],
                'local_telegram_audit',
            ),
        ),
    ],
)
def test_raw_delivery_never_mixes_partial_credential_sources(
    monkeypatch, config, expected,
):
    monkeypatch.setattr(order_audit.config_store, 'read_config', lambda: config)
    monkeypatch.setattr(
        order_audit, '_notification_settings_bot_token', lambda: '',
    )

    assert order_audit._telegram_delivery_configuration_details() == expected


def test_delivery_errors_are_per_recipient_and_unchanged_errors_do_not_fsync(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    flushes = []
    monkeypatch.setattr(
        collector, '_flush_index',
        lambda *, force=False: flushes.append(force),
    )
    collector.set_auto_send_error('provider down', chat_id='owner-a')
    collector.set_auto_send_error('provider down', chat_id='owner-a')
    collector.set_auto_send_error('blocked', chat_id='owner-b')
    assert len(flushes) == 2

    collector.mark_delivered('owner-a', 100)
    status = collector.status()
    assert status['delivery_errors'] == {'owner-b': 'blocked'}
    assert 'owner-b: blocked' in status['last_auto_send_error']


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
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '111111111',
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


def test_telegram_http_200_without_bot_api_ack_is_not_delivery(tmp_path, monkeypatch):
    document = tmp_path / 'evidence.jsonl.gz'
    document.write_bytes(b'evidence')

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'ok': False, 'description': 'document rejected'}

    import requests
    monkeypatch.setattr(requests, 'post', lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError, match='document rejected'):
        order_audit._post_telegram_document(
            '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd',
            'owner', document, 'caption',
        )


def test_incremental_export_advances_only_after_explicit_ack(tmp_path):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    collector.capture(_order(pk=1))
    collector.capture(_order(pk=2))

    first, first_meta = collector.prepare_incremental_export('owner', max_bytes=1)
    assert first is not None
    with gzip.open(first, 'rb') as source:
        first_raw = source.read()
    assert first_raw.endswith(b'\n')
    assert json.loads(first_raw)['order']['uuid'] == 'order-1'
    assert collector.delivery_offset('owner') == 0

    collector.mark_delivered('owner', first_meta['end_offset'])
    assert collector.delivery_offset('owner') == first_meta['end_offset']
    second, second_meta = collector.prepare_incremental_export('owner', max_bytes=1)
    assert second is not None
    with gzip.open(second, 'rb') as source:
        second_raw = source.read()
    assert json.loads(second_raw)['order']['uuid'] == 'order-2'
    assert second_meta['start_offset'] == first_meta['end_offset']

    reloaded = order_audit.OrderAuditCollector(
        dataset=collector.dataset, index_file=collector.index_file,
    )
    assert reloaded.delivery_offset('owner') == first_meta['end_offset']


def test_automatic_delivery_failure_retries_same_bytes_then_ack_advances(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    collector.capture(_order())
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    monkeypatch.setattr(
        order_audit, '_telegram_credentials', lambda: ('secret-token', ['owner']),
    )
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {'BRANCH_ID': 'restaurant-1'},
    )
    monkeypatch.setattr(order_audit, '_STOP', threading.Event())

    attempts = []
    def fail_once(_token, _chat_id, path, _caption):
        with gzip.open(path, 'rb') as source:
            attempts.append(source.read())
        raise RuntimeError('provider unavailable')

    monkeypatch.setattr(order_audit, '_post_telegram_document', fail_once)
    assert order_audit._deliver_pending_once() == {
        'sent': 0, 'failed': 1, 'empty': 0,
    }
    assert collector.delivery_offset('owner') == 0

    def succeed(_token, _chat_id, path, _caption):
        with gzip.open(path, 'rb') as source:
            attempts.append(source.read())

    monkeypatch.setattr(order_audit, '_post_telegram_document', succeed)
    assert order_audit._deliver_pending_once() == {
        'sent': 1, 'failed': 0, 'empty': 0,
    }
    assert attempts[0] == attempts[1]
    assert collector.delivery_offset('owner') == collector.dataset.stat().st_size


def test_sync_lifecycle_is_fsynced_and_redacts_credentials_but_preserves_hash(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    order_audit._on_sync_evidence('push_http_attempt', {
        'model_name': 'order',
        'records': [{
            'uuid': 'order-1', 'total_amount': '100000',
            'password': 'never-export-this',
            'nested': {'authorization': 'Branch secret'},
        }],
    })
    row = json.loads(collector.dataset.read_text())
    assert row['capture']['reason'] == 'push_http_attempt'
    copied = row['event']
    assert copied['payload_sha256']
    record = copied['payload']['records'][0]
    assert record['uuid'] == 'order-1'
    assert record['total_amount'] == '100000'
    assert record['password'] == '[REDACTED]'
    assert record['nested']['authorization'] == '[REDACTED]'


def test_local_order_http_request_is_fsynced_before_view_and_response_is_kept(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    request = RequestFactory().post(
        '/orders/create',
        data=json.dumps({
            'items': [{'product_id': 7, 'quantity': 2}],
            'total_amount': '639400',
            'secret_word': 'do-not-export',
        }),
        content_type='application/json',
        HTTP_IDEMPOTENCY_KEY='checkout-action-1',
    )
    request.user = _row(
        is_authenticated=True, pk=4, uuid='cashier-4', role='CASHIER',
        email='cashier@example.test',
    )

    def view(_request):
        first = json.loads(collector.dataset.read_text().splitlines()[0])
        assert first['capture']['reason'] == 'order_http_request_received'
        return JsonResponse({'success': False, 'error': {'message': 'declined'}}, status=409)

    response = order_http_audit.OrderMutationEvidenceMiddleware(view)(request)
    assert response.status_code == 409
    rows = [json.loads(line) for line in collector.dataset.read_text().splitlines()]
    assert len(rows) == 2
    received = rows[0]['event']['payload']
    completed = rows[1]['event']['payload']
    assert received['body']['json']['total_amount'] == '639400'
    assert received['body']['json']['secret_word'] == '[REDACTED]'
    assert received['idempotency_key']['present'] is True
    assert received['idempotency_key']['sha256']
    assert 'checkout-action-1' not in json.dumps(received)
    assert completed['status_code'] == 409
    assert completed['user']['id'] == 4
    assert completed['response']['json']['error']['message'] == 'declined'


def test_local_order_http_audit_records_safe_auth_and_client_resolution(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    cookie_session = 'cookie-session-secret-that-must-never-be-written'
    bearer_session = 'bearer-session-secret-that-must-never-be-written'
    login_password = 'login-password-that-must-never-be-written'
    request = RequestFactory().post(
        '/auth-login?session_key=also-secret&mode=fast',
        data=json.dumps({
            'user_id': 44,
            'password': login_password,
        }),
        content_type='application/json',
        HTTP_COOKIE=f'session_key={cookie_session}',
        HTTP_AUTHORIZATION=f'Bearer {bearer_session}',
        HTTP_USER_AGENT='AlphaPOS-Test-UA/1.0',
        HTTP_X_DEVICE_ID='till-ruxsora-smart',
        REMOTE_ADDR='192.0.2.44',
    )

    def view(_active_request):
        # Simulate the canonical transition guard's token-free conflict reply.
        return JsonResponse(
            {'success': False, 'code': 'session_credential_conflict'},
            status=401,
        )

    response = order_http_audit.OrderMutationEvidenceMiddleware(view)(request)
    assert response.status_code == 401
    raw_dataset = collector.dataset.read_text(encoding='utf-8')
    assert cookie_session not in raw_dataset
    assert bearer_session not in raw_dataset
    assert login_password not in raw_dataset
    assert 'also-secret' not in raw_dataset

    received, completed = [
        json.loads(line)['event']['payload']
        for line in raw_dataset.splitlines()
    ]
    assert received['body']['json']['password'] == '[REDACTED]'
    assert received['query']['parameter_names'] == ['mode', 'session_key']
    assert received['client']['remote_addr'] == '192.0.2.44'
    assert received['client']['user_agent']['value'] == 'AlphaPOS-Test-UA/1.0'
    assert received['client']['x_device_id']['value'] == 'till-ruxsora-smart'
    auth = received['auth_evidence']
    assert auth['cookie']['present'] is True
    assert auth['bearer']['present'] is True
    assert auth['header_scheme'] == 'bearer'
    assert auth['both_present'] is True
    assert auth['credential_conflict'] is True
    assert auth['selected_source'] == 'conflict'
    assert auth['selected_session_fingerprint']['present'] is False
    assert auth['resolved_session_fingerprint']['present'] is False

    resolved = completed['auth_evidence']
    assert resolved['resolved_matches_selected'] is False
    assert resolved['resolved_matches_cookie'] is False
    assert resolved['resolved_matches_bearer'] is False
    assert resolved['resolved_user'] == {'authenticated': False}
    assert completed['user']['authenticated'] is False


def test_local_order_http_audit_resolves_matching_dual_credential_custom_user(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    session = 'same-session-secret-that-must-never-be-written'
    request = RequestFactory().post(
        '/orders/create',
        data=json.dumps({'total_amount': '296000'}),
        content_type='application/json',
        HTTP_COOKIE=f'session_key={session}',
        HTTP_AUTHORIZATION=f'bEaReR {session}',
    )

    def view(active_request):
        # The custom login_required decorator sets a base.User, which has no
        # Django ``is_authenticated`` property, plus the resolved session.
        active_request.user = _row(
            pk=44, uuid='cashier-44', role='CASHIER',
            email='cashier44@example.test',
        )
        active_request.session_key = session
        return JsonResponse({'success': True}, status=201)

    response = order_http_audit.OrderMutationEvidenceMiddleware(view)(request)
    assert response.status_code == 201
    raw_dataset = collector.dataset.read_text(encoding='utf-8')
    assert session not in raw_dataset
    received, completed = [
        json.loads(line)['event']['payload']
        for line in raw_dataset.splitlines()
    ]
    auth = received['auth_evidence']
    assert auth['header_scheme'] == 'bearer'
    assert auth['credential_conflict'] is False
    assert auth['selected_source'] == 'cookie+bearer'
    assert auth['selected_session_fingerprint']['sha256'] == hashlib.sha256(
        session.encode('utf-8'),
    ).hexdigest()

    resolved = completed['auth_evidence']
    assert resolved['resolved_matches_selected'] is True
    assert resolved['resolved_matches_cookie'] is True
    assert resolved['resolved_matches_bearer'] is True
    assert resolved['resolved_user'] == {
        'authenticated': True,
        'email': 'cashier44@example.test',
        'id': 44,
        'role': 'CASHIER',
        'uuid': 'cashier-44',
    }
    assert completed['user']['authenticated'] is True
    assert completed['user']['id'] == 44


def test_custom_user_detection_honours_explicit_anonymous_marker():
    request = RequestFactory().post('/orders/create')
    request.user = _row(
        pk=44, uuid='cashier-44', role='CASHIER', email='cashier@example.test',
        is_authenticated=False,
    )
    assert order_http_audit._user_evidence(request) == {
        'authenticated': False,
    }


def test_auth_evidence_does_not_expose_malformed_header_as_scheme():
    raw_credential = 'MalformedCredentialWithoutSchemeSeparator123456789'
    request = RequestFactory().post(
        '/orders/create',
        HTTP_AUTHORIZATION=raw_credential,
    )
    evidence = order_http_audit._auth_evidence(request)
    assert evidence['header_scheme'] == 'other'
    assert evidence['header']['present'] is True
    assert raw_credential not in json.dumps(evidence)


def test_local_order_http_audit_failure_is_fail_open(monkeypatch, caplog):
    request = RequestFactory().post(
        '/orders/create',
        data={'total_amount': '1000'},
        content_type='application/json',
    )
    view_calls = []

    def denied(*_args, **_kwargs):
        raise PermissionError('audit file ACL denied')

    def view(_request):
        view_calls.append(True)
        return JsonResponse({'success': True}, status=201)

    monkeypatch.setattr(order_audit, 'record_local_event', denied)

    with caplog.at_level('ERROR', logger='desktop.order_http_audit'):
        response = order_http_audit.OrderMutationEvidenceMiddleware(view)(request)

    # Loading Django middleware must not load the optional collector eagerly,
    # and a later storage failure must never turn a valid sale into HTTP 500.
    assert 'order_audit' not in vars(order_http_audit)
    assert response.status_code == 201
    assert view_calls == [True]
    assert caplog.messages.count(
        'local order HTTP evidence write failed (order_http_request_received)',
    ) == 1
    assert caplog.messages.count(
        'local order HTTP evidence write failed (order_http_response_completed)',
    ) == 1


def test_local_http_path_evidence_masks_qr_and_claim_credentials():
    qr_token = (
        'd9428888-122b-41e1-b85c-61b074fc6f39:'
        'AbCdEfGhIjKlMnOpQrStUvWxYz0123456789'
    )
    qr_request = RequestFactory().post(f'/api/qr/order/{qr_token}/')
    qr = order_http_audit._path_evidence(qr_request)
    assert qr['safe_path'] == '/api/qr/order/:opaque/'
    assert qr['sha256']
    assert qr_token not in json.dumps(qr)

    claim = 'd9428888-122b-41e1-b85c-61b074fc6f39'
    claim_request = RequestFactory().post(f'/orders/print-jobs/{claim}/ack')
    claim_evidence = order_http_audit._path_evidence(claim_request)
    assert claim_evidence['safe_path'] == '/orders/print-jobs/:opaque/ack'
    assert claim not in json.dumps(claim_evidence)


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


def test_process_shutdown_latch_blocks_status_triggered_collector_restart(
        monkeypatch):
    starts = []

    class FakeThread:
        def start(self):
            starts.append(True)

    monkeypatch.setattr(order_audit.threading, 'Thread', lambda **_kwargs: FakeThread())
    monkeypatch.setattr(order_audit, '_register_signals', lambda: None)
    monkeypatch.setattr(order_audit, '_STARTED', False)
    monkeypatch.setattr(order_audit, '_THREAD', None)
    monkeypatch.setattr(order_audit, '_SENDER_THREAD', None)

    order_audit.begin_process_shutdown()

    assert order_audit._PROCESS_SHUTDOWN.is_set()
    assert order_audit._STOP.is_set()
    assert order_audit._AUTO_WAKE.is_set()
    assert order_audit.start_background_collector() is False
    assert starts == []


def test_normal_collector_stop_remains_restartable(monkeypatch):
    started = threading.Event()

    def worker():
        started.set()
        order_audit._STOP.wait(5)

    monkeypatch.setattr(order_audit, '_collector_worker', worker)
    monkeypatch.setattr(order_audit, '_auto_sender_worker', worker)
    monkeypatch.setattr(order_audit, '_register_signals', lambda: None)
    monkeypatch.setattr(order_audit, '_STARTED', False)
    monkeypatch.setattr(order_audit, '_THREAD', None)
    monkeypatch.setattr(order_audit, '_SENDER_THREAD', None)
    monkeypatch.setattr(order_audit, '_STOP', threading.Event())

    assert order_audit.start_background_collector() is True
    assert started.wait(1)
    assert order_audit.stop_background_collector(timeout=1) is True
    assert order_audit.start_background_collector() is True
    assert order_audit.stop_background_collector(timeout=1) is True


def test_process_shutdown_latches_optional_workers_before_stop(monkeypatch):
    from desktop import app, local_telegram_audit, support_tunnel

    calls = []
    monkeypatch.setattr(
        order_audit, 'begin_process_shutdown',
        lambda: calls.append('order_latch'),
    )
    monkeypatch.setattr(
        local_telegram_audit, 'begin_process_shutdown',
        lambda: calls.append('telegram_latch'),
    )
    monkeypatch.setattr(
        support_tunnel, 'stop',
        lambda **kwargs: calls.append(('support_stop', kwargs.get('timeout'))),
    )
    monkeypatch.setattr(
        order_audit, 'stop_background_collector',
        lambda **_kwargs: calls.append('order_stop') or True,
    )
    monkeypatch.setattr(
        local_telegram_audit, 'stop_background_notifier',
        lambda **_kwargs: calls.append('telegram_stop') or True,
    )

    app._stop_optional_workers(
        context='test shutdown', support_timeout=5, process_shutdown=True,
    )

    assert calls == [
        'order_latch',
        'telegram_latch',
        ('support_stop', 5),
        'order_stop',
        'telegram_stop',
    ]


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


def test_status_counts_new_telegram_recipient_backlog_from_byte_zero(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    collector.capture(_order())
    size = collector.dataset.stat().st_size
    collector.mark_delivered('existing-owner', size)

    status = collector.status(chat_ids=['existing-owner', 'new-owner'])

    assert status['auto_pending_bytes'] == size


def test_public_status_exposes_delivery_health_but_never_bot_token(
    tmp_path, monkeypatch,
):
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
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': 'owner-a,owner-b',
        },
    )

    class Alive:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(order_audit, '_THREAD', Alive())
    monkeypatch.setattr(order_audit, '_SENDER_THREAD', Alive())

    status = order_audit.get_status()

    assert status['telegram_configured'] is True
    assert status['telegram_chat_count'] == 2
    assert status['telegram_configuration_source'] == 'dedicated_order_audit'
    assert status['delivery_state'] == 'pending'
    assert status['formats'] == ['JSONL', 'JSONL.GZ']
    assert token not in json.dumps(status)


def test_status_ignores_errors_from_replaced_delivery_configuration(
    tmp_path, monkeypatch,
):
    collector = order_audit.OrderAuditCollector(
        dataset=tmp_path / 'orders.raw.jsonl',
        index_file=tmp_path / '.index.json',
    )
    collector.capture(_order())
    collector.set_auto_send_error(
        'Telegram delivery was not configured',
        chat_id='configuration',
    )
    collector.set_auto_send_error('old bot rejected upload', chat_id='old-owner')
    monkeypatch.setattr(order_audit, '_COLLECTOR', collector)
    local_token = '987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_local'
    monkeypatch.setattr(
        order_audit.config_store, 'read_config',
        lambda: {
            'TELEGRAM_BOT_TOKEN': '',
            'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': local_token,
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': 'current-owner',
        },
    )

    class Alive:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(order_audit, '_THREAD', Alive())
    monkeypatch.setattr(order_audit, '_SENDER_THREAD', Alive())

    status = order_audit.get_status()

    assert status['telegram_configured'] is True
    assert status['telegram_configuration_source'] == 'local_telegram_audit'
    assert status['delivery_errors'] == {}
    assert status['last_auto_send_error'] == ''
    assert status['delivery_state'] == 'pending'
    assert local_token not in json.dumps(status)
