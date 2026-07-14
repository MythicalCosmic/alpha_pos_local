from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.utils import timezone


pytestmark = pytest.mark.django_db


def _active_shift(cashier):
    from base.models import Shift
    return Shift.objects.create(
        user=cashier,
        start_time=timezone.now(),
        status='ACTIVE',
        branch_id='main',
    )


def _reject_stock(monkeypatch):
    from base.helpers.response import ServiceResponse
    from stock.services import OrderStatusHandler, StockSettingsService

    monkeypatch.setattr(
        StockSettingsService,
        'load',
        classmethod(lambda cls: SimpleNamespace(
            stock_enabled=True,
            auto_deduct_on_sale=True,
            reserve_on_order_create=False,
            deduct_on_order_status='PAID',
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
            'forced stock rejection'
        )),
    )


@override_settings(
    DEPLOYMENT_MODE='local', BRANCH_ID='main', SYNC_ENABLED=False,
)
def test_failed_payment_rolls_back_without_notification_or_fiscalization(
    monkeypatch, order_factory, cashier_user, regular_user,
    django_capture_on_commit_callbacks,
):
    from base.models import CashRegister, OrderPayment
    from customers.services import order_service

    _active_shift(cashier_user)
    order = order_factory(user=regular_user, cashier=cashier_user)
    CashRegister.objects.create(
        current_balance=Decimal('0'), branch_id='main',
    )
    _reject_stock(monkeypatch)
    emitted = []
    monkeypatch.setattr(
        order_service.OrderNotification,
        'on_order_paid',
        lambda order_id: emitted.append(('paid', order_id)),
    )
    monkeypatch.setattr(
        order_service,
        '_fiscalize_after_pay',
        lambda order_id: emitted.append(('fiscal', order_id)),
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        result, status = order_service.CustomerOrderService.mark_as_paid(
            order.id,
            cashier_id=cashier_user.id,
            user_id=cashier_user.id,
            user_role='CASHIER',
            payment_method='CASH',
        )

    assert status == 400, result
    assert callbacks == []
    assert emitted == []
    order.refresh_from_db()
    assert order.is_paid is False
    assert not OrderPayment.objects.filter(order=order).exists()
    assert CashRegister.objects.get(branch_id='main').current_balance == Decimal('0')


@override_settings(
    DEPLOYMENT_MODE='local', BRANCH_ID='main', SYNC_ENABLED=False,
)
def test_failed_customer_status_change_emits_no_ready_notification(
    monkeypatch, order_factory, cashier_user, regular_user,
    django_capture_on_commit_callbacks,
):
    from customers.services import order_service

    order = order_factory(user=regular_user, cashier=cashier_user)
    _reject_stock(monkeypatch)
    emitted = []
    monkeypatch.setattr(
        order_service.OrderNotification,
        'on_order_ready',
        lambda order_id: emitted.append(order_id),
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        result, status = order_service.CustomerOrderService.update_order_status(
            order.id,
            'READY',
            cashier_id=cashier_user.id,
            user_id=cashier_user.id,
            user_role='CASHIER',
        )

    assert status == 400, result
    assert callbacks == []
    assert emitted == []
    order.refresh_from_db()
    assert order.status == 'PREPARING'


@override_settings(
    DEPLOYMENT_MODE='local', BRANCH_ID='main', SYNC_ENABLED=False,
)
def test_failed_waiter_cancel_emits_no_cancel_notification(
    monkeypatch, order_factory, regular_user,
    django_capture_on_commit_callbacks,
):
    from waiters.services import order_service

    order = order_factory(user=regular_user, cashier=regular_user)
    _reject_stock(monkeypatch)
    emitted = []
    monkeypatch.setattr(
        order_service.OrderNotification,
        'on_order_cancelled',
        lambda order_id: emitted.append(order_id),
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        result, status = order_service.WaiterOrderService.cancel_order(
            order.id, regular_user.id,
        )

    assert status == 400, result
    assert callbacks == []
    assert emitted == []
    order.refresh_from_db()
    assert order.status == 'PREPARING'
