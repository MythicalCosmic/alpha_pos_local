"""Cashier order creation and shift close share one serialization boundary."""
import threading

import pytest
from django.db import close_old_connections, connection


pytestmark = pytest.mark.django_db(transaction=True)
requires_row_locks = pytest.mark.skipif(
    not connection.features.has_select_for_update,
    reason='the ordering assertion requires PostgreSQL SELECT FOR UPDATE',
)


def _start_shift(cashier):
    from base.models import Shift
    from core.shifts.service import ShiftService

    result, status = ShiftService.start_shift(cashier.id)
    assert status == 201, result
    return Shift.objects.get(pk=result['data']['id'])


def _thread(target, output, done):
    """Give each worker a clean thread-local DB connection and capture errors."""
    close_old_connections()
    try:
        output.append(target())
    except BaseException as exc:  # surfaced by the parent test with full repr
        output.append(exc)
    finally:
        close_old_connections()
        done.set()


def _assert_result(output):
    assert len(output) == 1
    if isinstance(output[0], BaseException):
        raise output[0]
    return output[0]


@requires_row_locks
def test_create_that_locks_shift_first_is_seen_and_blocks_close(
    cashier_user, product, monkeypatch,
):
    """Create wins the Shift lock: close must wait, then see the unpaid cart."""
    from base.models import Order, Shift
    from base.services import order_refund
    from core.shifts.service import ShiftService
    from customers.services.order_service import CustomerOrderService

    shift = _start_shift(cashier_user)
    create_has_shift = threading.Event()
    release_create = threading.Event()
    original_lock = order_refund.lock_active_cashier_shift

    def paused_lock(*args, **kwargs):
        locked = original_lock(*args, **kwargs)
        create_has_shift.set()
        assert release_create.wait(5), 'test did not release the create worker'
        return locked

    monkeypatch.setattr(order_refund, 'lock_active_cashier_shift', paused_lock)

    create_result, close_result = [], []
    create_done, close_done = threading.Event(), threading.Event()
    create_thread = threading.Thread(
        target=_thread,
        args=(lambda: CustomerOrderService.create_order(
            user_id=cashier_user.id,
            cashier_id=cashier_user.id,
            items=[{'product_id': product.id, 'quantity': 1}],
        ), create_result, create_done),
    )
    close_thread = threading.Thread(
        target=_thread,
        args=(lambda: ShiftService.end_shift(
            shift.id, cashier_user.id, '', actor=cashier_user,
        ), close_result, close_done),
    )

    create_thread.start()
    assert create_has_shift.wait(5), 'create never acquired the active Shift'
    close_thread.start()
    try:
        assert not close_done.wait(0.2), 'close bypassed the create Shift lock'
    finally:
        release_create.set()
    create_thread.join(5)
    close_thread.join(5)
    assert create_done.is_set() and close_done.is_set()

    created, create_status = _assert_result(create_result)
    closed, close_status = _assert_result(close_result)
    assert create_status == 201, created
    assert close_status == 400, closed
    assert 'unpaid' in closed['message'].lower()
    assert Order.objects.filter(cashier=cashier_user, is_paid=False).count() == 1
    assert Shift.objects.get(pk=shift.pk).status == Shift.Status.ACTIVE


@requires_row_locks
def test_close_that_locks_shift_first_rejects_late_cashier_create(
    cashier_user, product, monkeypatch,
):
    """Close wins the Shift lock: the late staff create must not orphan a cart."""
    from base.models import Order, Shift
    from base.repositories import ShiftRepository
    from core.shifts.service import ShiftService
    from customers.services.order_service import CustomerOrderService

    shift = _start_shift(cashier_user)
    close_has_shift = threading.Event()
    release_close = threading.Event()
    original_get = ShiftRepository.get_with_relations
    paused_once = threading.Event()

    def paused_get(cls, pk):
        value = original_get(pk)
        if pk == shift.id and not paused_once.is_set():
            paused_once.set()
            close_has_shift.set()
            assert release_close.wait(5), 'test did not release the close worker'
        return value

    monkeypatch.setattr(
        ShiftRepository, 'get_with_relations', classmethod(paused_get),
    )

    close_result, create_result = [], []
    close_done, create_done = threading.Event(), threading.Event()
    close_thread = threading.Thread(
        target=_thread,
        args=(lambda: ShiftService.end_shift(
            shift.id, cashier_user.id, '', actor=cashier_user,
        ), close_result, close_done),
    )
    create_thread = threading.Thread(
        target=_thread,
        args=(lambda: CustomerOrderService.create_order(
            user_id=cashier_user.id,
            cashier_id=cashier_user.id,
            items=[{'product_id': product.id, 'quantity': 1}],
        ), create_result, create_done),
    )

    close_thread.start()
    assert close_has_shift.wait(5), 'close never acquired the Shift row'
    create_thread.start()
    try:
        assert not create_done.wait(0.2), 'create bypassed the close Shift lock'
    finally:
        release_close.set()
    close_thread.join(5)
    create_thread.join(5)
    assert close_done.is_set() and create_done.is_set()

    closed, close_status = _assert_result(close_result)
    created, create_status = _assert_result(create_result)
    assert close_status == 200, closed
    assert create_status == 400, created
    assert 'active shift' in created['message'].lower()
    assert not Order.objects.filter(cashier=cashier_user).exists()
    assert Shift.objects.get(pk=shift.pk).status == Shift.Status.ENDED


def test_cashier_create_requires_an_active_shift(cashier_user, product):
    from base.models import Order
    from customers.services.order_service import CustomerOrderService

    result, status = CustomerOrderService.create_order(
        user_id=cashier_user.id,
        cashier_id=cashier_user.id,
        items=[{'product_id': product.id, 'quantity': 1}],
    )

    assert status == 400, result
    assert 'active shift' in result['message'].lower()
    assert not Order.objects.filter(cashier=cashier_user).exists()


def test_active_shift_create_is_visible_to_close_guard(cashier_user, product):
    from base.models import Shift
    from core.shifts.service import ShiftService
    from customers.services.order_service import CustomerOrderService

    shift = _start_shift(cashier_user)
    created, create_status = CustomerOrderService.create_order(
        user_id=cashier_user.id,
        cashier_id=cashier_user.id,
        items=[{'product_id': product.id, 'quantity': 1}],
    )
    closed, close_status = ShiftService.end_shift(
        shift.id, cashier_user.id, '', actor=cashier_user,
    )

    assert create_status == 201, created
    assert close_status == 400, closed
    assert 'unpaid' in closed['message'].lower()
    assert Shift.objects.get(pk=shift.pk).status == Shift.Status.ACTIVE


def test_cashierless_remote_order_still_does_not_require_a_shift(
    regular_user, product,
):
    from customers.services.order_service import CustomerOrderService

    result, status = CustomerOrderService.create_order(
        user_id=regular_user.id,
        cashier_id=None,
        items=[{'product_id': product.id, 'quantity': 1}],
    )

    assert status == 201, result
