"""A cashier's incremental sales report must discover changed order state."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from base.models import Order, Shift
from customers.services.order_service import CustomerOrderService
from waiters.services.order_service import WaiterOrderService


pytestmark = pytest.mark.django_db


def _cached_order(order_factory, cashier_user):
    order = order_factory(user=cashier_user, cashier=cashier_user)
    cached_at = timezone.now() - timedelta(days=2)
    Order.objects.filter(pk=order.pk).update(
        created_at=cached_at, updated_at=cached_at,
    )
    order.refresh_from_db()
    return order, cached_at


def _assert_discoverable(order, cached_at):
    # The installed cashier reporter sorts /orders by -updated_at, then skips
    # details whose timestamp is <= the locally cached timestamp.
    listing, status = CustomerOrderService.get_all_orders(order_by='-updated_at')
    assert status == 200, listing
    row = next(r for r in listing['data']['orders'] if r['id'] == order.id)
    assert parse_datetime(row['updated_at']) > cached_at
    detail, status = CustomerOrderService.get_order_by_id(order.id)
    assert status == 200, detail
    assert detail['data']['order']['updated_at'] == row['updated_at']
    return detail['data']['order']


@pytest.mark.parametrize('discount_percent', [0, 10])
def test_checkout_advances_sales_report_cursor(
    order_factory, cashier_user, discount_percent,
):
    order, cached_at = _cached_order(order_factory, cashier_user)
    Shift.objects.create(
        user=cashier_user, status='ACTIVE', start_time=timezone.now(),
        branch_id=order.branch_id, device_id='pytest-terminal',
    )
    payload = dict(cashier_id=cashier_user.id, payment_method='CASH',
                   discount_percent=discount_percent, payment_action_id=uuid4())
    response, status = CustomerOrderService.mark_as_paid(order.id, **payload)
    assert status == 200, response
    detail = _assert_discoverable(order, cached_at)
    assert detail['is_paid'] is True
    assert Decimal(detail['total_amount']) == Decimal('10') * (
        1 - Decimal(discount_percent) / 100
    )
    order.refresh_from_db()
    settled_update = order.updated_at
    original_paid_at = order.paid_at
    replay, status = CustomerOrderService.mark_as_paid(order.id, **payload)
    assert status == 200, replay
    order.refresh_from_db()
    assert order.updated_at == settled_update
    assert order.paid_at == original_paid_at
    assert order.payments.count() == 1


@pytest.mark.parametrize('actor', ['cashier', 'waiter'])
def test_item_total_change_advances_sales_report_cursor(
    order_factory, cashier_user, product, actor,
):
    order, cached_at = _cached_order(order_factory, cashier_user)
    if actor == 'cashier':
        response, status = CustomerOrderService.add_item_to_order(
            order.id, product.id, 2, cashier_id=cashier_user.id,
            user_id=cashier_user.id, user_role='CASHIER',
        )
    else:
        response, status = WaiterOrderService.add_item(
            order.id, product.id, 2, waiter_user_id=cashier_user.id,
        )
    assert status == 200, response
    detail = _assert_discoverable(order, cached_at)
    assert Decimal(detail['total_amount']) == Decimal(product.price) * 3


def test_rejected_payment_does_not_publish_a_new_sales_state(
    order_factory, cashier_user,
):
    order, cached_at = _cached_order(order_factory, cashier_user)
    response, status = CustomerOrderService.mark_as_paid(
        order.id, cashier_id=cashier_user.id,
        payments=[{'method': 'CASH', 'amount': '1'}],
    )
    assert status == 422, response
    order.refresh_from_db()
    assert order.updated_at == cached_at
    assert order.is_paid is False
    assert not order.payments.exists()
