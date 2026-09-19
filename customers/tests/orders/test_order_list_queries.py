"""The /orders list loads each page with a fixed number of queries.

The list reads only the columns it shows. A column missing from the
projection still works, but costs one extra query per order; these tests
catch that by listing a small and a large page and comparing query counts,
and check the listed rows against the same order fully loaded.
"""
import itertools

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from base.models import Customer, DeliveryPerson, Order, OrderItem, OrderPayment, Place, Table, User
from base.security.hashing import hash_password
from couriers.models import Courier, DeliveryAssignment
from customers.services.order_service import (
    CustomerOrderService,
    _get_order_by_id_with_courier,
    _serialize_order_list,
)

pytestmark = pytest.mark.django_db

_seq = itertools.count(1)


@pytest.fixture
def world(cashier_user, regular_user, product):
    place = Place.objects.create(name='Main hall')
    rider_user = User.objects.create(
        email='rider@t.local', first_name='Rider', last_name='One', role='COURIER',
        status='ACTIVE', password=hash_password('x'),
    )
    return {
        'cashier': cashier_user,
        'user': regular_user,
        'product': product,
        'place': place,
        'table': Table.objects.create(place=place, number='7'),
        'customer': Customer.objects.create(name='Ali', phone_number='998901112233'),
        'legacy_rider': DeliveryPerson.objects.create(
            first_name='Old', last_name='Rider', phone_number='+998900000001', is_active=True,
        ),
        'courier': Courier.objects.create(
            user=rider_user, code='CR-LIST', phone='+998900000002', branch_id='cloud',
        ),
    }


def _make_order(world, *, delivery):
    n = next(_seq)
    order = Order.objects.create(
        user=world['user'], cashier=world['cashier'], customer=world['customer'],
        order_type='DELIVERY' if delivery else 'HALL', status='PREPARING',
        display_id=n, subtotal='20.00', total_amount='20.00',
        place=None if delivery else world['place'], table=None if delivery else world['table'],
        delivery_person=world['legacy_rider'] if delivery else None,
        phone_number='998901112233' if delivery else None,
    )
    for qty in (1, 2):
        OrderItem.objects.create(order=order, product=world['product'], quantity=qty, price='10.00')
    OrderItem.objects.create(order=order, product=world['product'], quantity=1, price='10.00', is_deleted=True)
    OrderPayment.objects.create(order=order, method='CASH', amount='20.00')
    if delivery:
        DeliveryAssignment.objects.create(
            order=order, courier=world['courier'], step='ON_WAY', fee=5000, assigned_at=timezone.now(),
        )
    return order


def _list_queries(per_page):
    with CaptureQueriesContext(connection) as ctx:
        body, status = CustomerOrderService.get_all_orders(page=1, per_page=per_page)
    assert status == 200
    return body['data']['orders'], len(ctx.captured_queries)


def test_order_list_query_count_does_not_grow_with_the_page(world):
    for i in range(8):
        _make_order(world, delivery=i % 2 == 0)

    small, small_queries = _list_queries(2)
    large, large_queries = _list_queries(8)

    assert len(small) == 2 and len(large) == 8
    assert large_queries == small_queries


def test_order_list_rows_match_the_fully_loaded_order(world):
    orders = [_make_order(world, delivery=True), _make_order(world, delivery=False)]

    listed, _ = _list_queries(20)
    by_id = {row['id']: row for row in listed}

    for order in orders:
        full = _serialize_order_list(_get_order_by_id_with_courier(order.id))
        assert by_id[order.id] == full
    delivery_row = by_id[orders[0].id]
    assert delivery_row['courier_assignment'] is not None
    assert delivery_row['delivery_person']['name'] == 'Old Rider'
    assert [item['quantity'] for item in delivery_row['items']] == [1, 2]
    hall_row = by_id[orders[1].id]
    assert hall_row['place'] == {'id': world['place'].id, 'name': 'Main hall'}
    assert hall_row['table']['number'] == '7'
    assert hall_row['payments'] == [{'method': 'CASH', 'amount': '20.00'}]
    assert hall_row['customer']['name'] == 'Ali'
