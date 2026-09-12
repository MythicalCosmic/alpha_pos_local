import json
import re
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.staticfiles import finders
from django.test import Client
from django.utils import timezone

from base.models import AuditLog, Order, Session, User
from base.repositories import SessionRepository
from base.services.waiter_settings import update_policy
from waiters.services.order_service import WaiterOrderService

pytestmark = pytest.mark.django_db


@pytest.fixture
def waiter_user():
    update_policy({'waiter_enabled': True})
    return User.objects.create(
        email='webapp-waiter@test.local',
        role='WAITER',
        permissions=['order.create', 'order.update', 'order.cancel', 'discount.apply'],
    )


def authenticated_client(user):
    token = uuid4().hex
    Session.objects.create(
        user_id=user,
        payload=SessionRepository.hash_token(token),
        expires_at=timezone.now() + timedelta(days=1),
        user_agent='waiter-webapp-test',
    )
    return Client(
        HTTP_AUTHORIZATION=f'Bearer {token}',
        HTTP_USER_AGENT='waiter-webapp-test',
    )


def test_waiter_shell_and_deep_links_are_served(client):
    root = client.get('/waiter/')
    deep_link = client.get('/waiter/orders/42')

    assert root.status_code == 200
    assert deep_link.status_code == 200
    assert b'<div id="app"></div>' in root.content
    assert root['Cache-Control'] == 'no-store'

    referenced_assets = set(re.findall(
        rb'(?:src|href)="(/static/waiter/[^"?]+)',
        root.content,
    ))
    assert referenced_assets
    assert all(
        finders.find(asset.decode().removeprefix('/static/'))
        for asset in referenced_assets
    )


def test_waiter_service_worker_has_page_scope(client):
    response = client.get('/waiter/sw.js')

    assert response.status_code == 200
    assert response['Service-Worker-Allowed'] == '/waiter/'
    assert response['Cache-Control'] == 'no-cache'


def test_waiter_delivery_forwards_the_address(waiter_user, product):
    result, status = WaiterOrderService.create_order(
        user_id=waiter_user.id,
        items=[{'product_id': product.id, 'quantity': 1}],
        order_type='DELIVERY',
        phone_number='+998901234567',
        delivery_address='Tashkent, Amir Temur street 12',
    )

    assert status == 201, result
    order = Order.objects.get(pk=result['data']['order_id'])
    assert order.delivery_address == 'Tashkent, Amir Temur street 12'


def test_waiter_order_detail_includes_applied_discount(waiter_user, product):
    from discounts.models import Discount, DiscountType
    from discounts.services import DiscountService

    result, status = WaiterOrderService.create_order(
        user_id=waiter_user.id,
        items=[{'product_id': product.id, 'quantity': 1}],
        order_type='PICKUP',
    )
    assert status == 201, result
    order_id = result['data']['order_id']
    discount_type = DiscountType.objects.create(
        name='Web percentage',
        code='WEB-PERCENT',
        discount_method='PERCENTAGE',
    )
    discount = Discount.objects.create(
        name='Waiter web discount',
        code='WEB10',
        discount_type=discount_type,
        value=10,
    )

    applied, status = DiscountService.apply_to_order(
        order_id,
        discount.code,
        waiter_user.id,
    )
    assert status == 200, applied

    detail, status = WaiterOrderService.get_order(order_id, waiter_user.id)
    assert status == 200
    payload = detail['data']['order']
    assert payload['subtotal'] != payload['total_amount']
    assert payload['discount_amount'] == applied['data']['discount_amount']
    assert payload['discounts'] == [{
        'id': applied['data']['order_discount_id'],
        'code': 'WEB10',
        'name': 'Waiter web discount',
        'amount': applied['data']['discount_amount'],
    }]


def test_waiter_cancel_keeps_submitted_reason_in_audit(waiter_user, product):
    result, status = WaiterOrderService.create_order(
        user_id=waiter_user.id,
        items=[{'product_id': product.id, 'quantity': 1}],
        order_type='PICKUP',
    )
    assert status == 201, result
    order_id = result['data']['order_id']

    response = authenticated_client(waiter_user).post(
        f'/api/waiters/orders/{order_id}/cancel',
        data=json.dumps({'reason': 'Guest changed the order'}),
        content_type='application/json',
        HTTP_IDEMPOTENCY_KEY='waiter-cancel-reason',
    )

    assert response.status_code == 200, response.content
    event = AuditLog.objects.get(
        action=AuditLog.Action.ORDER_CANCEL,
        target_id=order_id,
    )
    assert event.metadata['reason'] == 'Guest changed the order'
