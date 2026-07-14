"""Waiter convenience reads: today's personal stats (C3) and the venue
capability/config payload (C5). Both are read-only and scoped to the local
edition (the waiter app talks to the till over the LAN)."""
from datetime import datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from base.helpers.response import ServiceResponse
from base.models import AppSettings, Order, OrderRefund, PaymentMethodConfig


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
        from base.services.business_day import business_date, range_window

        today = business_date()
        d_from = _parse_date(date_from) or today
        d_to = _parse_date(date_to) or today
        if d_to < d_from:
            d_from, d_to = d_to, d_from

        window_start, window_end = range_window(d_from, d_to)
        qs = Order.objects.filter(
            is_deleted=False,
            cashier_id=waiter_user_id,
            created_at__gte=window_start,
            created_at__lt=window_end,
        )

        # Operational counts use created_at/status. Money uses two immutable
        # clocks: gross sales at paid_at and negative refunds at refunded_at.
        agg = qs.aggregate(
            orders_count=Count('id'),
            cancelled_count=Count('id', filter=Q(status='CANCELED')),
            active_count=Count(
                'id', filter=Q(status__in=('PREPARING', 'READY'), is_paid=False),
            ),
        )
        settled = Order.objects.filter(
            is_deleted=False,
            cashier_id=waiter_user_id,
            is_paid=True,
            paid_at__gte=window_start,
            paid_at__lt=window_end,
        ).aggregate(
            paid_count=Count('id'), sales_total=Sum('total_amount'),
        )
        refunds = OrderRefund.objects.filter(
            is_deleted=False,
            cashier_id=waiter_user_id,
            refunded_at__gte=window_start,
            refunded_at__lt=window_end,
        ).aggregate(
            refund_count=Count('id'),
            cancelled_refund_count=Count(
                'id', filter=Q(source=OrderRefund.Source.ORDER_CANCEL),
            ),
            refund_total=Sum('amount'),
        )
        # Distinct tables the waiter served in the window (HALL orders only carry
        # a table); excludes table-less DELIVERY/PICKUP.
        tables_served = (
            qs.exclude(table__isnull=True).values('table_id').distinct().count()
        )
        # SUM drops the field's 2-dp scale (SQLite returns Decimal('20')), so
        # quantize to match the money formatting everywhere else in the API.
        gross_total = (settled['sales_total'] or Decimal('0')).quantize(
            Decimal('0.01'),
        )
        refund_total = (refunds['refund_total'] or Decimal('0')).quantize(
            Decimal('0.01'),
        )
        sales_total = gross_total - refund_total

        return ServiceResponse.success(data={
            'date_from': d_from.isoformat(),
            'date_to': d_to.isoformat(),
            'orders_count': agg['orders_count'] or 0,
            'paid_count': (
                (settled['paid_count'] or 0)
                - (refunds['cancelled_refund_count'] or 0)
            ),
            'refund_count': refunds['refund_count'] or 0,
            'active_count': agg['active_count'] or 0,
            'cancelled_count': agg['cancelled_count'] or 0,
            'tables_served': tables_served,
            'sales_total': str(sales_total),
            'gross_sales_total': str(gross_total),
            'refund_total': str(refund_total),
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
