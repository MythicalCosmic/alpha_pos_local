import pytest
from django.utils import timezone


pytestmark = pytest.mark.django_db


def _mark_synced(item):
    type(item).objects.filter(pk=item.pk).update(synced_at=timezone.now())
    item.refresh_from_db()


def test_cashier_increment_marks_existing_line_unsynced(
    order_factory, product, cashier_user,
):
    from customers.services.order_service import CustomerOrderService

    order = order_factory(user=cashier_user, cashier=cashier_user)
    item = order.items.get()
    _mark_synced(item)
    previous_version = item.sync_version

    result, status = CustomerOrderService.add_item_to_order(
        order.id, product.id, 2, cashier_id=cashier_user.id,
        user_id=cashier_user.id, user_role='CASHIER',
    )

    assert status == 200, result
    item.refresh_from_db()
    assert item.quantity == 3
    assert item.sync_version == previous_version + 1
    assert item.synced_at is None


def test_waiter_increment_marks_existing_line_unsynced(
    order_factory, product, regular_user,
):
    from waiters.services.order_service import WaiterOrderService

    order = order_factory(user=regular_user, cashier=regular_user)
    item = order.items.get()
    _mark_synced(item)
    previous_version = item.sync_version

    result, status = WaiterOrderService.add_item(
        order.id, product.id, 2, waiter_user_id=regular_user.id,
    )

    assert status == 200, result
    item.refresh_from_db()
    assert item.quantity == 3
    assert item.sync_version == previous_version + 1
    assert item.synced_at is None
