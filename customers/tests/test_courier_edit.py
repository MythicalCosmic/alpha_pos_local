"""Courier assignment + staff order-edit on the customer API (local edition)."""
import pytest
from base.models import User, Order, DeliveryPerson
from base.security.hashing import hash_password
from customers.services.order_service import CustomerOrderService

pytestmark = pytest.mark.django_db


def _staff(role='CASHIER'):
    return User.objects.create(email=f'{role.lower()}@t.local', first_name='S', last_name='T',
                               role=role, status='ACTIVE', password=hash_password('x'))


def _order(u, status='PREPARING'):
    return Order.objects.create(user=u, cashier=u, order_type='DELIVERY', status=status,
                                display_id=1, subtotal='10.00', total_amount='10.00')


def _courier(name='Ali', active=True):
    return DeliveryPerson.objects.create(first_name=name, last_name='K',
                                         phone_number=f'+99890{name}', is_active=active)


def test_list_couriers_active_only():
    _courier('Ali', active=True)
    _courier('Bob', active=False)
    body, st = CustomerOrderService.list_couriers()
    assert st == 200
    names = [c['name'] for c in body['data']['items']]
    assert 'Ali K' in names and 'Bob K' not in names


def test_assign_and_clear_courier():
    u = _staff(); o = _order(u); c = _courier()
    _, st = CustomerOrderService.assign_courier(o.id, c.id, user_id=u.id, user_role='CASHIER')
    assert st == 200
    o.refresh_from_db(); assert o.delivery_person_id == c.id
    _, st = CustomerOrderService.assign_courier(o.id, None, user_id=u.id, user_role='CASHIER')
    assert st == 200
    o.refresh_from_db(); assert o.delivery_person_id is None


def test_assign_courier_blocked_on_cancelled():
    u = _staff(); o = _order(u, status='CANCELED'); c = _courier()
    _, st = CustomerOrderService.assign_courier(o.id, c.id, user_id=u.id, user_role='CASHIER')
    assert st == 400


def test_update_details_phone_description_courier():
    u = _staff(); o = _order(u); c = _courier()
    body, st = CustomerOrderService.update_order_details(
        o.id, phone_number='+998901112233', description='leave at door',
        delivery_person_id=c.id, user_id=u.id, user_role='CASHIER')
    assert st == 200
    o.refresh_from_db()
    assert o.phone_number == '+998901112233' and o.description == 'leave at door'
    assert o.delivery_person_id == c.id
    assert body['data']['delivery_person']['id'] == c.id   # serializer carries it


def test_update_details_partial_leaves_courier():
    u = _staff(); o = _order(u); c = _courier()
    CustomerOrderService.assign_courier(o.id, c.id, user_id=u.id, user_role='CASHIER')
    # edit only phone -> courier unchanged (delivery_person_id not passed = _UNSET)
    CustomerOrderService.update_order_details(o.id, phone_number='+111',
                                              user_id=u.id, user_role='CASHIER')
    o.refresh_from_db()
    assert o.delivery_person_id == c.id


def test_waiter_can_edit_own_order_courier():
    """The waiter pay/edit fix: a WAITER may edit an order they own."""
    w = _staff(role='WAITER')
    o = _order(w); c = _courier()
    _, st = CustomerOrderService.assign_courier(o.id, c.id, user_id=w.id, user_role='WAITER')
    assert st == 200
    o.refresh_from_db(); assert o.delivery_person_id == c.id
