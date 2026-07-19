"""POS contract for the new Courier/DeliveryAssignment dispatch domain."""
import json
import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from base.models import Order, Session, User
from base.repositories.session import SessionRepository
from couriers.models import Courier, CourierNotification, DeliveryAssignment


pytestmark = pytest.mark.django_db


def _staff(role='CASHIER'):
    suffix = secrets.token_hex(4)
    user = User.objects.create(
        email=f'{role.lower()}-{suffix}@pos.local',
        first_name=role.title(),
        last_name='Operator',
        role=role,
        status='ACTIVE',
        password='!',
    )
    token = secrets.token_hex(32)
    Session.objects.create(
        user_id=user,
        ip_address='127.0.0.1',
        user_agent='',
        payload=SessionRepository.hash_token(token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return user, token


def _courier(code, *, branch_id='cloud'):
    suffix = secrets.token_hex(4)
    user = User.objects.create(
        email=f'{code.lower()}-{suffix}@courier.local',
        first_name=code,
        last_name='Rider',
        role='CASHIER',
        status='ACTIVE',
        password='!',
    )
    return Courier.objects.create(
        user=user,
        code=code,
        first_name=code,
        last_name='Rider',
        phone=f'+99890{secrets.randbelow(10**7):07d}',
        branch_id=branch_id,
    )


def _order(user, *, branch_id='cloud'):
    return Order.objects.create(
        user=user,
        cashier=user,
        order_type=Order.OrderType.DELIVERY,
        status=Order.Status.PREPARING,
        branch_id=branch_id,
        total_amount=Decimal('125000'),
    )


def _auth(token):
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


@pytest.mark.parametrize('role', ['ADMIN', 'MANAGER', 'CASHIER'])
def test_all_pos_staff_can_list_new_couriers(role):
    _courier(f'CR-{role[:2]}')
    _user, token = _staff(role)

    response = Client().get('/api/couriers/', **_auth(token))

    assert response.status_code == 200
    assert response.json()['data'][0]['id'].startswith('CR-')


def test_cashier_cannot_provision_or_rotate_credentials():
    courier = _courier('CR-LOCK')
    _user, token = _staff('CASHIER')
    client = Client()

    create = client.post(
        '/api/couriers/create',
        data=json.dumps({'phone': '+998901234567'}),
        content_type='application/json',
        **_auth(token),
    )
    regenerate = client.post(
        f'/api/couriers/{courier.pk}/regenerate',
        content_type='application/json',
        **_auth(token),
    )

    assert create.status_code == 403
    assert regenerate.status_code == 403


def test_cashier_assigns_reassigns_and_clears_with_order_projection():
    cashier, token = _staff('CASHIER')
    order = _order(cashier)
    first = _courier('CR-101')
    second = _courier('CR-102')
    client = Client()

    assigned = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': first.pk}),
        content_type='application/json',
        **_auth(token),
    )
    assert assigned.status_code == 200, assigned.content
    assignment = DeliveryAssignment.objects.get(order=order)
    assignment_pk = assignment.pk
    expected = {
        'id': first.code,
        'pk': first.pk,
        'code': first.code,
        'name': first.full_name,
        'phone': first.phone,
        'step': 'ASSIGNED',
    }
    assert assigned.json()['data']['courier_assignment'] == expected

    listed = client.get('/orders?per_page=10', **_auth(token))
    detailed = client.get(f'/orders/{order.pk}', **_auth(token))
    assert listed.status_code == detailed.status_code == 200
    assert listed.json()['data']['orders'][0]['courier_assignment'] == expected
    assert detailed.json()['data']['order']['courier_assignment'] == expected
    # The legacy DeliveryPerson relation remains untouched by the new path.
    order.refresh_from_db()
    assert order.delivery_person_id is None

    reassigned = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': second.pk}),
        content_type='application/json',
        **_auth(token),
    )
    assignment.refresh_from_db()
    assert reassigned.status_code == 200
    assert assignment.pk == assignment_pk
    assert assignment.courier_id == second.pk
    assert CourierNotification.objects.filter(
        courier=first, order=order, title__icontains='reassigned',
    ).exists()

    cleared = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': None}),
        content_type='application/json',
        **_auth(token),
    )
    assignment.refresh_from_db()
    assert cleared.status_code == 200
    assert cleared.json()['data']['courier_assignment'] is None
    assert assignment.pk == assignment_pk
    assert assignment.step == DeliveryAssignment.Step.DECLINED
    # Preserve who was cleared as durable lifecycle evidence.
    assert assignment.courier_id == second.pk
    assert client.get(
        f'/orders/{order.pk}', **_auth(token),
    ).json()['data']['order']['courier_assignment'] is None

    # Clear is idempotent and must not delete or duplicate the assignment row.
    again = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': None}),
        content_type='application/json',
        **_auth(token),
    )
    assert again.status_code == 200
    assert DeliveryAssignment.objects.filter(order=order).count() == 1


def test_order_list_preloads_assignment_without_per_order_queries():
    cashier, token = _staff('CASHIER')
    for number in range(5):
        order = _order(cashier)
        courier = _courier(f'CR-Q{number}')
        DeliveryAssignment.objects.create(
            order=order,
            courier=courier,
            step=DeliveryAssignment.Step.ASSIGNED,
            assigned_at=timezone.now(),
        )

    # Warm the session cache so this assertion measures the order contract.
    client = Client()
    client.get('/api/couriers/', **_auth(token))
    with CaptureQueriesContext(connection) as captured:
        response = client.get('/orders?per_page=10', **_auth(token))

    assert response.status_code == 200
    assert len(response.json()['data']['orders']) == 5
    assignment_queries = [
        query['sql'] for query in captured.captured_queries
        if 'couriers_deliveryassignment' in query['sql'].lower()
    ]
    # One JOIN in the page query; never five reverse-relation lookups.
    assert len(assignment_queries) == 1


def test_assignment_rejects_cross_branch_and_terminal_orders():
    cashier, token = _staff('CASHIER')
    courier = _courier('CR-OTHER', branch_id='other')
    order = _order(cashier, branch_id='cloud')
    client = Client()

    cross_branch = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk}),
        content_type='application/json',
        **_auth(token),
    )
    assert cross_branch.status_code == 409
    assert not DeliveryAssignment.objects.filter(order=order).exists()

    order.status = Order.Status.COMPLETED
    order.save(update_fields=['status'])
    same_branch = _courier('CR-SAME')
    terminal = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': same_branch.pk}),
        content_type='application/json',
        **_auth(token),
    )
    assert terminal.status_code == 409
    assert not DeliveryAssignment.objects.filter(order=order).exists()
