"""Client base — look up a returning client by phone and surface their history.

The till captures a client (name + phone) on every order via Customer.resolve;
this service is the read side: given a phone (or id) it returns the unified
base.Customer plus their order history, spend stats, and most-ordered products,
so the cashier sees a returning customer's past orders/foods at a glance.
"""
from django.db.models import Count, Sum, Max

from base.models import Customer, OrderItem, OrderRefund
from base.repositories import OrderRepository
from base.helpers.response import ServiceResponse

from customers.services.order_service import _serialize_order_list


def _client_dict(c):
    return {
        'id': c.id,
        'name': c.name,
        'phone': c.phone_number,
        'telegram_id': c.telegram_id,
        'is_staff': c.is_staff,
        'created_at': c.created_at.isoformat() if c.created_at else None,
    }


class ClientService:

    @staticmethod
    def find(phone=None, customer_id=None):
        """Find-only (never creates). Matches exact phone, then normalized phone."""
        qs = Customer.objects.filter(is_deleted=False)
        if customer_id:
            return qs.filter(id=customer_id).first()
        phone = (str(phone).strip() if phone else '')
        if not phone:
            return None
        c = qs.filter(phone_number=phone).order_by('id').first()
        if c:
            return c
        norm = Customer.normalize_phone(phone)
        if norm:
            for cid, cphone in qs.exclude(phone_number='').values_list('id', 'phone_number'):
                if Customer.normalize_phone(cphone) == norm:
                    return qs.filter(id=cid).first()
        return None

    @staticmethod
    def lookup(phone=None, customer_id=None, history_limit=20, fav_limit=8):
        c = ClientService.find(phone=phone, customer_id=customer_id)
        if not c:
            return ServiceResponse.not_found('Client not found')

        orders_qs = OrderRepository.build_filtered_queryset(customer_id=c.id)
        stats = orders_qs.aggregate(count=Count('id'), last=Max('created_at'))
        gross_spent = (orders_qs.filter(is_paid=True)
                       .aggregate(total=Sum('total_amount'))['total'] or 0)
        refunded = (OrderRefund.objects.filter(
            is_deleted=False, order__customer_id=c.id,
        ).aggregate(total=Sum('amount'))['total'] or 0)
        spent = gross_spent - refunded
        recent = [_serialize_order_list(o) for o in orders_qs[:history_limit]]

        # Most-ordered products across this client's whole history ("their foods").
        fav_sales = list(OrderItem.objects
               .filter(
                   is_deleted=False,
                   order__customer_id=c.id,
                   order__is_deleted=False,
                   order__is_paid=True,
               )
               .values('product_id', 'product__name')
               .annotate(times=Count('id'), qty=Sum('quantity'))
        )
        from base.services.refund_lines import (
            REFUND_EVENT_ALIAS, refund_item_events, refund_line_quantity,
        )
        fav_refunds = list(refund_item_events(
            item_queryset=OrderItem.objects.filter(order__customer_id=c.id),
            source=OrderRefund.Source.ORDER_CANCEL,
        ).values('product_id', 'product__name').annotate(
            times=Count(f'{REFUND_EVENT_ALIAS}__id', distinct=True),
            qty=Sum(refund_line_quantity(REFUND_EVENT_ALIAS)),
        ))
        by_product = {
            row['product_id']: dict(row) for row in fav_sales
        }
        for row in fav_refunds:
            target = by_product.setdefault(row['product_id'], {
                'product_id': row['product_id'],
                'product__name': row['product__name'],
                'times': 0,
                'qty': 0,
            })
            target['times'] = (target.get('times') or 0) - (row['times'] or 0)
            target['qty'] = (target.get('qty') or 0) - (row['qty'] or 0)
        fav = sorted(
            by_product.values(),
            key=lambda row: (-(row.get('times') or 0), -(row.get('qty') or 0)),
        )[:fav_limit]
        favorites = [{
            'product_id': f['product_id'],
            'name': f['product__name'],
            'times_ordered': f['times'],
            'total_qty': f['qty'],
        } for f in fav]

        return ServiceResponse.success(data={
            'client': _client_dict(c),
            'stats': {
                'order_count': stats['count'] or 0,
                'total_spent': str(spent or 0),
                'gross_spent': str(gross_spent or 0),
                'refund_amount': str(refunded or 0),
                'last_order_at': stats['last'].isoformat() if stats['last'] else None,
            },
            'orders': recent,
            'frequent_products': favorites,
        })

    @staticmethod
    def search(q, limit=20):
        """Type-ahead over name + phone for the cashier's client picker."""
        q = (q or '').strip()
        qs = Customer.objects.filter(is_deleted=False)
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(phone_number__icontains=q))
        return ServiceResponse.success(data={
            'clients': [_client_dict(c) for c in qs.order_by('-id')[:limit]],
        })
