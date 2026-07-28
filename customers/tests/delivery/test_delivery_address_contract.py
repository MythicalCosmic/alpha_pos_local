"""Delivery-address API contract tests."""

import json
import secrets
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from base.models import Customer, Order, Session
from base.repositories.session import SessionRepository


pytestmark = pytest.mark.django_db


def _auth(user):
    token = secrets.token_hex(32)
    Session.objects.create(
        user_id=user,
        ip_address='127.0.0.1',
        payload=SessionRepository.hash_token(token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


def _start_shift(user):
    from core.shifts.service import ShiftService

    result, status = ShiftService.start_shift(user.id)
    assert status == 201, result


def test_create_returns_structured_address_and_prefers_order_note(
        cashier_user, product):
    _start_shift(cashier_user)
    client = Client()
    auth = _auth(cashier_user)
    address = 'Tashkent, Amir Temur street 47, apartment 12'
    response = client.post(
        '/orders/create',
        data=json.dumps({
            'items': [{'product_id': product.id, 'quantity': 1}],
            'order_type': 'DELIVERY',
            'phone_number': '+998 (90) 111-22-33',
            'customer': {'name': 'Ali', 'phone': '90 111 22 33'},
            'delivery_address': address,
            'order_note': 'Call on arrival',
            'description': 'legacy address + legacy note',
        }),
        content_type='application/json',
        **auth,
    )
    assert response.status_code == 201, response.content

    order = Order.objects.get(pk=response.json()['data']['order_id'])
    assert order.phone_number == '998901112233'
    assert order.delivery_address == address
    assert order.description == 'Call on arrival'
    assert order.customer.phone_number == '998901112233'
    assert order.customer.name == 'Ali'

    detail = client.get(f'/orders/{order.id}', **auth)
    assert detail.status_code == 200
    assert detail.json()['data']['order']['delivery_address'] == address

    listing = client.get('/orders', **auth)
    listed = next(
        row for row in listing.json()['data']['orders'] if row['id'] == order.id
    )
    assert listed['delivery_address'] == address

    history = client.get('/clients?phone=0901112233', **auth)
    assert history.status_code == 200
    recent = next(
        row for row in history.json()['data']['orders'] if row['id'] == order.id
    )
    assert recent['delivery_address'] == address


def test_patch_supports_delivery_address_and_order_note_alias(
        cashier_user, order_factory):
    client = Client()
    auth = _auth(cashier_user)
    order = order_factory(cashier=cashier_user)

    response = client.patch(
        f'/orders/{order.id}/details',
        data=json.dumps({
            'phone_number': '0 90 555 44 33',
            'delivery_address': 'Chilonzor district, house 9',
            'order_note': 'Use side entrance',
            'description': 'must not win',
        }),
        content_type='application/json',
        **auth,
    )
    assert response.status_code == 200, response.content
    payload = response.json()['data']
    assert payload['phone_number'] == '998905554433'
    assert payload['delivery_address'] == 'Chilonzor district, house 9'
    assert payload['description'] == 'Use side entrance'

    order.refresh_from_db()
    assert order.phone_number == '998905554433'
    assert order.delivery_address == 'Chilonzor district, house 9'
    assert order.description == 'Use side entrance'


def test_phone_variants_reuse_customer_and_backfill_empty_name(
        cashier_user, product):
    _start_shift(cashier_user)
    existing = Customer.objects.create(
        phone_number='90 777 66 55', name='',
    )
    client = Client()
    response = client.post(
        '/orders/create',
        data=json.dumps({
            'items': [{'product_id': product.id, 'quantity': 1}],
            'phone_number': '+998 (90) 777-66-55',
            'customer': {
                'phone': '00998 90 777 66 55',
                'name': 'Backfilled Name',
            },
        }),
        content_type='application/json',
        **_auth(cashier_user),
    )
    assert response.status_code == 201, response.content
    order = Order.objects.get(pk=response.json()['data']['order_id'])
    existing.refresh_from_db()
    assert order.customer_id == existing.id
    assert order.phone_number == '998907776655'
    assert existing.phone_number == '998907776655'
    assert existing.name == 'Backfilled Name'
