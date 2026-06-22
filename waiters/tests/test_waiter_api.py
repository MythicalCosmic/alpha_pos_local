"""Waiter convenience endpoints (local edition):
  * send-to-cashier  (WaiterOrderService.request_payment)  — C1
  * per-waiter stats (WaiterService.get_stats)             — C3
  * venue capability/config (WaiterService.get_venue_config) — C5

Service-level tests (the local-edition convention — see customers/tests). The
waiters app is only installed on the local edition, so the whole module is
skipped where it isn't (e.g. a core-only or server test run)."""
from datetime import timedelta

import pytest
from django.apps import apps
from django.utils import timezone

pytestmark = pytest.mark.skipif(
    not apps.is_installed('waiters'),
    reason='waiters app — runs on the local edition',
)


def _waiter(email='waiter1@test.local'):
    from base.models import User
    from base.security.hashing import hash_password
    return User.objects.create(
        first_name='Wai', last_name='Ter', email=email,
        password=hash_password('1234'), role=User.RoleChoices.WAITER,
        status=User.UserStatus.ACTIVE,
    )


def _order(waiter, status='PREPARING', is_paid=False, table=None, total='10.00'):
    from base.models import Order
    return Order.objects.create(
        user=waiter, cashier=waiter, order_type='HALL', status=status,
        is_paid=is_paid, display_id=Order.objects.count() + 1,
        subtotal=total, total_amount=total, table=table,
    )


@pytest.mark.django_db
class TestRequestPayment:
    def test_stamps_once_and_is_idempotent(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        o = _order(w)

        res, st = WaiterOrderService.request_payment(o.id, w.id)
        assert st == 200 and res['success']
        o.refresh_from_db()
        assert o.payment_requested_at is not None
        first = o.payment_requested_at

        # Repeat call must not move the timestamp.
        res2, st2 = WaiterOrderService.request_payment(o.id, w.id)
        assert st2 == 200 and res2['success']
        o.refresh_from_db()
        assert o.payment_requested_at == first

    def test_rejects_paid_order(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        o = _order(w, is_paid=True)
        res, st = WaiterOrderService.request_payment(o.id, w.id)
        assert st == 400 and not res['success']
        o.refresh_from_db()
        assert o.payment_requested_at is None

    def test_rejects_cancelled_order(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        o = _order(w, status='CANCELED')
        res, st = WaiterOrderService.request_payment(o.id, w.id)
        assert st == 400 and not res['success']

    def test_forbids_another_waiters_order(self):
        from waiters.services.order_service import WaiterOrderService
        w1 = _waiter('w1@test.local')
        w2 = _waiter('w2@test.local')
        o = _order(w1)
        res, st = WaiterOrderService.request_payment(o.id, w2.id)
        assert st == 403
        o.refresh_from_db()
        assert o.payment_requested_at is None

    def test_missing_order_404(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        res, st = WaiterOrderService.request_payment(999999, w.id)
        assert st == 404

    def test_surfaced_to_cashier_list(self):
        """The cashier's order list exposes payment_requested_at so the till can
        highlight orders awaiting collection."""
        from waiters.services.order_service import WaiterOrderService
        from customers.services.order_service import CustomerOrderService
        w = _waiter()
        o = _order(w)
        WaiterOrderService.request_payment(o.id, w.id)

        res, st = CustomerOrderService.get_all_orders()
        assert st == 200
        row = next(r for r in res['data']['orders'] if r['id'] == o.id)
        assert row['payment_requested_at'] is not None


@pytest.mark.django_db
class TestWaiterStats:
    def test_counts_and_sales(self):
        from waiters.services.waiter_service import WaiterService
        w = _waiter()
        _order(w, status='COMPLETED', is_paid=True, total='30.00')
        _order(w, status='PREPARING', is_paid=False, total='10.00')
        _order(w, status='CANCELED', total='5.00')

        res, st = WaiterService.get_stats(w.id)
        assert st == 200
        d = res['data']
        assert d['orders_count'] == 3
        assert d['paid_count'] == 1
        assert d['active_count'] == 1        # the unpaid PREPARING one
        assert d['cancelled_count'] == 1
        assert d['sales_total'] == '30.00'   # paid orders only

    def test_scoped_to_the_waiter(self):
        from waiters.services.waiter_service import WaiterService
        w1 = _waiter('w1@test.local')
        w2 = _waiter('w2@test.local')
        _order(w1, is_paid=True, total='99.00')

        res, st = WaiterService.get_stats(w2.id)
        assert st == 200
        assert res['data']['orders_count'] == 0
        assert res['data']['sales_total'] == '0.00'

    def test_tables_served_is_distinct(self):
        from base.models import Place, Table
        from waiters.services.waiter_service import WaiterService
        w = _waiter()
        place = Place.objects.create(name='Main')
        t1 = Table.objects.create(place=place, number='1')
        t2 = Table.objects.create(place=place, number='2')
        _order(w, table=t1)
        _order(w, table=t1)   # same table — counted once
        _order(w, table=t2)
        _order(w)             # no table — not counted

        res, st = WaiterService.get_stats(w.id)
        assert st == 200
        assert res['data']['tables_served'] == 2

    def test_date_window_defaults_to_today(self):
        from base.models import Order
        from waiters.services.waiter_service import WaiterService
        w = _waiter()
        old = _order(w, is_paid=True, total='50.00')
        # auto_now_add stamps "now"; rewrite it to yesterday via .update (which
        # bypasses auto_now_add) so it falls outside the default today window.
        yesterday = timezone.now() - timedelta(days=1)
        Order.objects.filter(pk=old.pk).update(created_at=yesterday)
        _order(w, is_paid=True, total='20.00')   # today

        res, _ = WaiterService.get_stats(w.id)
        assert res['data']['orders_count'] == 1
        assert res['data']['sales_total'] == '20.00'

        res2, _ = WaiterService.get_stats(
            w.id, date_from=yesterday.date().isoformat())
        assert res2['data']['orders_count'] == 2
        assert res2['data']['sales_total'] == '70.00'


@pytest.mark.django_db
class TestVenueConfig:
    def test_returns_methods_types_and_capabilities(self):
        from waiters.services.waiter_service import WaiterService
        res, st = WaiterService.get_venue_config()
        assert st == 200
        d = res['data']
        assert 'waiter_enabled' in d
        # Payment methods are seeded by migration 0021_seed_payment_methods.
        codes = {m['code'] for m in d['payment_methods']}
        assert 'CASH' in codes
        types = {t['code'] for t in d['order_types']}
        assert {'HALL', 'DELIVERY', 'PICKUP'} <= types
        assert d['capabilities']['request_payment'] is True


@pytest.mark.django_db
class TestCreateOrderAttribution:
    def test_waiter_owns_created_order(self, product):
        """Stats + ownership both key off cashier_id == waiter — verify
        create_order sets it (the invariant request_payment / get_stats rely on)."""
        from base.models import Order
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        res, st = WaiterOrderService.create_order(
            user_id=w.id, items=[{'product_id': product.id, 'quantity': 2}],
        )
        assert st == 201
        o = Order.objects.get(pk=res['data']['order_id'])
        assert o.cashier_id == w.id
        assert o.user_id == w.id


# ── Bug-hunt regression coverage ──────────────────────────────────────────────

@pytest.mark.django_db
class TestOwnershipGate:
    """get_owned_order backs the discount / secret-word views' ownership check
    (HIGH IDOR fix): one waiter must not act on another's order."""

    def test_blocks_another_waiter(self):
        from waiters.services.order_service import WaiterOrderService
        w1 = _waiter('w1@test.local')
        w2 = _waiter('w2@test.local')
        o = _order(w1)
        order, denied = WaiterOrderService.get_owned_order(o.id, w2.id)
        assert order is None
        assert denied is not None and denied[1] == 403

    def test_allows_owner(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        o = _order(w)
        order, denied = WaiterOrderService.get_owned_order(o.id, w.id)
        assert denied is None and order.id == o.id

    def test_missing_order_404(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        order, denied = WaiterOrderService.get_owned_order(999999, w.id)
        assert order is None and denied[1] == 404


@pytest.mark.django_db
class TestCreateOrderValidation:
    """Malformed input must return a clean 422, never crash to a 500."""

    def test_items_not_a_list(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        _, st = WaiterOrderService.create_order(user_id=w.id, items='nope')
        assert st == 422

    def test_item_not_a_dict(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        _, st = WaiterOrderService.create_order(user_id=w.id, items=[1, 2, 3])
        assert st == 422

    def test_non_int_product_id(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        _, st = WaiterOrderService.create_order(
            user_id=w.id, items=[{'product_id': 'abc', 'quantity': 1}])
        assert st == 422

    def test_bad_quantity_rejected(self, product):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        for q in (None, 2.5, 0, -1, 'abc'):
            _, st = WaiterOrderService.create_order(
                user_id=w.id, items=[{'product_id': product.id, 'quantity': q}])
            assert st == 422, f'quantity={q!r} should 422'

    def test_int_like_values_accepted(self, product):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        _, st = WaiterOrderService.create_order(
            user_id=w.id, items=[{'product_id': str(product.id), 'quantity': '3'}])
        assert st == 201

    def test_non_int_place_id(self, product):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        _, st = WaiterOrderService.create_order(
            user_id=w.id, items=[{'product_id': product.id, 'quantity': 1}],
            place_id='abc')
        assert st == 422


@pytest.mark.django_db
class TestMarkReadyIdempotent:
    def test_second_call_returns_200(self):
        from waiters.services.order_service import WaiterOrderService
        w = _waiter()
        o = _order(w, status='PREPARING')
        _, st1 = WaiterOrderService.mark_ready(o.id, w.id)
        assert st1 == 200
        res2, st2 = WaiterOrderService.mark_ready(o.id, w.id)
        assert st2 == 200 and res2['success']


@pytest.mark.django_db
class TestStatsExcludesCancelledPaid:
    def test_paid_then_cancelled_not_in_sales(self):
        """A paid order that is later cancelled keeps is_paid=True (the drawer is
        reversed separately) — it must NOT inflate sales_total / paid_count."""
        from waiters.services.waiter_service import WaiterService
        w = _waiter()
        _order(w, status='CANCELED', is_paid=True, total='30.00')
        _order(w, status='COMPLETED', is_paid=True, total='20.00')
        res, st = WaiterService.get_stats(w.id)
        assert st == 200
        d = res['data']
        assert d['sales_total'] == '20.00'
        assert d['paid_count'] == 1
        assert d['cancelled_count'] == 1
        assert d['orders_count'] == 2
