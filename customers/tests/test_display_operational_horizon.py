from datetime import timedelta

import pytest
from django.utils import timezone

from customers.services.order_service import CustomerOrderService


pytestmark = pytest.mark.django_db


def test_historical_preparing_rows_cannot_starve_current_kitchen_order(
    regular_user, cashier_user, product, settings,
):
    from base.models import Order, OrderItem

    settings.KITCHEN_QUEUE_MAX_AGE_HOURS = 24

    # More than DISPLAY_LIMIT historical misses reproduce the production
    # failure: the old oldest-first query sliced these before today's order.
    stale = [
        Order(
            user=regular_user, cashier=cashier_user,
            status=Order.Status.PREPARING, is_paid=True,
            payment_method='CASH', paid_at=timezone.now() - timedelta(days=2),
            display_id=i + 1, subtotal='10.00', total_amount='10.00',
            branch_id='branch1',
        )
        for i in range(CustomerOrderService.DISPLAY_LIMIT + 5)
    ]
    Order.objects.bulk_create(stale)
    OrderItem.objects.bulk_create([
        OrderItem(
            order=order, product=product, quantity=1, price='10.00',
            branch_id='branch1',
        )
        for order in stale
    ])
    stale_ids = [order.id for order in stale]
    Order.objects.filter(id__in=stale_ids).update(
        created_at=timezone.now() - timedelta(days=2),
    )

    current = Order.objects.create(
        user=regular_user, cashier=cashier_user,
        status=Order.Status.PREPARING, is_paid=False,
        display_id=999, subtotal='10.00', total_amount='10.00',
        branch_id='branch1',
    )
    OrderItem.objects.create(
        order=current, product=product, quantity=1, price='10.00',
        branch_id='branch1',
    )

    chef, chef_status = CustomerOrderService.get_chef_display_orders()
    client, client_status = CustomerOrderService.get_client_display_orders()

    assert chef_status == client_status == 200
    chef_ids = {row['id'] for row in chef['data']['orders']}
    client_ids = {row['id'] for row in client['data']['processing']}
    assert current.id in chef_ids
    assert current.id in client_ids
    assert chef_ids.isdisjoint(stale_ids)
    assert client_ids.isdisjoint(stale_ids)
