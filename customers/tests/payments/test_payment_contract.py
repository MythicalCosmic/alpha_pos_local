"""Cashier checkout and payment contract tests."""

import json
import secrets
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from base.models import CashRegister, OrderPayment, Session, Shift
from base.repositories.session import SessionRepository
from customers.services.order_service import CustomerOrderService


pytestmark = pytest.mark.django_db


def _auth(user):
    token = secrets.token_hex(32)
    Session.objects.create(
        user_id=user,
        ip_address='127.0.0.1',
        user_agent='',
        payload=SessionRepository.hash_token(token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


def _start_shift(cashier, branch_id):
    return Shift.objects.create(
        user=cashier,
        status=Shift.Status.ACTIVE,
        start_time=timezone.now(),
        branch_id=branch_id,
        device_id='pytest-terminal',
    )


def _post_payment(client, order, auth, payload, *, key=None):
    headers = dict(auth)
    headers['HTTP_IDEMPOTENCY_KEY'] = key or str(uuid4())
    return client.post(
        f'/orders/{order.id}/pay',
        data=json.dumps(payload),
        content_type='application/json',
        **headers,
    )


@pytest.mark.parametrize('raw_body', [b'', b'{'])
def test_pay_endpoint_rejects_missing_or_malformed_json(
    raw_body, cashier_user, regular_user, order_factory,
):
    order = order_factory(user=regular_user, cashier=cashier_user)
    response = Client().post(
        f'/orders/{order.id}/pay',
        data=raw_body,
        content_type='application/json',
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
        **_auth(cashier_user),
    )

    assert response.status_code == 400
    order.refresh_from_db()
    assert order.is_paid is False
    assert not OrderPayment.objects.filter(order=order).exists()


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {
            'payment_method': 'HUMO',
            'payments': [{'method': 'CASH', 'amount': 10}],
        },
        {'payment_method': 'CASH', 'payments': []},
        {'payments': None},
        {'payments': {}},
        {'payments': 'CASH'},
        {'payments': []},
        {'payments': [None]},
        {'payments': ['CASH']},
    ],
)
def test_pay_endpoint_rejects_missing_malformed_or_contradictory_payment_shape(
    payload, cashier_user, regular_user, order_factory,
):
    order = order_factory(user=regular_user, cashier=cashier_user)
    response = _post_payment(
        Client(), order, _auth(cashier_user), payload,
    )

    assert response.status_code == 422, response.content
    order.refresh_from_db()
    assert order.is_paid is False
    assert order.payment_method is None
    assert not OrderPayment.objects.filter(order=order).exists()


def test_smart_pos_dual_payment_shape_uses_structured_tenders(
    cashier_user, regular_user, order_factory,
):
    """Smart POS sends payments plus a dominant legacy compatibility hint."""
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    _start_shift(cashier_user, order.branch_id)

    response = _post_payment(
        Client(),
        order,
        _auth(cashier_user),
        {
            'payments': [
                {'method': 'HUMO', 'amount': 6},
                {'method': 'CASH', 'amount': 4},
            ],
            'payment_method': 'HUMO',
            'discount_percent': 0,
        },
    )

    assert response.status_code == 200, response.content
    order.refresh_from_db()
    assert order.payment_method == 'MIXED'
    assert list(
        OrderPayment.objects.filter(order=order)
        .order_by('line_index')
        .values_list('method', 'amount')
    ) == [
        ('HUMO', Decimal('6.00')),
        ('CASH', Decimal('4.00')),
    ]
    assert CashRegister.objects.get().current_balance == Decimal('4.00')


def test_smart_pos_zero_total_dual_shape_creates_no_tender(
    cashier_user, regular_user, order_factory,
):
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    _start_shift(cashier_user, order.branch_id)

    response = _post_payment(
        Client(),
        order,
        _auth(cashier_user),
        {
            'payments': [],
            'payment_method': 'CASH',
            'discount_percent': 100,
        },
    )

    assert response.status_code == 200, response.content
    order.refresh_from_db()
    assert order.total_amount == Decimal('0.00')
    assert order.payment_method is None
    assert not OrderPayment.objects.filter(order=order).exists()
    assert CashRegister.objects.get().current_balance == Decimal('0.00')


@pytest.mark.parametrize(
    'amount',
    ['NaN', 'Infinity', '-Infinity', -1, 0, '0.001', '99999999.991', '100000000'],
)
def test_structured_payment_rejects_nonfinite_nonpositive_or_unstorable_amount(
    amount, cashier_user, regular_user, order_factory,
):
    order = order_factory(user=regular_user, cashier=cashier_user)
    result, status = CustomerOrderService.mark_as_paid(
        order.id,
        cashier_id=cashier_user.id,
        user_id=cashier_user.id,
        user_role='CASHIER',
        payments=[{'method': 'CASH', 'amount': amount}],
    )

    assert status == 422, result
    order.refresh_from_db()
    assert order.is_paid is False
    assert not OrderPayment.objects.filter(order=order).exists()


@pytest.mark.parametrize(
    'discount',
    ['NaN', 'Infinity', '-Infinity', -1, 101, '1.001', None, ''],
)
def test_payment_rejects_invalid_discount(
    discount, cashier_user, regular_user, order_factory,
):
    order = order_factory(user=regular_user, cashier=cashier_user)
    result, status = CustomerOrderService.mark_as_paid(
        order.id,
        cashier_id=cashier_user.id,
        user_id=cashier_user.id,
        user_role='CASHIER',
        payment_method='CASH',
        discount_percent=discount,
    )

    assert status == 422, result
    order.refresh_from_db()
    assert order.is_paid is False


def test_legacy_method_is_trimmed_normalized_and_returns_checkout_evidence(
    cashier_user, regular_user, order_factory,
):
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    shift = _start_shift(cashier_user, order.branch_id)

    response = _post_payment(
        Client(),
        order,
        _auth(cashier_user),
        {'payment_method': '  cash  '},
    )

    assert response.status_code == 200, response.content
    data = response.json()['data']
    order.refresh_from_db()
    payment = OrderPayment.objects.get(order=order)
    assert data == {
        'is_paid': True,
        'order_id': order.id,
        'order_uuid': str(order.uuid),
        'payment_action_id': str(order.payment_action_id),
        'shift_id': shift.id,
        'shift_uuid': str(shift.uuid),
        'paid_at': order.paid_at.isoformat(),
        'payment_method': 'CASH',
        'discount_percent': '0.00',
        'discount_amount': '0.00',
        'total_amount': '10.00',
        'payments': [
            {'line_index': 0, 'method': 'CASH', 'amount': '10.00'},
        ],
    }
    assert payment.method == 'CASH'
    assert payment.amount == Decimal('10.00')
    assert payment.payment_action_id == order.payment_action_id


def test_headerless_legacy_client_gets_same_safe_success_on_exact_retry(
    cashier_user, regular_user, order_factory,
):
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    _start_shift(cashier_user, order.branch_id)
    client = Client()
    auth = _auth(cashier_user)
    payload = json.dumps({'payment_method': 'CASH'})

    first = client.post(
        f'/orders/{order.id}/pay',
        data=payload,
        content_type='application/json',
        **auth,
    )
    replay = client.post(
        f'/orders/{order.id}/pay',
        data=payload,
        content_type='application/json',
        **auth,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()['data'] == replay.json()['data']
    assert OrderPayment.objects.filter(order=order).count() == 1
    assert CashRegister.objects.get().current_balance == Decimal('10.00')


@pytest.mark.parametrize('cache_loss', ['delete', 'inflight'])
def test_pay_endpoint_recovers_commit_response_cache_crash_byte_stably(
    cache_loss, cashier_user, regular_user, order_factory,
):
    """Committed money survives loss of the middleware response cache.

    This exercises the real endpoint/decorator/service chain. The first request
    commits the Order, OrderPayment and drawer credit. We then reproduce the
    two realistic crash artifacts: a vanished claim, or an old in-flight claim
    whose success body was never stored. The retry must reconstruct the exact
    HTTP success without collecting money twice.
    """
    from base.models import IdempotencyKey

    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    _start_shift(cashier_user, order.branch_id)
    client = Client()
    auth = _auth(cashier_user)
    key = f'checkout-crash-{uuid4()}'
    payload = json.dumps({'payment_method': 'CASH'})

    first = client.post(
        f'/orders/{order.id}/pay',
        data=payload,
        content_type='application/json',
        HTTP_IDEMPOTENCY_KEY=key,
        **auth,
    )
    assert first.status_code == 200, first.content
    claim = IdempotencyKey.objects.get(key=key)
    assert claim.response_status == 200

    if cache_loss == 'delete':
        claim.delete()
    else:
        # The endpoint opts into recovery after five seconds. Simulate a worker
        # that committed the payment and died before filling the response body.
        IdempotencyKey.objects.filter(pk=claim.pk).update(
            response_status=0,
            response_body={},
            created_at=timezone.now() - timedelta(seconds=6),
        )

    recovered = client.post(
        f'/orders/{order.id}/pay',
        data=payload,
        content_type='application/json',
        HTTP_IDEMPOTENCY_KEY=key,
        **auth,
    )

    assert recovered.status_code == 200, recovered.content
    assert recovered.content == first.content
    assert recovered.json() == first.json()
    order.refresh_from_db()
    assert order.is_paid is True
    assert OrderPayment.objects.filter(order=order).count() == 1
    payment = OrderPayment.objects.get(order=order)
    assert payment.payment_action_id == order.payment_action_id
    assert payment.method == 'CASH'
    assert payment.amount == Decimal('10.00')
    assert CashRegister.objects.get().current_balance == Decimal('10.00')
    recovered_claim = IdempotencyKey.objects.get(key=key)
    assert recovered_claim.response_status == 200
    assert recovered_claim.response_body == first.json()


def test_same_checkout_action_replays_identical_evidence_but_rejects_conflict(
    cashier_user, regular_user, order_factory,
):
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    _start_shift(cashier_user, order.branch_id)
    action_id = uuid4()
    request = {
        'cashier_id': cashier_user.id,
        'user_id': cashier_user.id,
        'user_role': 'CASHIER',
        'payment_method': 'CASH',
        'payment_action_id': action_id,
    }

    first, first_status = CustomerOrderService.mark_as_paid(order.id, **request)
    replay, replay_status = CustomerOrderService.mark_as_paid(order.id, **request)
    conflict, conflict_status = CustomerOrderService.mark_as_paid(
        order.id,
        cashier_id=cashier_user.id,
        user_id=cashier_user.id,
        user_role='CASHIER',
        payment_method='HUMO',
        payment_action_id=action_id,
    )

    assert first_status == replay_status == 200
    assert first == replay
    assert conflict_status == 409, conflict
    assert OrderPayment.objects.filter(order=order).count() == 1
    assert CashRegister.objects.get().current_balance == Decimal('10.00')


def test_same_action_replays_when_order_was_discounted_before_checkout(
    cashier_user, regular_user, order_factory,
):
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    order.discount_percent = Decimal('10.00')
    order.discount_amount = Decimal('1.00')
    order.total_amount = Decimal('9.00')
    order.save(update_fields=[
        'discount_percent', 'discount_amount', 'total_amount',
    ])
    _start_shift(cashier_user, order.branch_id)
    action_id = uuid4()
    request = {
        'cashier_id': cashier_user.id,
        'user_id': cashier_user.id,
        'user_role': 'CASHIER',
        'payment_method': 'CASH',
        # No additional pay-time discount; preserve the existing order terms.
        'discount_percent': 0,
        'payment_action_id': action_id,
    }

    first, first_status = CustomerOrderService.mark_as_paid(order.id, **request)
    replay, replay_status = CustomerOrderService.mark_as_paid(order.id, **request)

    assert first_status == replay_status == 200
    assert first == replay
    assert first['data']['discount_percent'] == '10.00'
    assert first['data']['discount_amount'] == '1.00'
    assert first['data']['total_amount'] == '9.00'
    assert first['data']['payments'] == [
        {'line_index': 0, 'method': 'CASH', 'amount': '9.00'},
    ]
    assert CashRegister.objects.get().current_balance == Decimal('9.00')


def test_zero_total_has_replayable_action_but_no_tender_evidence(
    cashier_user, regular_user, order_factory,
):
    CashRegister.objects.create(current_balance=Decimal('0'))
    order = order_factory(user=regular_user, cashier=cashier_user)
    _start_shift(cashier_user, order.branch_id)
    action_id = uuid4()
    request = {
        'cashier_id': cashier_user.id,
        'user_id': cashier_user.id,
        'user_role': 'CASHIER',
        'payment_method': 'CASH',
        'discount_percent': 100,
        'payment_action_id': action_id,
    }

    first, first_status = CustomerOrderService.mark_as_paid(order.id, **request)
    replay, replay_status = CustomerOrderService.mark_as_paid(order.id, **request)

    assert first_status == replay_status == 200
    assert first == replay
    assert first['data']['payment_action_id'] == str(action_id)
    assert first['data']['payment_method'] is None
    assert first['data']['payments'] == []
    order.refresh_from_db()
    assert order.total_amount == Decimal('0.00')
    assert order.payment_action_id == action_id
    assert not OrderPayment.objects.filter(order=order).exists()


def test_cloud_receiver_accepts_zero_total_action_without_payment_child(
    settings, cashier_user,
):
    from base.models import Order
    from base.services.sync.receiver import CloudReceiver
    from base.services.tender import tender_integrity_issues

    settings.DEPLOYMENT_MODE = 'cloud'
    settings.BRANCH_ID = 'cloud'
    order_uuid = str(uuid4())
    action_id = uuid4()
    paid_at = timezone.now()

    result = CloudReceiver.receive_batch(
        'order',
        'branch-a',
        [{
            'uuid': order_uuid,
            'sync_version': 1,
            'branch_id': 'branch-a',
            'user_uuid': str(cashier_user.uuid),
            'cashier_uuid': str(cashier_user.uuid),
            'order_origin': Order.Origin.POS,
            'order_type': Order.OrderType.HALL,
            'status': Order.Status.PREPARING,
            'is_paid': True,
            'payment_action_id': str(action_id),
            'payment_method': None,
            'subtotal': '10.00',
            'discount_amount': '10.00',
            'discount_percent': '100.00',
            'total_amount': '0.00',
            'paid_at': paid_at.isoformat(),
        }],
    )

    assert result['acknowledged_uuids'] == [order_uuid], result
    assert result['rejected_uuids'] == []
    landed = Order.objects.get(uuid=order_uuid)
    assert landed.is_paid is True
    assert landed.payment_action_id == action_id
    assert landed.payment_method is None
    assert landed.total_amount == Decimal('0.00')
    assert not OrderPayment.objects.filter(order=landed).exists()
    assert tender_integrity_issues(
        Order.objects.filter(pk=landed.pk),
        require_concrete=True,
    ) == []
