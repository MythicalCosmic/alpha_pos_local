"""Local Telegram audit delivery tests."""

import os
import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from desktop import bridge, config_store, local_telegram_audit as audit


FAKE_BOT_TOKEN = '123456789:TEST_ONLY_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ'


class TelegramAck:
    status_code = 200

    @staticmethod
    def json():
        return {'ok': True, 'result': {'message_id': 1}}


def _config(**overrides):
    values = {
        'enabled': True,
        'order_recorded': True,
        'order_paid': True,
        'shift_reports': True,
        'report_format': 'TXT',
        'token': FAKE_BOT_TOKEN,
        'chat_ids': ('-1001234567890',),
    }
    values.update(overrides)
    return audit.AuditConfig(**values)


@pytest.fixture
def isolated_outbox(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, 'AUDIT_DIR', tmp_path / 'local_telegram_audit')
    monkeypatch.setattr(
        audit,
        'OUTBOX_PATH',
        tmp_path / 'local_telegram_audit' / 'outbox.sqlite3',
    )
    return audit.OUTBOX_PATH


def _rows(path):
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in connection.execute(
                'SELECT * FROM deliveries ORDER BY event_key, chat_id',
            ).fetchall()
        ]
    finally:
        connection.close()


def test_outbox_repairs_private_acl_before_first_sqlite_open(
        monkeypatch, isolated_outbox):
    reports = isolated_outbox.parent / 'reports'
    reports.mkdir(parents=True)
    existing_report = reports / 'alpha-pos-shift-existing.txt'
    existing_report.write_text('private order total\n', encoding='utf-8')
    events = []
    real_connect = sqlite3.connect
    native_path_type = type(isolated_outbox)

    def guarded_connect(path, *args, **kwargs):
        events.append(('connect', native_path_type(path)))
        return real_connect(path, *args, **kwargs)

    config_store._HARDENED_WINDOWS_PATHS.clear()
    monkeypatch.setattr(config_store.os, 'name', 'nt')
    monkeypatch.setattr(config_store, 'Path', native_path_type)
    monkeypatch.setattr(config_store.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(
        config_store, '_current_windows_sid', lambda: 'S-1-5-21-1234',
    )
    monkeypatch.setattr(
        config_store, '_windows_executable', lambda name: name,
    )
    monkeypatch.setattr(
        config_store,
        '_hidden_windows_command',
        lambda command: events.append(
            ('acl', native_path_type(command[1]), command[-1]),
        ) or SimpleNamespace(returncode=0, stdout='processed', stderr=''),
    )
    monkeypatch.setattr(audit.sqlite3, 'connect', guarded_connect)

    try:
        connection = audit._connect()
        connection.close()
        # _connect is intentionally allowed to call the helper every time:
        # its process cache prevents repeat icacls work while new SQLite files
        # safely inherit from the already-private parent directory.
        connection = audit._connect()
        connection.close()
    finally:
        config_store._HARDENED_WINDOWS_PATHS.clear()

    assert events == [
        ('acl', isolated_outbox.parent, '*S-1-5-21-1234:(OI)(CI)F'),
        ('acl', reports, '*S-1-5-21-1234:(OI)(CI)F'),
        ('acl', existing_report, '*S-1-5-21-1234:F'),
        ('connect', isolated_outbox),
        ('connect', isolated_outbox),
    ]
    assert existing_report.read_text(encoding='utf-8') == (
        'private order total\n'
    )


def test_dedicated_token_is_secret_masked_and_not_in_config_repr(monkeypatch):
    assert 'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN' in config_store.SECRET_KEYS
    monkeypatch.setattr(
        config_store,
        'read_config',
        lambda: {
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': FAKE_BOT_TOKEN,
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': (
                '-1001234567890, -1001234567890 @owner_channel'
            ),
        },
    )

    parsed = audit.load_config()
    assert parsed.chat_ids == ('-1001234567890', '@owner_channel')
    assert FAKE_BOT_TOKEN not in repr(parsed)

    result = bridge.Api().get_config()
    assert result['ok'] is True
    assert result['config']['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'] == audit.MASK
    assert result['config']['LOCAL_TELEGRAM_AUDIT_CHAT_IDS'].startswith('-100')


def test_order_message_has_cost_discount_total_exact_time_shift_and_no_products():
    paid_at = timezone.now().replace(microsecond=0)
    cashier = SimpleNamespace(
        first_name='Madina', last_name='Cashier', email='cashier@example.test',
    )
    order = SimpleNamespace(
        pk=7,
        uuid='order-uuid-7',
        order_number=742,
        display_id=42,
        subtotal=Decimal('110000.00'),
        discount_amount=Decimal('10000.00'),
        total_amount=Decimal('100000.00'),
        payment_method='MIXED',
        paid_at=paid_at,
        cashier=cashier,
        branch_id='restaurant-1',
    )
    shift = SimpleNamespace(
        pk=3, uuid='shift-uuid-3',
        start_time=paid_at - timedelta(hours=2),
    )

    message = audit.format_order_message(order, shift)

    assert 'Order reference / name: <b>#742</b>' in message
    assert 'Cost / subtotal: 110,000.00 UZS' in message
    assert 'Discount: 10,000.00 UZS' in message
    assert 'Final total: <b>100,000.00 UZS</b>' in message
    assert audit._format_datetime(paid_at) in message
    assert 'shift-uuid-3' in message
    assert 'Lavash' not in message
    assert 'product' not in message.lower()


def test_direct_test_sends_to_every_chat_only_via_telegram(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return TelegramAck()

    monkeypatch.setattr(
        audit,
        'load_config',
        lambda: _config(chat_ids=('-1001111111111', '@owner_channel')),
    )
    import requests
    monkeypatch.setattr(requests, 'post', fake_post)

    result = audit.send_test_message()

    assert result == {
        'ok': True,
        'partial': False,
        'sent': ['-1001111111111', '@owner_channel'],
        'failed': [],
    }
    assert len(calls) == 2
    assert all(
        url == f'https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage'
        for url, _kwargs in calls
    )
    assert all('cloud' not in url and '78.111.' not in url for url, _ in calls)


def test_outbox_deduplicates_and_redacts_transport_failure(
    monkeypatch,
    isolated_outbox,
):
    monkeypatch.setattr(audit, 'load_config', lambda: _config())
    assert audit._insert_delivery(
        event_key='order-paid:stable-action',
        chat_id='-1001234567890',
        kind='order_paid',
        object_pk=9,
        payload={'message': 'safe order message'},
    ) is True
    assert audit._insert_delivery(
        event_key='order-paid:stable-action',
        chat_id='-1001234567890',
        kind='order_paid',
        object_pk=9,
        payload={'message': 'duplicate'},
    ) is False

    monkeypatch.setattr(
        audit,
        '_post_message',
        lambda token, chat_id, text: (_ for _ in ()).throw(
            RuntimeError(f'failed URL bot{token}/sendMessage'),
        ),
    )
    result = audit.deliver_pending_once()
    rows = _rows(isolated_outbox)

    assert result['failed'] == 1
    assert len(rows) == 1
    assert rows[0]['state'] == 'failed'
    assert FAKE_BOT_TOKEN not in rows[0]['last_error']
    assert '[redacted-token]' in rows[0]['last_error']


@pytest.mark.django_db(transaction=True)
def test_order_callbacks_run_only_after_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(audit, 'load_config', lambda: _config())
    monkeypatch.setattr(
        audit,
        'enqueue_recorded_order',
        lambda pk: calls.append(('recorded', pk)),
    )
    monkeypatch.setattr(
        audit,
        'enqueue_order',
        lambda pk: calls.append(('paid', pk)),
    )
    instance = SimpleNamespace(
        pk=91, is_deleted=False, is_paid=True, paid_at=timezone.now(),
    )

    with transaction.atomic():
        audit._on_order_saved(None, instance)
        transaction.set_rollback(True)
    assert calls == []

    with transaction.atomic():
        audit._on_order_saved(None, instance)
        assert calls == []
    assert calls == [('recorded', 91), ('paid', 91)]


@pytest.mark.django_db
def test_recorded_delivery_waits_for_order_batch_and_exports_no_product(
    monkeypatch,
    isolated_outbox,
    order_factory,
):
    monkeypatch.setattr(audit, 'load_config', lambda: _config(order_paid=False))
    monkeypatch.setattr(audit, 'RECORDED_ORDER_SETTLE_SECONDS', 0)
    audit._reset_enable_watermark(timezone.now() - timedelta(minutes=1))
    order = order_factory()
    captured = []

    def fake_post(token, chat_id, text):
        captured.append(text)

    monkeypatch.setattr(audit, '_post_message', fake_post)

    assert audit.enqueue_recorded_order(order.pk) == 1
    assert audit.deliver_pending_once()['sent'] == 1
    assert len(captured) == 1
    assert 'Order recorded locally' in captured[0]
    assert '10.00 UZS' in captured[0]
    assert 'Test Product' not in captured[0]
    assert 'product' not in captured[0].lower()


@pytest.mark.django_db
def test_reconciliation_repairs_crash_gap_without_pre_enable_or_off_interval_flood(
    monkeypatch,
    isolated_outbox,
    order_factory,
):
    monkeypatch.setattr(audit, 'load_config', lambda: _config(shift_reports=False))
    monkeypatch.setattr(audit, 'RECONCILE_SETTLE_SECONDS', 0)
    now = timezone.now().replace(microsecond=0)
    first_enable = now - timedelta(minutes=10)

    old = order_factory(is_paid=True)
    old_paid = first_enable - timedelta(minutes=1)
    old_action = uuid4()
    type(old).objects.filter(pk=old.pk).update(
        created_at=old_paid,
        paid_at=old_paid,
        payment_action_id=old_action,
        payment_method='CASH',
    )

    audit._reset_enable_watermark(first_enable)
    committed = order_factory(is_paid=True)
    committed_created = first_enable + timedelta(seconds=10)
    committed_paid = first_enable + timedelta(seconds=20)
    committed_action = uuid4()
    type(committed).objects.filter(pk=committed.pk).update(
        created_at=committed_created,
        paid_at=committed_paid,
        payment_action_id=committed_action,
        payment_method='CASH',
    )

    result = audit.reconcile_committed_events(now=now)
    keys = [row['event_key'] for row in _rows(isolated_outbox)]
    assert result['orders']['recorded']['inserted'] == 1
    assert result['orders']['paid']['inserted'] == 1
    assert any(str(committed.uuid) in key for key in keys)
    assert all(str(old.uuid) not in key for key in keys)

    # A pending row that existed before OFF is retained, while a sale created
    # during the OFF interval is below the fresh re-enable watermark.
    assert audit._insert_delivery(
        event_key='pre-disable-pending',
        chat_id='-1001234567890',
        kind='order_paid',
        object_pk=committed.pk,
        payload={'message': 'already queued'},
    )
    off_order = order_factory(is_paid=True)
    off_time = now + timedelta(seconds=5)
    type(off_order).objects.filter(pk=off_order.pk).update(
        created_at=off_time,
        paid_at=off_time,
        payment_action_id=uuid4(),
        payment_method='CASH',
    )
    reenabled_at = now + timedelta(seconds=10)
    audit._reset_enable_watermark(reenabled_at)
    audit.reconcile_committed_events(now=reenabled_at + timedelta(minutes=1))
    after = _rows(isolated_outbox)
    after_keys = [row['event_key'] for row in after]
    assert 'pre-disable-pending' in after_keys
    assert all(str(off_order.uuid) not in key for key in after_keys)


def test_per_kind_reenable_resets_only_cursors_and_keeps_pending_outbox(
    isolated_outbox,
):
    current = dict(config_store.CONFIG_FIELDS)
    current.update({
        'LOCAL_TELEGRAM_AUDIT_ENABLED': 'True',
        'LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED': 'False',
        'LOCAL_TELEGRAM_ORDER_PAID_ENABLED': 'False',
        'LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED': 'False',
    })
    assert audit._insert_delivery(
        event_key='pending-before-kind-disable',
        chat_id='-1001234567890',
        kind='order_paid',
        object_pk=88,
        payload={'message': 'preserve me'},
    )
    moment = timezone.now().replace(microsecond=0)

    clean = audit.prepare_configuration_update(
        {
            'order_recorded': True,
            'order_paid': True,
            'shift_reports': True,
        },
        current=current,
        moment=moment,
    )

    assert clean == {
        'LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED': 'True',
        'LOCAL_TELEGRAM_ORDER_PAID_ENABLED': 'True',
        'LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED': 'True',
    }
    expected = moment.astimezone(audit.dt_timezone.utc).isoformat()
    for kind in ('recorded', 'paid', 'shift'):
        assert audit._meta_get(f'{kind}_cursor_time') == expected
        assert audit._meta_get(f'{kind}_cursor_pk') == '0'
    rows = _rows(isolated_outbox)
    assert len(rows) == 1
    assert rows[0]['event_key'] == 'pending-before-kind-disable'
    assert rows[0]['state'] == 'pending'


def test_worker_cycle_recovers_after_unexpected_exception(monkeypatch):
    calls = []

    def flaky_config():
        calls.append('load')
        if len(calls) == 1:
            raise OSError('temporary local disk error')
        audit._STOP.set()
        return _config(enabled=False)

    monkeypatch.setattr(audit, 'load_config', flaky_config)
    monkeypatch.setattr(audit, 'POLL_SECONDS', 0)
    monkeypatch.setattr(audit, 'WORKER_RECOVERY_INITIAL_SECONDS', 0)
    monkeypatch.setattr(audit, 'WORKER_RECOVERY_MAX_SECONDS', 0)
    audit._STOP.clear()
    audit._WAKE.clear()
    try:
        audit._worker()
    finally:
        audit._STOP.clear()
        audit._WAKE.clear()

    assert calls == ['load', 'load']


def test_process_shutdown_latch_blocks_late_notifier_restart(monkeypatch):
    starts = []
    monkeypatch.setattr(audit, '_PROCESS_SHUTDOWN', audit.threading.Event())
    monkeypatch.setattr(audit, '_STOP', audit.threading.Event())
    monkeypatch.setattr(audit, '_WAKE', audit.threading.Event())
    monkeypatch.setattr(audit, '_STARTED', False)
    monkeypatch.setattr(audit, '_THREAD', None)
    monkeypatch.setattr(
        audit, '_register_signals', lambda: starts.append('signals'),
    )
    monkeypatch.setattr(
        audit, 'cleanup_stale_reports', lambda: starts.append('cleanup'),
    )
    monkeypatch.setattr(
        audit, '_reset_inflight', lambda: starts.append('inflight'),
    )

    audit.begin_process_shutdown()

    assert audit._PROCESS_SHUTDOWN.is_set()
    assert audit._STOP.is_set()
    assert audit._WAKE.is_set()
    assert audit.start_background_notifier() is False
    assert starts == []
    assert audit._THREAD is None
    assert audit._STARTED is False


def test_ordinary_notifier_stop_remains_restartable(monkeypatch):
    monkeypatch.setattr(audit, '_PROCESS_SHUTDOWN', audit.threading.Event())
    monkeypatch.setattr(audit, '_STOP', audit.threading.Event())
    monkeypatch.setattr(audit, '_WAKE', audit.threading.Event())
    monkeypatch.setattr(audit, '_STARTED', False)
    monkeypatch.setattr(audit, '_THREAD', None)
    monkeypatch.setattr(audit, '_register_signals', lambda: None)
    monkeypatch.setattr(audit, '_unregister_signals', lambda: None)
    monkeypatch.setattr(audit, 'cleanup_stale_reports', lambda: 0)
    monkeypatch.setattr(audit, '_reset_inflight', lambda: None)
    monkeypatch.setattr(audit, 'load_config', lambda: _config(enabled=False))

    try:
        assert audit.start_background_notifier() is True
        first = audit._THREAD
        assert first is not None and first.is_alive()
        assert audit.stop_background_notifier(timeout=1) is True
        assert audit._PROCESS_SHUTDOWN.is_set() is False

        assert audit.start_background_notifier() is True
        second = audit._THREAD
        assert second is not None and second is not first and second.is_alive()
    finally:
        audit.stop_background_notifier(timeout=1)


def _create_paid_order(
    *,
    user,
    branch,
    amount,
    method,
    created_at,
    paid_at,
    product,
):
    from base.models import Order, OrderItem, OrderPayment

    action = uuid4()
    order = Order.objects.create(
        user=user,
        cashier=user,
        branch_id=branch,
        order_type=Order.OrderType.HALL,
        status=Order.Status.COMPLETED,
        is_paid=True,
        payment_action_id=action,
        payment_method=method,
        paid_at=paid_at,
        accounting_recorded_at=paid_at,
        subtotal=amount,
        discount_amount=Decimal('0'),
        total_amount=amount,
    )
    Order.objects.filter(pk=order.pk).update(created_at=created_at)
    OrderItem.objects.create(
        order=order, product=product, quantity=1, price=amount,
    )
    OrderPayment.objects.create(
        order=order,
        method=method,
        amount=amount,
        payment_action_id=action,
        line_index=0,
    )
    order.refresh_from_db()
    return order


@pytest.mark.django_db
def test_shift_close_report_uses_half_open_canonical_money_and_explicit_differences(
    tmp_path,
    monkeypatch,
    cashier_user,
    product,
):
    from base.models import OrderRefund, Shift
    from cashbox.models import (
        CashboxExpense,
        CashboxExpenseCategory,
        ShiftPaymentTotal,
    )

    start = timezone.now().replace(microsecond=0) - timedelta(hours=2)
    end = start + timedelta(hours=1)
    shift = Shift.objects.create(
        user=cashier_user,
        branch_id='restaurant-1',
        start_time=start,
        end_time=end,
        status=Shift.Status.ENDED,
        total_orders=2,
        total_revenue=Decimal('145.00'),
        cash_collected=Decimal('95.00'),
    )
    cash_order = _create_paid_order(
        user=cashier_user,
        branch='restaurant-1',
        amount=Decimal('100.00'),
        method='CASH',
        created_at=start + timedelta(minutes=5),
        paid_at=start + timedelta(minutes=10),
        product=product,
    )
    card_order = _create_paid_order(
        user=cashier_user,
        branch='restaurant-1',
        amount=Decimal('50.00'),
        method='CARD',
        created_at=start + timedelta(minutes=15),
        paid_at=start + timedelta(minutes=20),
        product=product,
    )
    boundary = _create_paid_order(
        user=cashier_user,
        branch='restaurant-1',
        amount=Decimal('999.00'),
        method='CASH',
        created_at=end,
        paid_at=end,
        product=product,
    )
    refund = OrderRefund.objects.create(
        order=cash_order,
        shift=shift,
        cashier=cashier_user,
        branch_id='restaurant-1',
        amount=Decimal('10.00'),
        cash_amount=Decimal('10.00'),
        drawer_cash_amount=Decimal('10.00'),
        card_amount=Decimal('0'),
        payme_amount=Decimal('0'),
        unknown_amount=Decimal('0'),
        card_detail={},
        refunded_at=start + timedelta(minutes=30),
        source=OrderRefund.Source.ORDER_CANCEL,
        source_id='test-refund-1',
        reason='Customer cancellation before handoff',
    )
    expense_category = CashboxExpenseCategory.objects.create(name='Supplies')
    expense = CashboxExpense.objects.create(
        shift=shift,
        category=expense_category,
        amount=Decimal('15.00'),
        comment='Emergency till supplies',
        recipient_user=cashier_user,
        created_by=cashier_user,
        branch_id='restaurant-1',
    )
    ShiftPaymentTotal.objects.create(
        shift=shift,
        method='CASH',
        expected_amount=Decimal('75.00'),
        counted_amount=Decimal('74.00'),
        difference=Decimal('-1.00'),
        confirmed_amount=Decimal('75.00'),
        branch_id='restaurant-1',
    )
    ShiftPaymentTotal.objects.create(
        shift=shift,
        method='CARD',
        expected_amount=Decimal('50.00'),
        counted_amount=Decimal('50.00'),
        difference=Decimal('0.00'),
        confirmed_amount=Decimal('50.00'),
        branch_id='restaurant-1',
    )

    path, metadata = audit.build_shift_report(
        shift.pk,
        report_format='TXT',
        output_dir=tmp_path,
    )
    text = path.read_text(encoding='utf-8')

    assert metadata['orders_total'] == 2
    assert metadata['paid_orders'] == 2
    assert str(cash_order.uuid) in text
    assert str(card_order.uuid) in text
    assert str(boundary.uuid) not in text
    assert 'CASH: gross 100.00 UZS | refund 10.00 UZS | net 90.00 UZS' in text
    assert 'CARD: gross 50.00 UZS | refund 0.00 UZS | net 50.00 UZS' in text
    assert 'RECOMPUTED NET REVENUE: 140.00 UZS' in text
    assert 'FROZEN MINUS RECOMPUTED REVENUE: 5.00 UZS' in text
    assert 'RECOMPUTED DRAWER CASH: 90.00 UZS' in text
    assert 'FROZEN MINUS RECOMPUTED DRAWER CASH: 5.00 UZS' in text
    assert 'CASHBOX EXPENSES TOTAL: 15.00 UZS' in text
    assert 'RECOMPUTED DRAWER AFTER EXPENSES: 75.00 UZS' in text
    assert str(refund.uuid) in text
    refund_order_number = (
        cash_order.order_number
        if cash_order.order_number is not None
        else cash_order.display_id
    )
    assert f'order #{refund_order_number} / {cash_order.uuid}' in text
    assert audit._format_datetime(refund.refunded_at) in text
    assert 'source ORDER_CANCEL / test-refund-1' in text
    assert (
        'total 10.00 UZS | cash 10.00 UZS | drawer cash 10.00 UZS'
    ) in text
    assert 'Customer cancellation before handoff' in text
    assert (
        'CASH | expected 75.00 UZS | counted 74.00 UZS | '
        'difference -1.00 UZS | status COUNTED | cashier count COUNTED'
    ) in text
    assert 'manager confirmed NOT YET' in text
    assert str(expense.uuid) in text
    assert 'amount 15.00 UZS' in text
    assert 'category Supplies' in text
    assert 'Emergency till supplies' in text
    assert metadata['expenses_total'] == 1
    assert metadata['expenses_written'] == 1
    assert metadata['expense_amount'] == '15.00'
    assert metadata['settlements_total'] == 2
    assert metadata['settlements_written'] == 2
    assert metadata['refunds_total'] == 1
    assert metadata['refunds_written'] == 1
    assert metadata['refund_amount'] == '10.00'
    assert audit._format_datetime(start) in text
    assert 'Test Product' not in text
    assert path.stat().st_size <= audit.REPORT_MAX_BYTES
    path.unlink()

    CashboxExpense.objects.create(
        shift=shift,
        category=expense_category,
        amount=Decimal('2.00'),
        comment='Second bounded expense',
        created_by=cashier_user,
        branch_id='restaurant-1',
    )
    later_refund = OrderRefund.objects.create(
        order=card_order,
        shift=shift,
        cashier=cashier_user,
        branch_id='restaurant-1',
        amount=Decimal('5.00'),
        cash_amount=Decimal('0'),
        drawer_cash_amount=Decimal('0'),
        card_amount=Decimal('5.00'),
        payme_amount=Decimal('0'),
        unknown_amount=Decimal('0'),
        card_detail={'CARD': '5.00'},
        refunded_at=start + timedelta(minutes=40),
        source=OrderRefund.Source.ORDER_CANCEL,
        source_id='test-refund-2',
        reason='Later card correction',
    )
    monkeypatch.setattr(audit, 'REPORT_MAX_EXPENSES', 1)
    monkeypatch.setattr(audit, 'REPORT_MAX_REFUNDS', 1)
    bounded_path, bounded = audit.build_shift_report(
        shift.pk,
        report_format='TXT',
        output_dir=tmp_path,
    )
    assert bounded['expenses_total'] == 2
    assert bounded['expenses_written'] == 1
    assert bounded['expense_amount'] == '17.00'
    assert bounded['refunds_total'] == 2
    assert bounded['refunds_written'] == 1
    assert bounded['refund_amount'] == '15.00'
    assert bounded['truncated'] is True
    bounded_text = bounded_path.read_text(encoding='utf-8')
    assert str(refund.uuid) in bounded_text
    assert str(later_refund.uuid) not in bounded_text
    assert bounded_path.stat().st_size <= audit.REPORT_MAX_BYTES
    bounded_path.unlink()

    monkeypatch.setattr(
        audit,
        '_report_line_for_order',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError('forced report rendering failure'),
        ),
    )
    with pytest.raises(RuntimeError, match='forced report rendering failure'):
        audit.build_shift_report(
            shift.pk,
            report_format='TXT',
            output_dir=tmp_path,
        )
    assert not list(tmp_path.glob('alpha-pos-shift-*.txt'))


def test_startup_cleanup_removes_old_and_bounds_recent_plaintext_reports(
    monkeypatch,
    tmp_path,
):
    audit_dir = tmp_path / 'local_telegram_audit'
    reports = audit_dir / 'reports'
    reports.mkdir(parents=True)
    monkeypatch.setattr(audit, 'AUDIT_DIR', audit_dir)
    monkeypatch.setattr(audit, 'REPORT_STALE_SECONDS', 100)
    monkeypatch.setattr(audit, 'REPORT_MAX_STALE_FILES', 3)
    now = 10_000.0
    old = reports / 'alpha-pos-shift-1-old.txt'
    old.write_text('old private report', encoding='utf-8')
    os.utime(old, (now - 101, now - 101))
    for index in range(5):
        path = reports / f'alpha-pos-shift-{index + 2}-recent.md'
        path.write_text('recent private report', encoding='utf-8')
        os.utime(path, (now - index, now - index))
    unrelated = reports / 'operator-note.txt'
    unrelated.write_text('not owned by notifier cleanup', encoding='utf-8')

    removed = audit.cleanup_stale_reports(now=now)

    generated = list(reports.glob('alpha-pos-shift-*'))
    assert removed == 3
    assert not old.exists()
    assert len(generated) == 3
    assert unrelated.exists()


def test_shift_document_http_is_direct_utf8_attachment(monkeypatch, tmp_path):
    report = tmp_path / 'shift-audit.md'
    report.write_text('# Shift\nBuyurtma №42\n', encoding='utf-8')
    captured = {}

    def fake_post(url, **kwargs):
        captured['url'] = url
        captured['data'] = kwargs['data']
        name, handle, mime = kwargs['files']['document']
        captured['name'] = name
        captured['mime'] = mime
        captured['bytes'] = handle.read()
        return TelegramAck()

    import requests
    monkeypatch.setattr(requests, 'post', fake_post)
    audit._post_document(
        FAKE_BOT_TOKEN,
        '-1001234567890',
        report,
        caption='Shift close',
        report_format='MD',
    )

    assert captured['url'].endswith(f'bot{FAKE_BOT_TOKEN}/sendDocument')
    assert captured['mime'] == 'text/markdown'
    assert captured['bytes'].decode('utf-8').splitlines()[-1] == 'Buyurtma №42'


def test_local_audit_polling_cannot_overwrite_dirty_form_source():
    source = Path('desktop/ui/app/screens-admin.jsx').read_text(encoding='utf-8')
    status_update = source.index('setStatus(r);', source.index('function LocalTelegramAuditScreen'))
    hydration_guard = source.index(
        'if (hydrated.current && !forceHydrate) return;',
        status_update,
    )
    form_update = source.index('setForm((old)', hydration_guard)
    assert status_update < hydration_guard < form_update
    assert 'setDirty(true);' in source
    assert 'applyStatus(r, true)' in source
