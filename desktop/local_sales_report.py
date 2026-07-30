"""Read-only sales proof view for the temporary desktop compatibility screen.

The old MVP dashboard is used only as a presentation reference.  Every figure
here is derived from the current immutable settlement events and the shared
business-day/tender helpers used by the production POS.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q, Sum
from django.utils import timezone


ZERO = Decimal('0.00')


def _finite_decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal(value) -> Decimal:
    result = _finite_decimal(value if value is not None else 0)
    return result if result is not None else ZERO


def _uzs(value) -> str:
    return str(int(_decimal(value)))


def _name(user) -> str:
    if user is None:
        return ''
    return f'{user.first_name or ""} {user.last_name or ""}'.strip()


def _payment_payload(split, detail):
    result = {
        'cash': _uzs(split.get('cash')),
        'card': _uzs(split.get('card')),
        'payme': _uzs(split.get('payme')),
        'card_detail': {
            method: _uzs(detail.get(method))
            for method in ('UZCARD', 'HUMO', 'CARD')
        },
    }
    unknown = _decimal(split.get('unknown'))
    if unknown:
        result['unknown'] = _uzs(unknown)
    return result


def _grouped_products(window, branch_id):
    from base.models import OrderItem
    from base.services.refund_lines import refund_item_events_in_window
    from base.services.revenue import net_grouped_items

    branch_items = OrderItem.objects.filter(
        is_deleted=False,
        order__is_deleted=False,
        order__branch_id=branch_id,
    )
    sale_items = window.filter(
        branch_items.filter(order__is_paid=True),
        'order__paid_at',
    )
    refund_items = refund_item_events_in_window(window, branch_items)

    products = net_grouped_items(
        sale_items,
        refund_items,
        ('product_id', 'product__name'),
    )
    products.sort(
        key=lambda row: (
            -_decimal(row.get('rev')),
            -(row.get('q') or 0),
            row.get('product_id') or 0,
        ),
    )

    categories = net_grouped_items(
        sale_items,
        refund_items,
        ('product__category_id', 'product__category__name'),
    )
    categories.sort(
        key=lambda row: (
            -_decimal(row.get('rev')),
            row.get('product__category_id') or 0,
        ),
    )

    def serialize(rows, *, category=False):
        output = []
        for row in rows:
            output.append({
                'id': (
                    row.get('product__category_id')
                    if category else row.get('product_id')
                ),
                'name': (
                    row.get('product__category__name') or 'Uncategorized'
                    if category else row.get('product__name') or 'Unknown product'
                ),
                'quantity': int(row.get('q') or 0),
                'revenue': _uzs(row.get('rev')),
                'gross_quantity': int(row.get('gross_q') or 0),
                'refunded_quantity': int(row.get('refund_q') or 0),
                'gross_revenue': _uzs(row.get('gross_rev')),
                'refund_amount': _uzs(row.get('refund_rev')),
            })
        return output

    return serialize(products), serialize(categories, category=True)


def _cashier_rows(window, opened, paid, refunds, expenses):
    from base.models import User
    from base.services.tender import (
        breakdown_sources_for_orders,
        net_breakdown,
    )

    operational = {
        row['cashier_id']: row
        for row in (
            opened.filter(cashier__isnull=False)
            .values('cashier_id')
            .annotate(
                orders=Count('id'),
                cancelled=Count('id', filter=Q(status='CANCELED')),
            )
        )
    }
    settlements = {
        row['cashier_id']: row
        for row in (
            paid.filter(cashier__isnull=False)
            .values('cashier_id')
            .annotate(
                paid_orders=Count('id'),
                gross_revenue=Sum('total_amount'),
            )
        )
    }
    reversals = {
        row['cashier_id']: row
        for row in (
            refunds.filter(cashier__isnull=False)
            .values('cashier_id')
            .annotate(
                refunded_orders=Count('id'),
                refund_amount=Sum('amount'),
                drawer_refunds=Sum('drawer_cash_amount'),
            )
        )
    }
    expense_totals = {
        row['shift__user_id']: row
        for row in (
            expenses.filter(shift__user__isnull=False)
            .values('shift__user_id')
            .annotate(expense_amount=Sum('amount'))
        )
    }

    cashier_ids = (
        set(operational)
        | set(settlements)
        | set(reversals)
        | set(expense_totals)
    )
    users = {
        user.id: user
        for user in User.objects.filter(pk__in=cashier_ids)
    }
    output = []
    for cashier_id in cashier_ids:
        sale_rows = paid.filter(cashier_id=cashier_id)
        refund_rows = refunds.filter(cashier_id=cashier_id)
        split, detail = net_breakdown(sale_rows, refund_rows)
        _, _, drawer_sales = breakdown_sources_for_orders(sale_rows)

        op = operational.get(cashier_id, {})
        settlement = settlements.get(cashier_id, {})
        reversal = reversals.get(cashier_id, {})
        expense = expense_totals.get(cashier_id, {})
        gross = _decimal(settlement.get('gross_revenue'))
        refunded = _decimal(reversal.get('refund_amount'))
        paid_count = int(settlement.get('paid_orders') or 0)
        drawer_refunds = _decimal(reversal.get('drawer_refunds'))
        expense_amount = _decimal(expense.get('expense_amount'))
        output.append({
            'cashier_id': cashier_id,
            'cashier_name': _name(users.get(cashier_id)) or f'User {cashier_id}',
            'orders': int(op.get('orders') or 0),
            'cancelled': int(op.get('cancelled') or 0),
            'paid_orders': paid_count,
            'refunded_orders': int(reversal.get('refunded_orders') or 0),
            'net_revenue': _uzs(gross - refunded),
            'gross_revenue': _uzs(gross),
            'refund_amount': _uzs(refunded),
            'average_paid_order': _uzs(
                (gross - refunded) / paid_count if paid_count else ZERO,
            ),
            'payment_breakdown': _payment_payload(split, detail),
            'drawer_events': {
                'cash_sales': _uzs(drawer_sales),
                'cash_refunds': _uzs(drawer_refunds),
                'cashbox_expenses': _uzs(expense_amount),
                'net_movement': _uzs(
                    drawer_sales - drawer_refunds - expense_amount,
                ),
            },
        })
    output.sort(
        key=lambda row: (
            -int(row['net_revenue']),
            row['cashier_name'].casefold(),
            row['cashier_id'],
        ),
    )
    return output


def _expense_rows(expenses, limit):
    from cashbox.models import CashboxExpense

    rows = (
        expenses.select_related('category', 'shift__user')
        .order_by('-created_at', '-id')[:limit]
    )
    return [{
        'id': expense.id,
        'amount': _uzs(expense.amount),
        'category': expense.category.name if expense.category_id else None,
        'comment': CashboxExpense.visible_comment(expense.comment),
        'created_at': expense.created_at.isoformat(),
        'shift_id': expense.shift_id,
        'cashier_name': (
            _name(expense.shift.user)
            if expense.shift_id and expense.shift else None
        ),
    } for expense in rows]


def _recent_paid_rows(paid, limit):
    rows = (
        paid.select_related('cashier')
        .order_by('-paid_at', '-id')[:limit]
    )
    return [{
        'id': order.id,
        'order_number': order.order_number or order.display_id,
        'cashier_name': _name(order.cashier) or None,
        'amount': _uzs(order.total_amount),
        'payment_method': order.payment_method or 'UNKNOWN',
        'order_type': order.order_type,
        'paid_at': order.paid_at.isoformat() if order.paid_at else None,
    } for order in rows]


def _daily_rows(window, paid, refunds, expenses):
    if window.mode != 'business':
        return []

    labels = [
        (window.date_from + timedelta(days=index)).isoformat()
        for index in range(window.days)
    ]
    rows = {
        label: {
            'date': label,
            'net_revenue': ZERO,
            'gross_revenue': ZERO,
            'refund_amount': ZERO,
            'cashbox_expenses': ZERO,
        }
        for label in labels
    }

    def label_for(moment):
        local = timezone.localtime(moment)
        day = local.date()
        if local.hour < 3:
            day -= timedelta(days=1)
        return day.isoformat()

    for paid_at, amount in paid.values_list('paid_at', 'total_amount'):
        target = rows.get(label_for(paid_at))
        if target is not None:
            target['gross_revenue'] += _decimal(amount)
            target['net_revenue'] += _decimal(amount)
    for refunded_at, amount in refunds.values_list('refunded_at', 'amount'):
        target = rows.get(label_for(refunded_at))
        if target is not None:
            target['refund_amount'] += _decimal(amount)
            target['net_revenue'] -= _decimal(amount)
    for created_at, amount in expenses.values_list('created_at', 'amount'):
        target = rows.get(label_for(created_at))
        if target is not None:
            target['cashbox_expenses'] += _decimal(amount)

    return [{
        key: (_uzs(value) if isinstance(value, Decimal) else value)
        for key, value in rows[label].items()
    } for label in labels]


def _active_shift_rows():
    from core.shifts.service import ShiftService

    service_result = ShiftService.get_active_shifts(actor=None)
    result = (
        service_result[0]
        if isinstance(service_result, tuple) and service_result
        else service_result
    )
    if not isinstance(result, dict) or result.get('success') is not True:
        return {
            'available': False,
            'complete': False,
            'expected_cash_total': None,
            'shifts': [],
            'error': (
                result.get('message')
                if isinstance(result, dict) else 'Shift evidence unavailable'
            ),
        }

    source_rows = result.get('data')
    if not isinstance(source_rows, list) or any(
        not isinstance(row, dict) for row in source_rows
    ):
        return {
            'available': False,
            'complete': False,
            'expected_cash_total': None,
            'shifts': [],
            'error': 'Shift evidence returned an invalid response',
        }
    rows = []
    complete = bool(source_rows)
    total = ZERO
    for shift in source_rows:
        expected = shift.get('expected_cash')
        parsed_expected = _finite_decimal(expected)
        cash_evidence_complete = (
            shift.get('financial_evidence_available') is True
            and shift.get('cash_to_receive_complete') is True
            and parsed_expected is not None
        )
        if not cash_evidence_complete:
            complete = False
        else:
            total += parsed_expected
        rows.append({
            'shift_id': shift.get('id'),
            'cashier': (shift.get('user') or {}).get('name'),
            'started_at': shift.get('start_time'),
            'expected_cash': expected if cash_evidence_complete else None,
            'expected_cash_source': shift.get('expected_cash_source'),
            'payment_mix': shift.get('payment_mix') or {},
            'expenses_total': shift.get('expenses_total'),
            'refunds_total': shift.get('refunds_total'),
            'cash_evidence_complete': cash_evidence_complete,
            'financial_evidence_available': (
                shift.get('financial_evidence_available') is True
            ),
            'cash_to_receive_complete': (
                shift.get('cash_to_receive_complete') is True
            ),
            'tender_attribution_complete': (
                shift.get('tender_attribution_complete') is True
            ),
            'unattributed_expected_amount': shift.get(
                'unattributed_expected_amount',
            ),
            'evidence_issues': shift.get('frozen_tender_evidence_issues') or [],
        })
    return {
        'available': True,
        'complete': complete,
        'expected_cash_total': _uzs(total) if complete else None,
        'shifts': rows,
        'error': None,
    }


def build_local_sales_report(
    date_from=None,
    date_to=None,
    *,
    from_at=None,
    to_at=None,
    recent_limit=20,
):
    """Build the temporary legacy-style report without mutating POS state."""
    from base.models import Order, OrderRefund
    from base.services.business_day import resolve_reporting_window
    from base.services.tender import (
        breakdown_for_orders,
        breakdown_for_refunds,
    )
    from cashbox.models import CashboxExpense
    from django.conf import settings

    branch_id = str(getattr(settings, 'BRANCH_ID', '') or '').strip()
    if not branch_id:
        raise ValueError('The local branch identity is not configured')

    window = resolve_reporting_window(
        date_from,
        date_to,
        from_at=from_at,
        to_at=to_at,
    )
    opened = window.filter(
        Order.objects.filter(is_deleted=False, branch_id=branch_id),
        'created_at',
    )
    paid = window.filter(
        Order.objects.filter(
            is_deleted=False,
            is_paid=True,
            branch_id=branch_id,
        ),
        'paid_at',
    )
    refunds = window.filter(
        OrderRefund.objects.filter(is_deleted=False, branch_id=branch_id),
        'refunded_at',
    )
    expenses = window.filter(
        CashboxExpense.objects.filter(
            is_deleted=False,
            branch_id=branch_id,
        ),
        'created_at',
    )

    order_counts = opened.aggregate(
        orders=Count('id'),
        cancelled=Count('id', filter=Q(status='CANCELED')),
        open=Count(
            'id',
            filter=Q(status__in=['OPEN', 'PREPARING', 'READY']),
        ),
    )
    sale_totals = paid.aggregate(
        paid_orders=Count('id'),
        gross_revenue=Sum('total_amount'),
    )
    refund_totals = refunds.aggregate(
        refunded_orders=Count('id'),
        refund_amount=Sum('amount'),
    )
    expense_total = expenses.aggregate(total=Sum('amount'))['total'] or ZERO

    gross = _decimal(sale_totals.get('gross_revenue'))
    refunded = _decimal(refund_totals.get('refund_amount'))
    paid_count = int(sale_totals.get('paid_orders') or 0)
    sale_split, sale_detail = breakdown_for_orders(paid)
    refund_split, refund_detail = breakdown_for_refunds(refunds)
    split = {
        key: sale_split[key] - refund_split[key]
        for key in ('cash', 'card', 'payme', 'unknown')
    }
    detail = {
        key: sale_detail[key] - refund_detail[key]
        for key in ('UZCARD', 'HUMO', 'CARD')
    }
    products, categories = _grouped_products(window, branch_id)
    units_sold = sum(row['quantity'] for row in products)

    return {
        'generated_at': timezone.now().isoformat(),
        'range': window.metadata(),
        'summary': {
            'net_revenue': _uzs(gross - refunded),
            'gross_revenue': _uzs(gross),
            'refund_amount': _uzs(refunded),
            'orders': int(order_counts.get('orders') or 0),
            'paid_orders': paid_count,
            'refunded_orders': int(
                refund_totals.get('refunded_orders') or 0,
            ),
            'cancelled_orders': int(order_counts.get('cancelled') or 0),
            'open_orders': int(order_counts.get('open') or 0),
            'average_paid_order': _uzs(
                (gross - refunded) / paid_count if paid_count else ZERO,
            ),
            'units_sold': int(units_sold),
            'cashbox_expenses': _uzs(expense_total),
        },
        'payment_breakdown': _payment_payload(split, detail),
        'cashiers': _cashier_rows(
            window,
            opened,
            paid,
            refunds,
            expenses,
        ),
        'top_products': products[:10],
        'categories': categories,
        'expenses': _expense_rows(expenses, recent_limit),
        'recent_paid_orders': _recent_paid_rows(paid, recent_limit),
        'daily': _daily_rows(window, paid, refunds, expenses),
        'active_drawers': _active_shift_rows(),
        'data_quality': {
            'tender_attribution_complete': (
                sale_split['unknown'] == ZERO
                and refund_split['unknown'] == ZERO
            ),
            'unknown_tender_amount': _uzs(split.get('unknown')),
            'unknown_sale_amount': _uzs(sale_split['unknown']),
            'unknown_refund_amount': _uzs(refund_split['unknown']),
            'sales_clock': 'paid_at',
            'refund_clock': 'refunded_at',
            'expense_clock': 'created_at',
            'branch_id': branch_id,
            'soft_deleted_rows_excluded': True,
        },
    }
