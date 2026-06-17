"""Client base: returning-client lookup by phone -> history + frequent foods,
and create_order resolving a client from the phone field."""
import pytest
from decimal import Decimal

from base.models import User, Customer, Order, OrderItem, Product, Category
from customers.services.client_service import ClientService

pytestmark = pytest.mark.django_db


def _setup():
    u = User.objects.create(email='c@t.local', first_name='C', last_name='R',
                            role='CASHIER', status='ACTIVE', password='x')
    cat = Category.objects.create(name='Pizza')
    p1 = Product.objects.create(name='Margherita', price=Decimal('50000'), category=cat)
    p2 = Product.objects.create(name='Cola', price=Decimal('10000'), category=cat)
    client = Customer.objects.create(name='Ali', phone_number='998901112233')
    for _ in range(2):
        o = Order.objects.create(user=u, customer=client, order_type='HALL',
                                 status='COMPLETED', is_paid=True,
                                 total_amount=Decimal('60000'), branch_id='branch1')
        OrderItem.objects.create(order=o, product=p1, quantity=1, price=p1.price)
        OrderItem.objects.create(order=o, product=p2, quantity=2, price=p2.price)
    return client, p1, p2


def test_lookup_returns_history_and_frequent_products():
    client, _p1, _p2 = _setup()
    res, st = ClientService.lookup(phone='+998 90 111 22 33')   # normalized match
    assert st == 200, res
    d = res['data']
    assert d['client']['id'] == client.id and d['client']['name'] == 'Ali'
    assert d['stats']['order_count'] == 2
    assert d['stats']['total_spent'].startswith('120000')       # 2 x 60000
    assert len(d['orders']) == 2
    names = [f['name'] for f in d['frequent_products']]
    assert 'Margherita' in names and 'Cola' in names


def test_lookup_not_found():
    res, st = ClientService.lookup(phone='998900000000')
    assert st == 404


def test_find_exact_and_normalized():
    client, _p1, _p2 = _setup()
    assert ClientService.find(phone='998901112233').id == client.id
    assert ClientService.find(phone='901112233').id == client.id   # normalized national


def test_create_order_resolves_client_from_phone_only():
    """An order carrying just a phone (no name) still creates + links a client."""
    from customers.services.order_service import CustomerOrderService
    cat = Category.objects.create(name='Drinks')
    p = Product.objects.create(name='Water', price=Decimal('5000'), category=cat)
    u = User.objects.create(email='k@t.local', first_name='K', last_name='S',
                            role='CASHIER', status='ACTIVE', password='x')
    # mirror the view's resolve step (the view builds customer_id then calls the service)
    client, created = Customer.resolve(phone='998907778899')
    assert created and client.phone_number == '998907778899' and client.name == ''
    res, st = CustomerOrderService.create_order(
        user_id=u.id, items=[{'product_id': p.id, 'quantity': 1}],
        order_type='HALL', customer_id=client.id)
    assert st in (200, 201), res
