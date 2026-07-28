"""POS assignment contract for the Courier delivery domain."""
import json
import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models.query import QuerySet
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from base.models import (
    DeliveryPerson,
    Order,
    Session,
    Shift,
    SyncQueueRecord,
    User,
)
from base.repositories.session import SessionRepository
from couriers import realtime, services
from couriers.models import Courier, CourierNotification, DeliveryAssignment


pytestmark = pytest.mark.django_db
TEST_BRANCH = str(getattr(settings, 'BRANCH_ID', '') or 'main')


def _staff(role='CASHIER', *, branch_id=None):
    suffix = secrets.token_hex(4)
    fields = dict(
        email=f'{role.lower()}-{suffix}@pos.local',
        first_name=role.title(),
        last_name='Operator',
        role=role,
        status='ACTIVE',
        password='!',
    )
    if branch_id is not None:
        fields['branch_id'] = branch_id
    user = User.objects.create(**fields)
    token = secrets.token_hex(32)
    Session.objects.create(
        user_id=user,
        ip_address='127.0.0.1',
        user_agent='',
        payload=SessionRepository.hash_token(token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return user, token


def _courier(code, *, branch_id=TEST_BRANCH):
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


def _order(user, *, branch_id=TEST_BRANCH, order_origin=None):
    return Order.objects.create(
        user=user,
        cashier=user,
        order_type=Order.OrderType.DELIVERY,
        order_origin=order_origin or Order.Origin.POS,
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
    order = _order(cashier, order_origin=Order.Origin.TELEGRAM)
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
    assert listed.json()['data']['orders'][0]['order_origin'] == 'TELEGRAM'
    assert detailed.json()['data']['order']['order_origin'] == 'TELEGRAM'
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


@override_settings(SYNC_ENABLED=True, DEPLOYMENT_MODE='local')
def test_inbound_legacy_courier_replay_is_cleared_and_published():
    """A rejected legacy projection must be corrected on both sync peers."""
    cashier, _token = _staff('CASHIER')
    order = _order(cashier)
    courier = _courier('CR-AUTHORITATIVE')
    DeliveryAssignment.objects.create(
        order=order,
        courier=courier,
        step=DeliveryAssignment.Step.ASSIGNED,
        assigned_at=timezone.now(),
    )
    legacy = DeliveryPerson.objects.create(
        first_name='Legacy',
        last_name='Courier',
        phone_number='+998900000001',
    )
    SyncQueueRecord.objects.all().delete()
    starting_version = order.sync_version

    # Simulate a cloud pull applying an old legacy courier without itself
    # enqueuing an echo. The guard's corrective save must create that echo.
    order.delivery_person = legacy
    order.save(_syncing=True, update_fields=['delivery_person'])

    order.refresh_from_db()
    assert order.delivery_person_id is None
    assert order.sync_version == starting_version + 1
    assert order.synced_at is None
    queued = SyncQueueRecord.objects.get(
        model_name='order',
        record_uuid=order.uuid,
    )
    assert queued.payload['sync_version'] == order.sync_version
    assert queued.payload['delivery_person_uuid'] is None


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
    order = _order(cashier, branch_id=TEST_BRANCH)
    client = Client()

    cross_branch = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk}),
        content_type='application/json',
        **_auth(token),
    )
    assert cross_branch.status_code == 404
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


def test_same_courier_retry_preserves_lifecycle_and_timestamps():
    cashier, token = _staff('CASHIER')
    order = _order(cashier)
    courier = _courier('CR-IDEMPOTENT')
    client = Client()
    first = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk,
                         'fee': 15000, 'addr_text': 'Original'}),
        content_type='application/json',
        **_auth(token),
    )
    assert first.status_code == 200
    assignment = DeliveryAssignment.objects.get(order=order)
    accepted_at = timezone.now()
    ready_at = accepted_at + timedelta(seconds=2)
    assignment.step = DeliveryAssignment.Step.READY
    assignment.accepted_at = accepted_at
    assignment.ready_at = ready_at
    assignment.save(update_fields=['step', 'accepted_at', 'ready_at', 'updated_at'])
    assignment.refresh_from_db()
    before = {
        field: getattr(assignment, field)
        for field in (
            'step', 'fee', 'assigned_at', 'accepted_at', 'ready_at',
            'picked_at', 'delivered_at', 'expires_at', 'addr_text', 'updated_at',
        )
    }

    retry = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk,
                         'fee': 999999, 'addr_text': 'Should not replace'}),
        content_type='application/json',
        **_auth(token),
    )

    assert retry.status_code == 200
    assignment.refresh_from_db()
    assert {field: getattr(assignment, field) for field in before} == before
    assert DeliveryAssignment.objects.filter(order=order).count() == 1


def test_ready_order_assignment_starts_at_ready_without_rewind():
    cashier, token = _staff('CASHIER')
    order = _order(cashier)
    order.status = Order.Status.READY
    order.ready_at = timezone.now() - timedelta(minutes=3)
    order.save(update_fields=['status', 'ready_at', 'updated_at'])
    courier = _courier('CR-READY')

    response = Client().post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk}),
        content_type='application/json',
        **_auth(token),
    )

    assert response.status_code == 200
    assignment = DeliveryAssignment.objects.get(order=order)
    assert assignment.step == DeliveryAssignment.Step.READY
    assert assignment.ready_at == order.ready_at
    assert response.json()['data']['courier_assignment']['step'] == 'READY'


def test_assignment_network_effects_wait_until_commit(
    monkeypatch, django_capture_on_commit_callbacks,
):
    cashier, token = _staff('CASHIER')
    order = _order(cashier)
    courier = _courier('CR-COMMIT')
    effects = []
    monkeypatch.setattr(
        services, '_emit',
        lambda *args, **kwargs: effects.append(('courier', args, kwargs)),
    )
    monkeypatch.setattr(
        realtime, 'send_to_cashiers',
        lambda *args, **kwargs: effects.append(('cashiers', args, kwargs)),
    )

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = Client().post(
            '/api/couriers/assign',
            data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk}),
            content_type='application/json',
            **_auth(token),
        )
        assert response.status_code == 200
        assert effects == []

    assert len(callbacks) == 2
    for callback in callbacks:
        callback()
    assert [effect[0] for effect in effects] == ['courier', 'cashiers']


@pytest.mark.parametrize('step', [
    DeliveryAssignment.Step.PICKED_UP,
    DeliveryAssignment.Step.ON_WAY,
    DeliveryAssignment.Step.DELIVERED,
])
def test_in_flight_assignment_cannot_be_reassigned_or_cleared(step):
    cashier, token = _staff('CASHIER')
    order = _order(cashier)
    first = _courier(f'CR-FIRST-{step[:2]}')
    second = _courier(f'CR-SECOND-{step[:2]}')
    assignment = DeliveryAssignment.objects.create(
        order=order,
        courier=first,
        step=step,
        assigned_at=timezone.now() - timedelta(minutes=10),
    )
    client = Client()

    reassign = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': second.pk}),
        content_type='application/json',
        **_auth(token),
    )
    clear = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': None}),
        content_type='application/json',
        **_auth(token),
    )

    assert reassign.status_code == 409
    assert clear.status_code == 409
    assignment.refresh_from_db()
    assert assignment.courier_id == first.pk
    assert assignment.step == step


def test_stale_previous_courier_cannot_advance_reassigned_order():
    cashier, _token = _staff('CASHIER')
    order = _order(cashier)
    first = _courier('CR-STALE-FIRST')
    second = _courier('CR-STALE-SECOND')
    assignment = DeliveryAssignment.objects.create(
        order=order,
        courier=first,
        step=DeliveryAssignment.Step.READY,
        assigned_at=timezone.now(),
        ready_at=timezone.now(),
    )
    stale_assignment = DeliveryAssignment.objects.get(pk=assignment.pk)
    DeliveryAssignment.objects.filter(pk=assignment.pk).update(courier=second)

    updated, error = services.advance_status(
        stale_assignment, DeliveryAssignment.Step.PICKED_UP,
    )

    assert updated is None
    assert 'reassigned' in error.lower()
    assignment.refresh_from_db()
    assert assignment.courier_id == second.pk
    assert assignment.step == DeliveryAssignment.Step.READY


@pytest.mark.parametrize('account_state', ['SUSPENDED', 'DELETED'])
def test_suspended_or_deleted_courier_is_hidden_and_cannot_be_assigned(account_state):
    cashier, token = _staff('CASHIER')
    order = _order(cashier)
    courier = _courier(f'CR-{account_state}')
    if account_state == 'SUSPENDED':
        courier.user.status = User.UserStatus.SUSPENDED
        courier.user.save(update_fields=['status', 'updated_at'])
    else:
        courier.user.is_deleted = True
        courier.user.save(update_fields=['is_deleted', 'updated_at'])
    client = Client()

    listed = client.get('/api/couriers/', **_auth(token))
    assigned = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': order.pk, 'courier_id': courier.pk}),
        content_type='application/json',
        **_auth(token),
    )

    assert courier.code not in {row['id'] for row in listed.json()['data']}
    assert assigned.status_code == 409
    assert not DeliveryAssignment.objects.filter(order=order).exists()


def test_cashier_dispatch_is_scoped_to_active_shift_branch_and_admin_is_global():
    cashier, token = _staff('CASHIER', branch_id='cloud')
    Shift.objects.create(
        user=cashier, status=Shift.Status.ACTIVE,
        start_time=timezone.now(), branch_id='branch-a',
    )
    own_order = _order(cashier, branch_id='branch-a')
    foreign_order = _order(cashier, branch_id='branch-b')
    own = _courier('CR-BRANCH-A', branch_id='branch-a')
    foreign = _courier('CR-BRANCH-B', branch_id='branch-b')
    client = Client()

    listed = client.get('/api/couriers/', **_auth(token))
    assert {row['id'] for row in listed.json()['data']} == {own.code}
    assert client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': foreign_order.pk, 'courier_id': foreign.pk}),
        content_type='application/json', **_auth(token),
    ).status_code == 404
    assert client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': foreign_order.pk, 'courier_id': None}),
        content_type='application/json', **_auth(token),
    ).status_code == 404
    assert client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': own_order.pk, 'courier_id': foreign.pk}),
        content_type='application/json', **_auth(token),
    ).status_code == 404

    _admin, admin_token = _staff('ADMIN', branch_id='cloud')
    admin_list = client.get('/api/couriers/', **_auth(admin_token))
    assert {row['id'] for row in admin_list.json()['data']} == {
        own.code, foreign.code,
    }
    assigned = client.post(
        '/api/couriers/assign',
        data=json.dumps({'order_id': foreign_order.pk, 'courier_id': foreign.pk}),
        content_type='application/json', **_auth(admin_token),
    )
    assert assigned.status_code == 200


def test_auto_picker_treats_on_way_as_busy_and_assignment_is_exclusive(monkeypatch):
    cashier, _token = _staff('CASHIER')
    busy = _courier('CR-BUSY')
    busy.online = True
    busy.save(update_fields=['online', 'updated_at'])
    free = _courier('CR-FREE')
    free.online = True
    free.save(update_fields=['online', 'updated_at'])
    DeliveryAssignment.objects.create(
        order=_order(cashier), courier=busy,
        step=DeliveryAssignment.Step.ON_WAY,
        assigned_at=timezone.now(),
    )
    lock_calls = []
    real_select_for_update = QuerySet.select_for_update

    def tracked_lock(queryset, *args, **kwargs):
        lock_calls.append(kwargs)
        return real_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, 'select_for_update', tracked_lock)
    selected = services.pick_available_courier(branch_id=TEST_BRANCH)
    assert selected.pk == free.pk
    assert lock_calls

    first_order = _order(cashier)
    services.assign(first_order, free)
    with pytest.raises(services.AssignmentConflict, match='active delivery'):
        services.assign(_order(cashier), free)


def test_notification_failure_rolls_back_savepoint_not_outer_transaction(monkeypatch):
    courier = _courier('CR-NOTIFY-SAFE')

    def fail_notification(**kwargs):
        raise IntegrityError('simulated notification insert failure')

    monkeypatch.setattr(CourierNotification.objects, 'create', fail_notification)
    with transaction.atomic():
        assert services.notify(courier, title='Optional notification') is None
        courier.online = True
        courier.save(update_fields=['online', 'updated_at'])

    courier.refresh_from_db()
    assert courier.online is True


def test_courier_phone_is_canonical_and_unique():
    courier = _courier('CR-PHONE')
    courier.phone = '90 123 45 67'
    courier.save(update_fields=['phone', 'updated_at'])
    assert courier.phone == '998901234567'

    suffix = secrets.token_hex(4)
    other_user = User.objects.create(
        email=f'duplicate-{suffix}@courier.local', first_name='D', last_name='U',
        role='CASHIER', status='ACTIVE', password='!',
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Courier.objects.create(
                user=other_user, code='CR-PHONE-DUP', phone='+998 90 123 45 67',
                branch_id=TEST_BRANCH,
            )
