from datetime import datetime
from uuid import uuid4

import pytest
from django.utils import timezone

from desktop.local_sales_report import _active_shift_rows, build_local_sales_report


def _at(value):
    return timezone.make_aware(
        datetime.fromisoformat(value),
        timezone.get_current_timezone(),
    )


def _paid_order(
    *,
    user,
    cashier,
    amount,
    created_at,
    paid_at,
    method='CASH',
    deleted=False,
    branch_id=None,
):
    from base.models import Order

    order = Order.objects.create(
        user=user,
        cashier=cashier,
        display_id=Order.objects.count() + 1,
        order_type='HALL',
        status='COMPLETED',
        is_paid=True,
        payment_method=method,
        subtotal=amount,
        total_amount=amount,
        paid_at=paid_at,
        is_deleted=deleted,
        **({'branch_id': branch_id} if branch_id else {}),
    )
    Order.objects.filter(pk=order.pk).update(
        created_at=created_at,
        paid_at=paid_at,
    )
    order.refresh_from_db()
    return order


def test_bridge_feature_flag_disables_only_the_compatibility_view(monkeypatch):
    from desktop.bridge import Api

    monkeypatch.setenv('LEGACY_COMPAT_DASHBOARD_ENABLED', 'false')
    api = Api()
    monkeypatch.setattr(
        api.server,
        'ensure_django',
        lambda: (_ for _ in ()).throw(AssertionError('must stay read-only/off')),
    )

    assert api.legacy_sales_report() == {
        'ok': True,
        'enabled': False,
        'report': None,
    }


@pytest.mark.django_db
def test_business_day_boundaries_and_paid_event_clock(
    settings,
    regular_user,
    cashier_user,
):
    settings.BRANCH_ID = 'main'
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='10',
        created_at=_at('2026-07-10T06:59:00'),
        paid_at=_at('2026-07-10T06:59:00'),
    )
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='20',
        created_at=_at('2026-07-10T07:00:00'),
        paid_at=_at('2026-07-10T07:00:00'),
    )
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='30',
        created_at=_at('2026-07-11T02:59:59'),
        paid_at=_at('2026-07-11T02:59:59'),
    )
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='40',
        created_at=_at('2026-07-11T03:00:00'),
        paid_at=_at('2026-07-11T03:00:00'),
    )
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='50',
        created_at=_at('2026-07-09T20:00:00'),
        paid_at=_at('2026-07-10T12:00:00'),
    )
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='999',
        created_at=_at('2026-07-10T13:00:00'),
        paid_at=_at('2026-07-10T13:00:00'),
        deleted=True,
    )

    report = build_local_sales_report('2026-07-10', '2026-07-10')

    assert report['range']['start_at'].startswith('2026-07-10T07:00:00')
    assert report['range']['end_at'].startswith('2026-07-11T03:00:00')
    assert report['summary']['gross_revenue'] == '100'
    assert report['summary']['net_revenue'] == '100'
    assert report['summary']['paid_orders'] == 3
    assert report['summary']['orders'] == 2
    assert report['payment_breakdown']['cash'] == '100'
    assert report['data_quality']['sales_clock'] == 'paid_at'


@pytest.mark.django_db
def test_mixed_tenders_refunds_expenses_and_active_drawer_reconcile(
    settings,
    regular_user,
    cashier_user,
):
    from base.models import OrderPayment, OrderRefund, Shift
    from cashbox.models import CashboxExpense, CashboxExpenseCategory

    settings.BRANCH_ID = 'main'
    start = _at('2026-07-10T07:00:00')
    shift = Shift.objects.create(
        user=cashier_user,
        start_time=start,
        status='ACTIVE',
        branch_id='main',
    )
    action_id = uuid4()
    order = _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='100',
        created_at=_at('2026-07-10T09:50:00'),
        paid_at=_at('2026-07-10T10:00:00'),
        method='MIXED',
    )
    order.payment_action_id = action_id
    order.save(update_fields=['payment_action_id'])
    OrderPayment.objects.create(
        order=order,
        method='CASH',
        amount='60',
        payment_action_id=action_id,
        line_index=0,
        branch_id='main',
    )
    OrderPayment.objects.create(
        order=order,
        method='HUMO',
        amount='40',
        payment_action_id=action_id,
        line_index=1,
        branch_id='main',
    )
    OrderRefund.objects.create(
        order=order,
        shift=shift,
        cashier=cashier_user,
        amount='20',
        cash_amount='20',
        drawer_cash_amount='20',
        card_amount='0',
        payme_amount='0',
        unknown_amount='0',
        refunded_at=_at('2026-07-10T11:00:00'),
        source='ORDER_CANCEL',
        source_id='test-refund-1',
        branch_id='main',
    )
    category = CashboxExpenseCategory.objects.create(
        name='Supplies',
        branch_id='main',
    )
    expense = CashboxExpense.objects.create(
        shift=shift,
        category=category,
        amount='10',
        comment='Napkins',
        branch_id='main',
    )
    CashboxExpense.objects.filter(pk=expense.pk).update(
        created_at=_at('2026-07-10T12:00:00'),
    )

    report = build_local_sales_report('2026-07-10', '2026-07-10')

    assert report['summary'] == {
        'net_revenue': '80',
        'gross_revenue': '100',
        'refund_amount': '20',
        'orders': 1,
        'paid_orders': 1,
        'refunded_orders': 1,
        'cancelled_orders': 0,
        'open_orders': 0,
        'average_paid_order': '80',
        'units_sold': 0,
        'cashbox_expenses': '10',
    }
    assert report['payment_breakdown']['cash'] == '40'
    assert report['payment_breakdown']['card'] == '40'
    assert report['payment_breakdown']['card_detail']['HUMO'] == '40'

    cashier = report['cashiers'][0]
    assert cashier['drawer_events'] == {
        'cash_sales': '60',
        'cash_refunds': '20',
        'cashbox_expenses': '10',
        'net_movement': '30',
    }
    assert report['expenses'][0]['comment'] == 'Napkins'
    assert report['active_drawers']['complete'] is True
    assert report['active_drawers']['expected_cash_total'] == '30'
    assert report['active_drawers']['shifts'][0]['expected_cash'] == '30.00'


@pytest.mark.django_db
def test_exact_datetime_range_is_continuous_through_quiet_hours(
    settings,
    regular_user,
    cashier_user,
):
    settings.BRANCH_ID = 'main'
    for timestamp, amount in (
        ('2026-07-10T09:59:59', '10'),
        ('2026-07-10T10:00:00', '20'),
        ('2026-07-11T04:00:00', '30'),
        ('2026-07-11T21:59:59', '40'),
        ('2026-07-11T22:00:00', '50'),
    ):
        moment = _at(timestamp)
        _paid_order(
            user=regular_user,
            cashier=cashier_user,
            amount=amount,
            created_at=moment,
            paid_at=moment,
        )

    report = build_local_sales_report(
        from_at='2026-07-10T10:00:00+05:00',
        to_at='2026-07-11T22:00:00+05:00',
    )

    assert report['range']['mode'] == 'custom'
    assert report['summary']['gross_revenue'] == '90'
    assert report['summary']['paid_orders'] == 3
    assert report['daily'] == []


def test_active_drawer_never_presents_incomplete_evidence_as_zero(monkeypatch):
    from core.shifts.service import ShiftService

    monkeypatch.setattr(
        ShiftService,
        'get_active_shifts',
        lambda actor=None: ({
            'success': True,
            'data': [{
                'id': 17,
                'user': {'name': 'Cashier'},
                'expected_cash': '0.00',
                'financial_evidence_available': False,
                'cash_to_receive_complete': False,
                'tender_attribution_complete': False,
            }],
        }, 200),
    )

    drawers = _active_shift_rows()

    assert drawers['complete'] is False
    assert drawers['expected_cash_total'] is None
    assert drawers['shifts'][0]['expected_cash'] is None
    assert drawers['shifts'][0]['cash_evidence_complete'] is False


@pytest.mark.parametrize(
    ('expected_cash', 'evidence'),
    [
        ('0.00', {'cash_to_receive_complete': True}),
        (
            'NaN',
            {
                'financial_evidence_available': True,
                'cash_to_receive_complete': True,
            },
        ),
        (
            'not-money',
            {
                'financial_evidence_available': True,
                'cash_to_receive_complete': True,
            },
        ),
    ],
)
def test_active_drawer_rejects_missing_or_malformed_proof(
    monkeypatch,
    expected_cash,
    evidence,
):
    from core.shifts.service import ShiftService

    monkeypatch.setattr(
        ShiftService,
        'get_active_shifts',
        lambda actor=None: ({
            'success': True,
            'data': [{
                'id': 18,
                'user': {'name': 'Cashier'},
                'expected_cash': expected_cash,
                **evidence,
            }],
        }, 200),
    )

    drawers = _active_shift_rows()

    assert drawers['complete'] is False
    assert drawers['expected_cash_total'] is None
    assert drawers['shifts'][0]['expected_cash'] is None


def test_no_active_shift_is_not_presented_as_verified_zero(monkeypatch):
    from core.shifts.service import ShiftService

    monkeypatch.setattr(
        ShiftService,
        'get_active_shifts',
        lambda actor=None: ({'success': True, 'data': []}, 200),
    )

    drawers = _active_shift_rows()

    assert drawers['available'] is True
    assert drawers['complete'] is False
    assert drawers['expected_cash_total'] is None
    assert drawers['shifts'] == []


def test_malformed_active_shift_payload_fails_closed(monkeypatch):
    from core.shifts.service import ShiftService

    monkeypatch.setattr(
        ShiftService,
        'get_active_shifts',
        lambda actor=None: ({'success': True, 'data': {'id': 1}}, 200),
    )

    drawers = _active_shift_rows()

    assert drawers['available'] is False
    assert drawers['complete'] is False
    assert drawers['expected_cash_total'] is None
    assert drawers['shifts'] == []


@pytest.mark.django_db
def test_offsetting_unknown_sale_and_refund_still_fail_attribution(
    settings,
    regular_user,
    cashier_user,
):
    from base.models import OrderRefund

    settings.BRANCH_ID = 'main'
    moment = _at('2026-07-10T10:00:00')
    order = _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='100',
        created_at=moment,
        paid_at=moment,
        method='MIXED',
    )
    OrderRefund.objects.create(
        order=order,
        amount='100',
        unknown_amount='100',
        refunded_at=_at('2026-07-10T11:00:00'),
        source=OrderRefund.Source.COURIER_PAYMENT,
        source_id='offsetting-unknown-refund',
        branch_id='main',
    )

    report = build_local_sales_report('2026-07-10', '2026-07-10')

    quality = report['data_quality']
    assert report['payment_breakdown'].get('unknown', '0') == '0'
    assert quality['tender_attribution_complete'] is False
    assert quality['unknown_sale_amount'] == '100'
    assert quality['unknown_refund_amount'] == '100'


@pytest.mark.django_db
def test_local_report_excludes_foreign_branch_sales(
    settings,
    regular_user,
    cashier_user,
):
    settings.BRANCH_ID = 'main'
    moment = _at('2026-07-10T10:00:00')
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='75',
        created_at=moment,
        paid_at=moment,
        branch_id='main',
    )
    _paid_order(
        user=regular_user,
        cashier=cashier_user,
        amount='900',
        created_at=moment,
        paid_at=moment,
        branch_id='foreign-branch',
    )

    report = build_local_sales_report('2026-07-10', '2026-07-10')

    assert report['summary']['gross_revenue'] == '75'
    assert report['summary']['paid_orders'] == 1
    assert report['data_quality']['branch_id'] == 'main'
