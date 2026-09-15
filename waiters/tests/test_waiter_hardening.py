"""Cross-route policy, ownership, retry, and table/stock regression contracts."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection, connections
from django.test import Client
from django.utils import timezone

from base.models import AppSettings, AuditLog, Order, OrderItem, Place, Session, Shift, Table, User
from base.repositories import SessionRepository
from base.services.order_floor import reconcile_table
from base.services.waiter_settings import update_policy
from customers.services.order_service import CustomerOrderService
from waiters.services.order_service import WaiterOrderService
from waiters.services.waiter_service import WaiterService

pytestmark = pytest.mark.django_db


@pytest.fixture
def waiter():
    update_policy({'waiter_enabled': True})
    return User.objects.create(email='new-waiter@test.local', role='WAITER',
                               permissions=['order.create', 'order.update', 'order.cancel'])


def client_for(user):
    token = uuid4().hex
    Session.objects.create(user_id=user, payload=SessionRepository.hash_token(token),
                           expires_at=timezone.now() + timedelta(days=1), user_agent='hardening')
    return Client(HTTP_AUTHORIZATION='Bearer ' + token, HTTP_USER_AGENT='hardening')


def post(client, path, body=None, key='command'):
    headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
    return client.post(path, data=json.dumps(body or {}), content_type='application/json', **headers)


def create(waiter, product, **kwargs):
    body, status = WaiterOrderService.create_order(waiter.pk,
        [{'product_id': product.pk, 'quantity': 1}], order_type=kwargs.pop('order_type', 'PICKUP'), **kwargs)
    assert status == 201, body
    return Order.objects.get(pk=body['data']['order_id'])


def test_dynamic_settings_are_strict_and_admin_only(waiter, admin_user):
    client = client_for(admin_user)
    request = {'waiter_payment_mode': 'PERMITTED_WAITER', 'waiter_require_shift': True}
    result = client.put('/api/waiters/settings', data=json.dumps(request), content_type='application/json')
    assert result.status_code == 200, result.content
    assert len(result.json()['data']['settings']['waiter_payment_mode_choices']) == 2
    assert client_for(waiter).put('/api/waiters/settings', data='{}', content_type='application/json').status_code == 403
    assert update_policy({'waiter_enabled': 'false'})[1] == 422
    assert AppSettings.objects.get(pk=1).waiter_enabled is True
    assert AuditLog.objects.filter(action='WAITER_POLICY_UPDATE').count() == 1


def test_disabled_feature_blocks_existing_sessions_on_both_surfaces(waiter):
    client = client_for(waiter)
    assert client.get('/api/waiters/venue-config').status_code == 200
    update_policy({'waiter_enabled': False})
    for path in ('/api/waiters/orders', '/orders', '/products', '/shifts/current'):
        response = client.get(path)
        assert response.status_code == 403, (path, response.content)
        assert response.json()['code'] == 'WAITER_DISABLED'
    assert post(client, '/api/waiters/auth-logout').status_code == 200


def test_cashier_collection_preserves_waiter_and_releases_table(waiter, product, cashier_user):
    from core.shifts.service import ShiftService
    place = Place.objects.create(name='Main')
    table = Table.objects.create(place=place, number='W1')
    order = create(waiter, product, order_type='HALL', table_id=table.pk)
    snapshot = order.waiter_policy_snapshot.copy()
    assert order.cashier_id is None and order.waiter_id == waiter.pk
    assert ShiftService.start_shift(cashier_user.pk)[1] == 201
    result, status = CustomerOrderService.mark_as_paid(order.pk, payment_method='CASH',
        cashier_id=cashier_user.pk, user_id=cashier_user.pk, user_role='CASHIER')
    assert status == 200, result
    order.refresh_from_db(); table.refresh_from_db()
    assert order.waiter_id == waiter.pk and order.cashier_id == cashier_user.pk
    assert order.waiter_policy_snapshot == snapshot
    assert WaiterOrderService.get_order(order.pk, waiter.pk)[1] == 200
    assert table.status == 'AVAILABLE'
    assert order.to_sync_dict()['waiter_uuid'] == str(waiter.uuid)


def test_payment_policy_requires_both_setting_and_explicit_grant(waiter, product):
    from core.shifts.service import ShiftService
    order = create(waiter, product)
    client = client_for(waiter)
    assert post(client, f'/orders/{order.pk}/pay', {'payment_method': 'CASH'}).status_code == 403
    update_policy({'waiter_payment_mode': 'PERMITTED_WAITER'})
    assert post(client, f'/orders/{order.pk}/pay', {'payment_method': 'CASH'}).status_code == 403
    waiter.permissions = [*waiter.permissions, 'order.pay']; waiter.save(update_fields=['permissions'])
    assert ShiftService.start_shift(waiter.pk)[1] == 201
    response = post(client, f'/orders/{order.pk}/pay', {'payment_method': 'CASH'})
    assert response.status_code == 200, response.content
    order.refresh_from_db()
    assert order.waiter_id == waiter.pk and order.is_paid
    assert WaiterOrderService.cancel_order(order.pk, waiter.pk)[1] == 403


def test_shared_order_reads_are_personal_and_customer_directory_is_forbidden(waiter, product, cashier_user):
    mine = create(waiter, product)
    other = Order.objects.create(user=cashier_user, cashier=cashier_user, status='PREPARING')
    client = client_for(waiter)
    result = client.get('/orders').json()
    assert [row['id'] for row in result['data']['orders']] == [mine.pk]
    assert client.get(f'/orders/{other.pk}').status_code in (403, 404)
    for path in ('/clients', '/clients/lookup?phone=998901234567', '/orders/chef-display', '/orders/client-display'):
        assert client.get(path).status_code == 403, path


def test_create_add_retry_and_permission_revocation(waiter, product):
    client = client_for(waiter)
    payload = {'order_type': 'PICKUP', 'items': [{'product_id': product.pk, 'quantity': 1}]}
    path = '/api/waiters/orders/create'
    assert post(client, path, payload, key=None).status_code == 422
    first = post(client, path, payload)
    second = post(client, path, payload)
    assert first.status_code == 201 and first.content == second.content
    order = Order.objects.get()
    add_path = f'/api/waiters/orders/{order.pk}/add-item'
    add = {'product_id': product.pk, 'quantity': 2}
    first_add = post(client, add_path, add, key='add')
    assert first_add.status_code == 200, first_add.content
    assert post(client, add_path, add, key='add').content == first_add.content
    assert order.items.get().quantity == 3
    waiter.permissions = []; waiter.save(update_fields=['permissions'])
    assert post(client, path, payload).status_code == 403
    assert post(client, add_path, add, key='add').status_code == 403
    assert Order.objects.count() == 1


@pytest.mark.parametrize('status', ['OPEN', 'COMPLETED', 'CANCELED'])
def test_ready_cannot_reopen_terminal_or_skip_open(waiter, product, status):
    order = create(waiter, product)
    order.status = status; order.save(update_fields=['status'])
    result, code = WaiterOrderService.mark_ready(order.pk, waiter.pk)
    assert code >= 400, result
    order.refresh_from_db()
    assert order.status == status and order.ready_at is None


def test_paid_kitchen_ticket_can_advance_and_ready_retry_preserves_time(waiter, product):
    order = create(waiter, product)
    order.is_paid = True; order.save(update_fields=['is_paid'])
    assert WaiterOrderService.mark_ready(order.pk, waiter.pk)[1] == 200
    order.refresh_from_db(); ready_at = order.ready_at
    assert WaiterOrderService.mark_ready(order.pk, waiter.pk)[1] == 200
    order.refresh_from_db(); assert order.ready_at == ready_at
    assert CustomerOrderService.unmark_item_ready(order.pk, order.items.get().pk,
        user_id=waiter.pk, user_role='WAITER')[1] >= 400


def test_table_validation_and_legacy_multiple_ticket_reconciliation(waiter, product):
    place = Place.objects.create(name='Main')
    table = Table.objects.create(place=place, number='W2')
    first = create(waiter, product, order_type='HALL', table_id=table.pk)
    data, status = WaiterOrderService.create_order(waiter.pk,
        [{'product_id': product.pk}], table_id=table.pk)
    assert status == 409 and data['code'] == 'TABLE_UNAVAILABLE'
    assert WaiterOrderService.create_order(waiter.pk, [{'product_id': product.pk}])[1] == 422
    # Pre-upgrade data can contain a second ticket: closing one must not free it.
    second = Order.objects.create(user=waiter, waiter=waiter, table=table, status='PREPARING')
    first.status = 'CANCELED'; first.save(update_fields=['status'])
    reconcile_table(table.pk); table.refresh_from_db(); assert table.status == 'OCCUPIED'
    second.status = 'CANCELED'; second.save(update_fields=['status'])
    reconcile_table(table.pk); table.refresh_from_db(); assert table.status == 'AVAILABLE'


def test_shift_required_is_configurable_and_closing_checks_served_orders(waiter, product):
    from core.shifts.service import ShiftService
    create(waiter, product)
    update_policy({'waiter_require_shift': True})
    assert WaiterOrderService.create_order(waiter.pk, [{'product_id': product.pk}], order_type='PICKUP')[1] == 400
    result, status = ShiftService.start_shift(waiter.pk)
    assert status == 201, result
    shift = Shift.objects.get(user=waiter, status='ACTIVE')
    order = create(waiter, product)
    assert order.waiter_shift_id == shift.pk
    result, status = ShiftService.end_shift(shift.pk, waiter.pk, '', actor=waiter)
    assert status == 400 and 'unpaid' in result['message']


@pytest.mark.parametrize('date_from,date_to', [('bad', None), ('2026-09-12', '2026-09-01')])
def test_invalid_statistics_dates_are_not_silently_replaced(waiter, date_from, date_to):
    assert WaiterService.get_stats(waiter.pk, date_from=date_from, date_to=date_to)[1] == 422


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != 'postgresql', reason='Requires PostgreSQL row locks')
def test_real_concurrent_table_claims_create_one_ticket(waiter, product):
    table = Table.objects.create(place=Place.objects.create(name='Race'), number='R1')
    barrier = Barrier(2)
    def run(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return WaiterOrderService.create_order(waiter.pk,
                [{'product_id': product.pk}], table_id=table.pk)[1]
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, index) for index in range(2)]
        statuses = [future.result(timeout=30) for future in futures]
    assert sorted(statuses) == [201, 409]
    assert Order.objects.filter(table=table, is_deleted=False).count() == 1


def test_discount_permission_ownership_and_audit_are_shared(waiter, product, cashier_user):
    from discounts.models import Discount, DiscountType
    from discounts.services import DiscountService
    kind = DiscountType.objects.create(name='Test percent', code='WP', discount_method='PERCENTAGE')
    discount = Discount.objects.create(name='Waiter discount', code='WP10', discount_type=kind, value=10)
    mine = create(waiter, product)
    other = Order.objects.create(user=cashier_user, cashier=cashier_user, status='PREPARING', subtotal=10, total_amount=10)
    OrderItem.objects.create(order=other, product=product, quantity=1, price=10)
    assert DiscountService.apply_to_order(mine.pk, discount.code, waiter.pk)[1] == 403
    waiter.permissions = [*waiter.permissions, 'discount.apply']; waiter.save(update_fields=['permissions'])
    assert DiscountService.apply_to_order(other.pk, discount.code, waiter.pk)[1] == 403
    assert DiscountService.apply_to_order(mine.pk, discount.code, waiter.pk)[1] == 200
    assert AuditLog.objects.filter(action='DISCOUNT_APPLY', target_id=mine.pk, actor=waiter).count() == 1


def test_audit_command_reports_without_modifying_legacy_data(waiter):
    from io import StringIO
    from django.core.management import call_command
    table = Table.objects.create(place=Place.objects.create(name='Audit'), number='A1', status='AVAILABLE')
    order = Order.objects.create(user=waiter, table=table, status='PREPARING')
    output = StringIO()
    call_command('audit_loyalty_waiter', stdout=output)
    report = json.loads(output.getvalue())
    assert report['read_only'] is True
    assert report['findings']['available_table_with_live_ticket']['example_ids'] == [table.pk]
    table.refresh_from_db(); order.refresh_from_db()
    assert table.status == 'AVAILABLE' and order.waiter_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != 'postgresql', reason='Requires PostgreSQL row locks')
def test_real_concurrent_create_command_replays_same_order(waiter, product):
    client = client_for(waiter)
    barrier = Barrier(2)
    def run():
        close_old_connections()
        try:
            test_client = Client(**client.defaults)
            barrier.wait(timeout=10)
            response = post(test_client, '/api/waiters/orders/create', {
                'order_type': 'PICKUP', 'items': [{'product_id': product.pk}],
            }, key='concurrent-order')
            return response.status_code, response.content
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        responses = [future.result(timeout=30) for future in futures]
    assert responses[0] == responses[1] and responses[0][0] == 201, responses
    assert Order.objects.count() == 1 and OrderItem.objects.count() == 1


def test_waiter_attendance_follows_shift_not_login_session(waiter, django_capture_on_commit_callbacks, monkeypatch):
    from core.shifts.service import ShiftService
    from hr.services import AttendanceService
    events = []
    monkeypatch.setattr(AttendanceService, 'auto_check_in', lambda user_id: events.append(('in', user_id)))
    monkeypatch.setattr(AttendanceService, 'auto_check_out', lambda user_id: events.append(('out', user_id)))
    with django_capture_on_commit_callbacks(execute=True):
        assert ShiftService.start_shift(waiter.pk)[1] == 201
    shift = Shift.objects.get(user=waiter, status='ACTIVE')
    assert events == [('in', waiter.pk)]
    client = client_for(waiter)
    assert post(client, '/api/waiters/auth-logout').status_code == 200
    assert events == [('in', waiter.pk)]
    with django_capture_on_commit_callbacks(execute=True):
        result, status = ShiftService.end_shift(shift.pk, waiter.pk, '', actor=waiter)
        assert status == 200, result
    assert events == [('in', waiter.pk), ('out', waiter.pk)]


def test_refund_of_yesterdays_sale_does_not_make_paid_count_negative(waiter, product):
    from base.models import OrderRefund
    from base.services.business_day import business_date, day_window
    # Anchor to operating-day windows, not the wall clock: between 03:00 and
    # 07:00 local time "now" is in the quiet gap that stats deliberately exclude.
    today_start, _ = day_window(business_date())
    order = create(waiter, product)
    Order.objects.filter(pk=order.pk).update(status='CANCELED', is_paid=True,
        paid_at=today_start - timedelta(days=1) + timedelta(hours=1))
    refunded_at = today_start + timedelta(hours=1)
    shift = Shift.objects.create(user=waiter, status='ENDED', start_time=refunded_at - timedelta(hours=1),
                                  end_time=refunded_at, branch_id=order.branch_id)
    OrderRefund.objects.create(order=order, shift=shift, cashier=waiter,
        amount=10, cash_amount=10, drawer_cash_amount=10, refunded_at=refunded_at,
        source='ORDER_CANCEL', source_id=f'order-cancel:{order.uuid}', branch_id=order.branch_id)
    result, status = WaiterService.get_stats(waiter.pk)
    assert status == 200
    assert result['data']['paid_count'] == 0
    assert result['data']['cancelled_refund_count'] == 1
    assert result['data']['sales_total'] == '-10.00'
