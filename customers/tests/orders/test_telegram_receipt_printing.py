"""Telegram receipt auto-print contract tests."""

import importlib
import json
import secrets
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.test import Client
from django.utils import timezone

from base.models import Order, OrderItem, Session
from base.repositories.session import SessionRepository
from customers.models import ReceiptPrintJob, ReceiptPrintPolicy


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _activated_print_contract(db, settings):
    # Production creates this boundary in migration 0002 before the backend can
    # accept/sync orders. --nomigrations test runs reproduce that ordering here.
    ReceiptPrintPolicy.objects.get_or_create(pk=1)
    # Most endpoint tests are about claim/ACK fencing rather than wall-clock
    # settling. A dedicated test below exercises the production stability gate.
    settings.TELEGRAM_PRINT_MATERIALIZATION_SETTLE_SECONDS = 0


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


def _telegram(order):
    order.order_origin = Order.Origin.TELEGRAM
    order.save(update_fields=['order_origin'])
    return order


def test_claim_is_session_stable_and_ack_stops_telegram_replay(
    cashier_user, order_factory,
):
    client = Client()
    owner_auth = _auth(cashier_user)
    other_auth = _auth(cashier_user)
    pos_order = order_factory(cashier=cashier_user)
    telegram_order = _telegram(order_factory(cashier=cashier_user))

    first = client.post('/orders/print-jobs/claim', **owner_auth)
    assert first.status_code == 200, first.content
    job = first.json()['data']['job']
    assert job['order']['id'] == telegram_order.id
    assert job['order']['order_origin'] == 'TELEGRAM'
    assert job['order']['items']
    assert job['order']['id'] != pos_order.id

    # A lost claim response is recoverable without allocating a second token.
    repeated = client.post('/orders/print-jobs/claim', **owner_auth)
    assert repeated.json()['data']['job']['claim_token'] == job['claim_token']

    # Another signed-in POS cannot acknowledge or concurrently receive it.
    assert client.post(
        f"/orders/print-jobs/{job['claim_token']}/ack", **other_auth,
    ).status_code == 409
    assert client.post(
        '/orders/print-jobs/claim', **other_auth,
    ).json()['data']['job'] is None

    acknowledged = client.post(
        f"/orders/print-jobs/{job['claim_token']}/ack", **owner_auth,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()['data']['already_printed'] is False

    # ACK itself is idempotent, and a printed order never re-enters the queue.
    duplicate_ack = client.post(
        f"/orders/print-jobs/{job['claim_token']}/ack", **owner_auth,
    )
    assert duplicate_ack.status_code == 200
    assert duplicate_ack.json()['data']['already_printed'] is True
    assert client.post(
        '/orders/print-jobs/claim', **owner_auth,
    ).json()['data']['job'] is None

    ledger = ReceiptPrintJob.objects.get(order=telegram_order)
    assert ledger.state == ReceiptPrintJob.State.PRINTED
    assert ledger.printed_at is not None
    assert ledger.attempt_count == 1
    assert not ReceiptPrintJob.objects.filter(order=pos_order).exists()


def test_definite_failure_requeues_with_a_new_fencing_token(
    cashier_user, order_factory,
):
    client = Client()
    auth = _auth(cashier_user)
    order = _telegram(order_factory(cashier=cashier_user))

    first = client.post('/orders/print-jobs/claim', **auth).json()['data']['job']
    failed = client.post(
        f"/orders/print-jobs/{first['claim_token']}/fail",
        data=json.dumps({'error': 'printer offline'}),
        content_type='application/json',
        **auth,
    )
    assert failed.status_code == 200
    assert failed.json()['data']['retryable'] is True

    second = client.post('/orders/print-jobs/claim', **auth).json()['data']['job']
    assert second['order']['id'] == order.id
    assert second['claim_token'] != first['claim_token']
    assert second['attempt'] == 2
    # The released token is no longer authoritative after a retry claim.
    assert client.post(
        f"/orders/print-jobs/{first['claim_token']}/ack", **auth,
    ).status_code == 404

    ledger = ReceiptPrintJob.objects.get(order=order)
    assert ledger.last_error == 'printer offline'


def test_expired_lease_is_reclaimed_and_stale_ack_is_fenced(
    cashier_user, order_factory,
):
    client = Client()
    first_auth = _auth(cashier_user)
    second_auth = _auth(cashier_user)
    order = _telegram(order_factory(cashier=cashier_user))

    first = client.post(
        '/orders/print-jobs/claim', **first_auth,
    ).json()['data']['job']
    ReceiptPrintJob.objects.filter(order=order).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    second = client.post(
        '/orders/print-jobs/claim', **second_auth,
    ).json()['data']['job']
    assert second['order']['id'] == order.id
    assert second['claim_token'] != first['claim_token']
    assert second['attempt'] == 2
    assert client.post(
        f"/orders/print-jobs/{first['claim_token']}/ack", **first_auth,
    ).status_code == 404
    assert client.post(
        f"/orders/print-jobs/{second['claim_token']}/ack", **second_auth,
    ).status_code == 200


def test_claim_waits_for_items_and_rejects_customer_role(
    cashier_user, regular_user, product,
):
    client = Client()
    cashier_auth = _auth(cashier_user)
    customer_auth = _auth(regular_user)
    order = Order.objects.create(
        user=regular_user,
        cashier=cashier_user,
        order_origin=Order.Origin.TELEGRAM,
        order_type=Order.OrderType.DELIVERY,
        status=Order.Status.PREPARING,
        subtotal='10.00',
        total_amount='10.00',
    )

    assert client.post(
        '/orders/print-jobs/claim', **customer_auth,
    ).status_code == 403
    assert client.post(
        '/orders/print-jobs/claim', **cashier_auth,
    ).json()['data']['job'] is None

    OrderItem.objects.create(
        order=order, product=product, quantity=1, price='10.00',
    )
    claimed = client.post(
        '/orders/print-jobs/claim', **cashier_auth,
    ).json()['data']['job']
    assert claimed['order']['id'] == order.id


def test_claim_waits_for_full_multi_item_gross_not_just_first_synced_line(
    cashier_user, regular_user, product,
):
    """A staged OrderItem pull cannot print a financially partial receipt.

    The order includes quantity, an add-on-inclusive frozen price, an order
    discount, and non-product delivery/tip charges.  This proves readiness is
    checked against the canonical subtotal rather than total_amount.
    """
    client = Client()
    auth = _auth(cashier_user)
    order = Order.objects.create(
        user=regular_user,
        cashier=cashier_user,
        order_origin=Order.Origin.TELEGRAM,
        order_type=Order.OrderType.DELIVERY,
        status=Order.Status.PREPARING,
        subtotal='35.00',
        discount_amount='5.00',
        # 35 food - 5 loyalty + 7 delivery/tip = 37 collected.
        total_amount='37.00',
    )

    # Frozen unit price 12.50 includes the product's selected add-ons.  The
    # first independently-synced line contributes only 25 of the 35 subtotal.
    OrderItem.objects.create(
        order=order, product=product, quantity=2, price='12.50',
        original_price='10.00', detail='size + topping',
    )
    partial = client.post('/orders/print-jobs/claim', **auth)
    assert partial.status_code == 200
    assert partial.json()['data']['job'] is None
    assert not ReceiptPrintJob.objects.filter(order=order).exists()

    OrderItem.objects.create(
        order=order, product=product, quantity=1, price='10.00',
        original_price='10.00',
    )
    complete = client.post('/orders/print-jobs/claim', **auth)
    assert complete.status_code == 200
    job = complete.json()['data']['job']
    assert job['order']['id'] == order.id
    assert len(job['order']['items']) == 2


def test_complete_item_snapshot_must_settle_and_detect_free_line_arrival(
    settings, cashier_user, order_factory, product,
):
    settings.TELEGRAM_PRINT_MATERIALIZATION_SETTLE_SECONDS = 30
    client = Client()
    auth = _auth(cashier_user)
    order = _telegram(order_factory(cashier=cashier_user))

    first = client.post('/orders/print-jobs/claim', **auth)
    assert first.status_code == 200
    assert first.json()['data']['job'] is None
    ledger = ReceiptPrintJob.objects.get(order=order)
    assert ledger.materialization_fingerprint
    assert ledger.eligible_at > timezone.now()
    first_fingerprint = ledger.materialization_fingerprint

    # A free line does not change gross/subtotal equality, but it still belongs
    # on the receipt. Its identity/version changes the evidence fingerprint and
    # starts a fresh stability window before the claim can proceed.
    OrderItem.objects.create(
        order=order, product=product, quantity=1, price='0.00',
        original_price='10.00', detail='loyalty gift',
    )
    assert client.post(
        '/orders/print-jobs/claim', **auth,
    ).json()['data']['job'] is None
    ledger.refresh_from_db()
    assert ledger.materialization_fingerprint != first_fingerprint
    assert ledger.eligible_at > timezone.now()

    # An unchanged snapshot becomes claimable after the persisted dwell time.
    ReceiptPrintJob.objects.filter(pk=ledger.pk).update(
        eligible_at=timezone.now() - timedelta(seconds=1),
    )
    claimed = client.post('/orders/print-jobs/claim', **auth)
    assert claimed.json()['data']['job']['order']['id'] == order.id
    assert len(claimed.json()['data']['job']['order']['items']) == 2


def test_rollout_migration_suppresses_historical_telegram_orders(
    cashier_user, order_factory,
):
    order = _telegram(order_factory(cashier=cashier_user))
    migration = importlib.import_module(
        'customers.migrations.0002_receipt_print_job',
    )

    migration.suppress_historical_telegram_replay(
        django_apps, SimpleNamespace(connection=connection),
    )

    ledger = ReceiptPrintJob.objects.get(order=order)
    assert ledger.state == ReceiptPrintJob.State.PRINTED
    assert ledger.printed_at is not None
    assert 'historical replay' in ledger.last_error


def test_late_origin_backfill_cannot_enqueue_a_pre_activation_order(
    cashier_user, order_factory,
):
    policy = ReceiptPrintPolicy.objects.get(pk=1)
    order = order_factory(cashier=cashier_user)
    Order.objects.filter(pk=order.pk).update(
        created_at=policy.activated_at - timedelta(days=30),
        order_origin=Order.Origin.TELEGRAM,
    )

    response = Client().post(
        '/orders/print-jobs/claim', **_auth(cashier_user),
    )

    assert response.status_code == 200
    assert response.json()['data']['job'] is None
    assert not ReceiptPrintJob.objects.filter(order=order).exists()
