"""The local (till) edition must expose the core cashbox drawer-expense API.

The expense service itself is covered by alpha_pos_core/cashbox/tests.py; here we
only assert the LOCAL URLconf wires the routes (they resolve to the cashbox views
and are auth-gated, i.e. 401 — not 404, which would mean they were never mounted).
"""
import pytest
from django.test import Client
from django.urls import resolve

pytestmark = pytest.mark.django_db


def test_cashbox_routes_resolve_to_core_views():
    assert resolve('/api/cashbox/categories/').func.__module__ == 'cashbox.views'
    assert resolve('/api/cashbox/shifts/1/expenses/').func.__name__ == 'cashbox_expenses'
    assert resolve('/api/cashbox/recipients/search/').func.__name__ == 'recipient_search'


def test_cashbox_routes_are_mounted_and_gated():
    c = Client()
    # Unauthenticated -> 401/403 (mounted + gated), never 404 (not wired).
    for url in ('/api/cashbox/categories/',
                '/api/cashbox/shifts/1/expenses/',
                '/api/cashbox/recipients/search/'):
        assert c.get(url).status_code in (401, 403), f'{url} not mounted/gated'


def test_cashier_can_record_drawer_expense_end_to_end():
    """A cashier on an active shift records an expense through the local edition's
    URLconf (proves wiring + pos-staff auth + the service all line up)."""
    import secrets
    from datetime import timedelta
    from decimal import Decimal
    from django.utils import timezone
    from base.models import User, Shift
    from base.security.hashing import hash_password
    from base.repositories.session import SessionRepository

    cashier = User.objects.create(
        first_name='Cash', last_name='Ier', email='till@t.local',
        role='CASHIER', status='ACTIVE', password=hash_password('1234'))
    shift = Shift.objects.create(user=cashier, start_time=timezone.now(), status='ACTIVE')

    # Mint a session the same way auth_service.login does (raw token -> sha256 payload).
    raw = secrets.token_hex(32)
    SessionRepository.create(
        user_id=cashier, ip_address='', user_agent='',
        payload=SessionRepository.hash_token(raw),
        expires_at=timezone.now() + timedelta(days=1))

    c = Client(HTTP_AUTHORIZATION=f'Bearer {raw}')
    resp = c.post(
        f'/api/cashbox/shifts/{shift.id}/expenses/',
        data={'amount': '30000', 'comment': 'napkins'},
        content_type='application/json')
    assert resp.status_code == 201, resp.content

    from cashbox.services.drawer import drawer_cash
    # No cash sales yet, so the drawer goes negative by the expense — but the row exists.
    from cashbox.models import CashboxExpense
    assert CashboxExpense.objects.filter(shift=shift, amount=Decimal('30000.00')).exists()
    assert drawer_cash(shift) == Decimal('-30000.00')
