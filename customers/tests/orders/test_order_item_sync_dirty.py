"""Order-item synchronization dirtiness tests."""

import pytest
from types import SimpleNamespace
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


def test_cashier_mark_ready_marks_every_line_unsynced(
    order_factory, cashier_user,
):
    from customers.services.order_service import CustomerOrderService

    order = order_factory(user=cashier_user, cashier=cashier_user)
    item = order.items.get()
    _mark_synced(item)
    previous_version = item.sync_version

    result, status = CustomerOrderService.mark_order_ready(
        order.id, cashier_id=cashier_user.id,
        user_id=cashier_user.id, user_role='CASHIER',
    )

    assert status == 200, result
    item.refresh_from_db()
    assert item.ready_at is not None
    assert item.sync_version == previous_version + 1
    assert item.synced_at is None


def test_cashier_unmark_ready_marks_line_unsynced(
    order_factory, cashier_user,
):
    from customers.services.order_service import CustomerOrderService

    order = order_factory(user=cashier_user, cashier=cashier_user)
    item = order.items.get()
    item.ready_at = timezone.now()
    item.save(update_fields=['ready_at'])
    _mark_synced(item)
    previous_version = item.sync_version

    result, status = CustomerOrderService.unmark_item_ready(
        order.id, item.id, cashier_id=cashier_user.id,
        user_id=cashier_user.id, user_role='CASHIER',
    )

    assert status == 200, result
    item.refresh_from_db()
    assert item.ready_at is None
    assert item.sync_version == previous_version + 1
    assert item.synced_at is None


def test_waiter_mark_ready_marks_every_line_unsynced(
    order_factory, regular_user,
):
    from waiters.services.order_service import WaiterOrderService

    order = order_factory(user=regular_user, cashier=regular_user)
    item = order.items.get()
    _mark_synced(item)
    previous_version = item.sync_version

    result, status = WaiterOrderService.mark_ready(order.id, regular_user.id)

    assert status == 200, result
    item.refresh_from_db()
    assert item.ready_at is not None
    assert item.sync_version == previous_version + 1
    assert item.synced_at is None


def test_soft_deleted_line_does_not_block_order_becoming_ready(
    order_factory, cashier_user,
):
    from customers.services.order_service import CustomerOrderService

    order = order_factory(
        user=cashier_user, cashier=cashier_user, items=2,
    )
    removed, live = list(order.items.order_by('id'))
    removed.delete()

    result, status = CustomerOrderService.mark_item_ready(
        order.id, live.id, cashier_id=cashier_user.id,
        user_id=cashier_user.id, user_role='CASHIER',
    )

    assert status == 200, result
    order.refresh_from_db()
    assert order.status == 'READY'
    assert result['data']['order']['all_items_ready'] is True


def test_removing_discounted_line_recalculates_discount_from_live_items(
    order_factory, cashier_user,
):
    from decimal import Decimal
    from customers.services.order_service import CustomerOrderService
    from discounts.models import Discount, DiscountType, OrderDiscount

    order = order_factory(
        user=cashier_user, cashier=cashier_user, items=2,
    )
    removed, _live = list(order.items.order_by('id'))
    order.subtotal = Decimal('20')
    order.discount_amount = Decimal('10')
    order.total_amount = Decimal('10')
    order.save(update_fields=['subtotal', 'discount_amount', 'total_amount'])
    discount_type = DiscountType.objects.create(
        name='Half', code='half',
        discount_method=DiscountType.Method.PERCENTAGE,
    )
    discount = Discount.objects.create(
        discount_type=discount_type, name='Half off', code='HALF',
        value=Decimal('50'),
    )
    OrderDiscount.objects.create(
        order=order, discount=discount, discount_code=discount.code,
        discount_amount=Decimal('10'),
    )

    result, status = CustomerOrderService.remove_item_from_order(
        order.id, removed.id, cashier_id=cashier_user.id,
        user_id=cashier_user.id, user_role='CASHIER',
    )

    assert status == 200, result
    order.refresh_from_db()
    assert order.subtotal == Decimal('10')
    assert order.discount_amount == Decimal('5')
    assert order.total_amount == Decimal('5')


def test_stock_rejection_rolls_back_cashier_order_item_edit(
    monkeypatch, order_factory, cashier_user,
):
    from base.helpers.response import ServiceResponse
    from customers.services.order_service import CustomerOrderService
    from stock.services import OrderStockService, StockSettingsService

    order = order_factory(user=cashier_user, cashier=cashier_user)
    item = order.items.get()
    order.refresh_from_db()
    original_quantity = item.quantity
    original_subtotal = order.subtotal
    original_total = order.total_amount

    monkeypatch.setattr(
        StockSettingsService,
        'get_default_location_id',
        classmethod(lambda cls: 1),
    )
    monkeypatch.setattr(
        OrderStockService,
        'adjust_for_item_change',
        classmethod(lambda cls, *args, **kwargs: ServiceResponse.error(
            'forced stock rejection'
        )),
    )

    result, status = CustomerOrderService.update_order_item(
        order.id, item.id, original_quantity + 2,
        cashier_id=cashier_user.id,
        user_id=cashier_user.id,
        user_role='CASHIER',
    )

    assert status == 400, result
    item.refresh_from_db()
    order.refresh_from_db()
    assert item.quantity == original_quantity
    assert order.subtotal == original_subtotal
    assert order.total_amount == original_total


def test_stock_rejection_rolls_back_waiter_order_item_edit(
    monkeypatch, order_factory, regular_user,
):
    from base.helpers.response import ServiceResponse
    from stock.services import OrderStockService, StockSettingsService
    from waiters.services.order_service import WaiterOrderService

    order = order_factory(user=regular_user, cashier=regular_user)
    item = order.items.get()
    order.refresh_from_db()
    original_quantity = item.quantity
    original_total = order.total_amount

    monkeypatch.setattr(
        StockSettingsService,
        'get_default_location_id',
        classmethod(lambda cls: 1),
    )
    monkeypatch.setattr(
        OrderStockService,
        'adjust_for_item_change',
        classmethod(lambda cls, *args, **kwargs: ServiceResponse.error(
            'forced stock rejection'
        )),
    )

    result, status = WaiterOrderService.update_item(
        order.id, item.id, original_quantity + 2, regular_user.id,
    )

    assert status == 400, result
    item.refresh_from_db()
    order.refresh_from_db()
    assert item.quantity == original_quantity
    assert order.total_amount == original_total


def test_stock_failure_rolls_back_new_cashier_order(
    monkeypatch, cashier_user, product,
):
    from base.helpers.response import ServiceResponse
    from base.models import Order
    from core.shifts.service import ShiftService
    from customers.services.order_service import CustomerOrderService
    from stock.services import OrderStatusHandler, StockSettingsService

    shift_result, shift_status = ShiftService.start_shift(cashier_user.id)
    assert shift_status == 201, shift_result

    monkeypatch.setattr(
        StockSettingsService,
        'load',
        classmethod(lambda cls: SimpleNamespace(
            stock_enabled=True,
            reserve_on_order_create=False,
            deduct_on_order_status='PREPARING',
        )),
    )
    monkeypatch.setattr(
        StockSettingsService,
        'get_default_location_id',
        classmethod(lambda cls: 1),
    )
    monkeypatch.setattr(
        OrderStatusHandler,
        'on_status_change',
        classmethod(lambda cls, *args, **kwargs: ServiceResponse.error(
            'forced deduction failure'
        )),
    )
    before = Order.objects.count()

    result, status = CustomerOrderService.create_order(
        user_id=cashier_user.id,
        cashier_id=cashier_user.id,
        items=[{'product_id': product.id, 'quantity': 1}],
    )

    assert status == 400, result
    assert Order.objects.count() == before
