"""Local audit reports distinguish an omitted count from a physical shortage."""
from datetime import timedelta

import pytest
from django.utils import timezone

from desktop import local_telegram_audit as audit


pytestmark = pytest.mark.django_db


def _shift_with_cash_row(cashier, *, counted_methods, expected='267000.00'):
    from base.models import Order, OrderPayment, Shift
    from cashbox.models import ShiftPaymentTotal

    end = timezone.now()
    shift = Shift.objects.create(
        user=cashier,
        branch_id='restaurant-1',
        start_time=end - timedelta(hours=1),
        end_time=end,
        status=Shift.Status.ENDED,
        settlement_manifest={
            'version': 3,
            'cashier_counted_methods': counted_methods,
        },
    )
    order = Order.objects.create(
        user=cashier,
        cashier=cashier,
        branch_id=shift.branch_id,
        display_id=Order.objects.count() + 1,
        status=Order.Status.COMPLETED,
        is_paid=True,
        payment_method=Order.PaymentMethod.CASH,
        subtotal=expected,
        total_amount=expected,
        paid_at=shift.start_time + timedelta(minutes=30),
    )
    OrderPayment.objects.create(
        order=order,
        method=Order.PaymentMethod.CASH,
        amount=expected,
    )
    ShiftPaymentTotal.objects.create(
        shift=shift,
        branch_id=shift.branch_id,
        method='CASH',
        expected_amount=expected,
        counted_amount='0.00',
        confirmed_amount='0.00',
        difference=f'-{expected}',
    )
    return shift


def test_local_report_labels_missing_count_without_shortage(
    tmp_path, cashier_user,
):
    shift = _shift_with_cash_row(cashier_user, counted_methods=[])

    path, metadata = audit.build_shift_report(
        shift.pk,
        report_format='TXT',
        output_dir=tmp_path,
    )
    text = path.read_text(encoding='utf-8')

    assert (
        'CASH | status UNCOUNTED | cashier count UNCOUNTED | '
        'expected 267,000.00 UZS | counted NOT SUBMITTED | '
        'difference NOT APPLICABLE'
    ) in text
    assert '| difference -267,000.00 UZS' not in text
    assert 'manager confirmed NOT YET' in text
    assert 'frozen difference -267,000.00 UZS' in text
    assert metadata['settlements_total'] == 1
    assert metadata['settlements_written'] == 1


def test_local_report_preserves_explicit_zero_count(
    tmp_path, cashier_user,
):
    shift = _shift_with_cash_row(cashier_user, counted_methods=['CASH'])

    path, _ = audit.build_shift_report(
        shift.pk,
        report_format='TXT',
        output_dir=tmp_path,
    )
    text = path.read_text(encoding='utf-8')

    assert (
        'CASH | expected 267,000.00 UZS | counted 0.00 UZS | '
        'difference -267,000.00 UZS | status COUNTED | '
        'cashier count COUNTED'
    ) in text
    assert 'manager confirmed NOT YET' in text


def test_local_report_uses_canonical_cash_not_customer_change(
    tmp_path, cashier_user,
):
    from base.models import OrderPayment
    from cashbox.models import ShiftPaymentTotal

    shift = _shift_with_cash_row(
        cashier_user,
        counted_methods=['CASH'],
        expected='100.00',
    )
    OrderPayment.objects.update(amount='120.00')
    ShiftPaymentTotal.objects.update(
        expected_amount='120.00',
        counted_amount='100.00',
        difference='-20.00',
    )

    path, _ = audit.build_shift_report(
        shift.pk,
        report_format='TXT',
        output_dir=tmp_path,
    )
    text = path.read_text(encoding='utf-8')

    assert (
        'CASH | expected 100.00 UZS | counted 100.00 UZS | '
        'difference 0.00 UZS | status COUNTED | cashier count COUNTED'
    ) in text
    assert 'expected source CANONICAL_DERIVED' in text
    assert 'frozen expected 120.00 UZS' in text
    assert '| difference -20.00 UZS' not in text
    assert 'frozen difference -20.00 UZS' in text


def test_local_report_never_formats_unavailable_evidence_as_zero(
    tmp_path, cashier_user,
):
    from base.models import Order, Shift
    from cashbox.models import ShiftPaymentTotal

    end = timezone.now()
    shift = Shift.objects.create(
        user=cashier_user,
        branch_id='restaurant-1',
        start_time=end - timedelta(hours=1),
        end_time=end,
        status=Shift.Status.ENDED,
        settlement_manifest={
            'version': 3,
            'cashier_counted_methods': ['CASH'],
        },
    )
    Order.objects.create(
        user=cashier_user,
        cashier=cashier_user,
        branch_id=shift.branch_id,
        display_id=Order.objects.count() + 1,
        status=Order.Status.COMPLETED,
        is_paid=True,
        payment_method=Order.PaymentMethod.MIXED,
        subtotal='100.00',
        total_amount='100.00',
        paid_at=shift.start_time + timedelta(minutes=30),
    )
    ShiftPaymentTotal.objects.create(
        shift=shift,
        branch_id=shift.branch_id,
        method='CASH',
        expected_amount='100.00',
        counted_amount='100.00',
        confirmed_amount='0.00',
        difference='0.00',
    )

    path, _ = audit.build_shift_report(
        shift.pk,
        report_format='TXT',
        output_dir=tmp_path,
    )
    text = path.read_text(encoding='utf-8')

    assert 'CASH | expected UNAVAILABLE | counted 100.00 UZS | difference UNAVAILABLE' in text
    assert 'expected source ATTRIBUTION_INCOMPLETE' in text
    assert 'frozen expected 100.00 UZS' in text
