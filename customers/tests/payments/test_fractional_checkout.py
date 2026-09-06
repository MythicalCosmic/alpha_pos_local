"""Checkout must not round a bill differently from the stored sale."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from base.models import CashRegister, Shift
from base.services.tender import order_tender_sources
from customers.services.order_service import CustomerOrderService


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('due', ['10000.25', '10000.75'])
@pytest.mark.parametrize('method', ['CASH', 'UZCARD', 'PAYME'])
def test_existing_fractional_bill_is_preserved_without_new_discount(
    due, method, cashier_user, order_factory,
):
    # Existing menu prices and previously applied percentage discounts both
    # support two decimal places; a zero checkout discount must preserve them.
    due = Decimal(due)
    order = order_factory(cashier=cashier_user)
    order.subtotal = Decimal('12000')
    order.discount_amount = order.subtotal - due
    order.total_amount = due
    order.save(update_fields=['subtotal', 'discount_amount', 'total_amount'])
    Shift.objects.create(
        user=cashier_user, status='ACTIVE', start_time=timezone.now(),
        branch_id=order.branch_id, device_id='pytest-terminal',
    )
    register = CashRegister.objects.create(
        current_balance=0, branch_id=order.branch_id,
    )
    action_id = uuid4()
    payload = {
        'cashier_id': cashier_user.id,
        'payment_method': method,
        'payment_action_id': action_id,
    }
    result, status = CustomerOrderService.mark_as_paid(order.id, **payload)
    assert status == 200, result
    order.refresh_from_db()
    register.refresh_from_db()
    assert order.total_amount == due
    assert order.payments.get().amount == due
    split, _detail, drawer = order_tender_sources(order)
    assert split['unknown'] == 0
    assert sum(split.values()) == due
    assert drawer == register.current_balance == (due if method == 'CASH' else 0)
    retry, retry_status = CustomerOrderService.mark_as_paid(order.id, **payload)
    assert retry_status == 200, retry
    assert retry == result
