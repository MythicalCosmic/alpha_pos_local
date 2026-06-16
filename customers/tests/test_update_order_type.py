"""POST/PATCH orders/<id>/type — change order type after creation."""
import pytest
from decimal import Decimal
from base.models import User, Order
from base.security.hashing import hash_password
from customers.services.order_service import CustomerOrderService

pytestmark = pytest.mark.django_db


def _admin():
    return User.objects.create(email='t@t.local', first_name='A', last_name='B',
                               role='ADMIN', status='ACTIVE', password=hash_password('x'))


def _order(u, otype='HALL', status='PREPARING'):
    return Order.objects.create(user=u, order_type=otype, status=status,
                                branch_id='branch1', total_amount=Decimal('1000'))


def test_change_type_ok_and_requeues_sync():
    u = _admin(); o = _order(u, 'HALL')
    body, code = CustomerOrderService.update_order_type(o.id, 'DELIVERY',
                                                        user_id=u.id, user_role='ADMIN')
    assert code == 200 and body['success']
    o.refresh_from_db()
    assert o.order_type == 'DELIVERY'
    assert o.synced_at is None  # save() re-queued it for cloud sync


def test_invalid_type_rejected():
    u = _admin(); o = _order(u)
    body, code = CustomerOrderService.update_order_type(o.id, 'TAKEAWAY',
                                                        user_id=u.id, user_role='ADMIN')
    assert code == 422 and not body['success']
    o.refresh_from_db(); assert o.order_type == 'HALL'


def test_cancelled_order_rejected():
    u = _admin(); o = _order(u, 'HALL', status='CANCELED')
    body, code = CustomerOrderService.update_order_type(o.id, 'PICKUP',
                                                        user_id=u.id, user_role='ADMIN')
    assert code == 422 and not body['success']
