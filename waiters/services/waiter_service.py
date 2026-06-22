"""Waiter convenience reads: today's personal stats (C3) and the venue
capability/config payload (C5). Both are read-only and scoped to the local
edition (the waiter app talks to the till over the LAN)."""
from datetime import datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from base.helpers.response import ServiceResponse
from base.models import AppSettings, Order, PaymentMethodConfig


def _parse_date(value):
    """'YYYY-MM-DD' -> date, or None if absent/malformed (caller defaults it)."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except (ValueError, TypeError, AttributeError):
        return None


class WaiterService:

    @staticmethod
    def get_stats(waiter_user_id, date_from=None, date_to=None):
        """Per-waiter tallies for a date window (defaults to today, in the
        server's local timezone). A waiter "owns" the orders they created —
        those carry cashier_id == waiter_user_id (see WaiterOrderService.
        create_order) — so we scope by cashier_id, mirroring the admin
        get_cashier_stats aggregation. `sales_total` counts only paid orders
        (money actually collected); active/cancelled are status tallies."""
        today = timezone.localdate()
        d_from = _parse_date(date_from) or today
        d_to = _parse_date(date_to) or today
        if d_to < d_from:
            d_from, d_to = d_to, d_from

        # __date__range honours the active timezone under USE_TZ — no manual
        # make_aware (which would crash if USE_TZ were ever False).
        qs = Order.objects.filter(
            is_deleted=False,
            cashier_id=waiter_user_id,
            created_at__date__gte=d_from,
            created_at__date__lte=d_to,
        )

        # Cancelling a paid order reverses the drawer cash but does NOT reset
        # is_paid, so the money tallies must also exclude CANCELED to match the
        # authoritative shift/cash-reconciliation aggregation (core/shifts/
        # service.py pairs is_paid=True with .exclude(status='CANCELED')).
        paid_and_live = Q(is_paid=True) & ~Q(status='CANCELED')
        agg = qs.aggregate(
            orders_count=Count('id'),
            paid_count=Count('id', filter=paid_and_live),
            cancelled_count=Count('id', filter=Q(status='CANCELED')),
            active_count=Count(
                'id', filter=Q(status__in=('PREPARING', 'READY'), is_paid=False),
            ),
            sales_total=Sum('total_amount', filter=paid_and_live),
        )
        # Distinct tables the waiter served in the window (HALL orders only carry
        # a table); excludes table-less DELIVERY/PICKUP.
        tables_served = (
            qs.exclude(table__isnull=True).values('table_id').distinct().count()
        )
        # SUM drops the field's 2-dp scale (SQLite returns Decimal('20')), so
        # quantize to match the money formatting everywhere else in the API.
        sales_total = (agg['sales_total'] or Decimal('0')).quantize(Decimal('0.01'))

        return ServiceResponse.success(data={
            'date_from': d_from.isoformat(),
            'date_to': d_to.isoformat(),
            'orders_count': agg['orders_count'] or 0,
            'paid_count': agg['paid_count'] or 0,
            'active_count': agg['active_count'] or 0,
            'cancelled_count': agg['cancelled_count'] or 0,
            'tables_served': tables_served,
            'sales_total': str(sales_total),
        })

    @staticmethod
    def get_venue_config():
        """Capability/branding payload the waiter app caches after login: which
        order types and payment methods exist, plus feature flags. Mirrors the
        cashier payment-screen config (PaymentMethodConfig) so the waiter app
        renders the same method set as the till."""
        app_settings = AppSettings.load()
        methods = [
            {
                'code': m.code,
                'label': m.label,
                'color': m.color,
                'icon': m.icon,
            }
            for m in PaymentMethodConfig.objects.filter(is_active=True)
        ]
        return ServiceResponse.success(data={
            'waiter_enabled': app_settings.waiter_enabled,
            'order_types': [
                {'code': code, 'label': label}
                for code, label in Order.OrderType.choices
            ],
            'payment_methods': methods,
            'currency': 'UZS',
            'capabilities': {
                'discounts': True,
                'secret_word': True,
                'tables': True,
                'split_payment': True,
                'request_payment': True,
            },
        })
