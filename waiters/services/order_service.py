from django.db import transaction
from django.utils import timezone

from base.repositories import (
    OrderRepository,
    UserRepository,
    PlaceRepository,
    TableRepository,
)
from base.helpers.response import ServiceResponse
from base.helpers.request import coerce_positive_id, coerce_quantity
from base.models import Table, Order
from django.db.models import Q, Count
from base.services.waiter_policy import owns_order
from customers.services.order_service import CustomerOrderService


def _live_items(order):
    """Return live lines while reusing OrderRepository's prefetch cache."""
    return [item for item in order.items.all() if not item.is_deleted]


def _serialize_order_list(order):
    live_items = _live_items(order)
    return {
        "id": order.id,
        "display_id": order.display_id,
        "order_type": order.order_type,
        "phone_number": order.phone_number,
        "description": order.description,
        "place": {
            "id": order.place.id,
            "name": order.place.name,
        }
        if order.place
        else None,
        "table": {
            "id": order.table.id,
            "number": order.table.number,
        }
        if order.table
        else None,
        "customer": {
            "id": order.customer.id,
            "name": order.customer.name,
            "phone": order.customer.phone_number,
            "is_staff": order.customer.is_staff,
        }
        if order.customer_id
        else None,
        "status": order.status,
        "is_paid": order.is_paid,
        "payment_requested_at": (
            order.payment_requested_at.isoformat()
            if order.payment_requested_at
            else None
        ),
        "total_amount": str(order.total_amount or 0),
        # The list queryset is prefetched with `items__product__category`
        # (OrderRepository.get_with_relations) — iterate the cached items
        # instead of `.count()` (extra query per order) and `.values()` (fresh
        # query that bypasses the prefetch). Mirrors the admin list serializer.
        "items_count": len(live_items),
        "items": [
            {
                "id": i.id,
                "product__id": i.product_id,
                "product__name": i.product.name if i.product else None,
                "product__category__id": i.product.category_id if i.product else None,
                "product__category__name": (
                    i.product.category.name
                    if i.product and i.product.category
                    else None
                ),
                "quantity": i.quantity,
                "detail": i.detail,
                "price": i.price,
                "ready_at": i.ready_at,
            }
            for i in live_items
        ],
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


def _serialize_order_detail(order):
    items = []
    for item in _live_items(order):
        items.append(
            {
                "id": item.id,
                "product": {
                    "id": item.product.id,
                    "name": item.product.name,
                    "category": item.product.category.name
                    if item.product.category
                    else None,
                },
                "quantity": item.quantity,
                "price": str(item.price),
                "subtotal": str(item.price * item.quantity),
                "detail": item.detail,
                "ready_at": item.ready_at.isoformat() if item.ready_at else None,
                "is_ready": item.ready_at is not None,
            }
        )

    return {
        "id": order.id,
        "display_id": order.display_id,
        "order_type": order.order_type,
        "phone_number": order.phone_number,
        "description": order.description,
        "place": {
            "id": order.place.id,
            "name": order.place.name,
        }
        if order.place
        else None,
        "table": {
            "id": order.table.id,
            "number": order.table.number,
        }
        if order.table
        else None,
        "waiter_id": order.waiter_id,
        "waiter_shift_id": order.waiter_shift_id,
        "waiter_policy_snapshot": order.waiter_policy_snapshot,
        "cashier": {
            "id": order.cashier.id,
            "name": f"{order.cashier.first_name} {order.cashier.last_name}",
        }
        if order.cashier
        else None,
        "customer": {
            "id": order.customer.id,
            "name": order.customer.name,
            "phone": order.customer.phone_number,
            "is_staff": order.customer.is_staff,
        }
        if order.customer_id
        else None,
        "status": order.status,
        "is_paid": order.is_paid,
        "payment_requested_at": (
            order.payment_requested_at.isoformat()
            if order.payment_requested_at
            else None
        ),
        "total_amount": str(order.total_amount),
        "items": items,
        "items_ready_count": sum(1 for i in items if i["is_ready"]),
        "items_total_count": len(items),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "ready_at": order.ready_at.isoformat() if order.ready_at else None,
    }


def _check_waiter_ownership(order, waiter_user_id):
    if not owns_order(order, waiter_user_id):
        return ServiceResponse.forbidden(
            f"You do not have permission to modify this order. Order #{order.display_id} belongs to another waiter."
        )
    return None


class WaiterOrderService:
    @staticmethod
    def get_owned_order(order_id, waiter_user_id):
        """Load an order and enforce the waiter-ownership gate. Used by the
        discount / secret-word views, which call DiscountService directly and
        would otherwise skip the per-order ownership check every other waiter
        mutation enforces. Returns (order, None) on success, or
        (None, (body, status)) when missing / not owned."""
        order = OrderRepository.get_by_id(order_id)
        if not order:
            return None, ServiceResponse.not_found("Order not found")
        denied = _check_waiter_ownership(order, waiter_user_id)
        if denied:
            return None, denied
        return order, None

    @staticmethod
    def list_my_orders(waiter_user_id, page=1, per_page=20, status=None):
        statuses = status if isinstance(status, list) else ([status] if status else [])
        if any(value not in Order.Status.values for value in statuses):
            return ServiceResponse.validation_error({'status': 'Use a supported order status.'})
        qs = OrderRepository.build_filtered_queryset(
            statuses=status
            if isinstance(status, list)
            else ([status] if status else None),
            order_by="-created_at",
        )

        qs = qs.filter(Q(waiter_id=waiter_user_id) | Q(waiter_id__isnull=True, user_id=waiter_user_id))
        page_obj, paginator = OrderRepository.paginate(qs, page, per_page)
        orders = [_serialize_order_list(o) for o in page_obj.object_list]

        return ServiceResponse.success(
            data={
                "orders": orders,
                "pagination": {
                    "current_page": page_obj.number,
                    "total_pages": paginator.num_pages,
                    "total_orders": paginator.count,
                    "per_page": per_page,
                    "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous(),
                },
            }
        )

    @staticmethod
    def create_order(user_id, items, place_id=None, table_id=None, order_type="HALL",
                     phone_number=None, description=None):
        if not UserRepository.exists(id=user_id, role='WAITER'):
            return ServiceResponse.not_found('Waiter not found')
        if not isinstance(items, list) or not items:
            return ServiceResponse.validation_error({'items': 'Provide a non-empty list of items.'})
        cleaned = []
        for raw in items:
            if not isinstance(raw, dict):
                return ServiceResponse.validation_error({'items': 'Each line must be an object.'})
            product_id = coerce_positive_id(raw.get('product_id'))
            quantity = coerce_quantity(raw.get('quantity', 1))
            if product_id is None or quantity is None:
                return ServiceResponse.validation_error({'items': 'Use positive product IDs and quantities.'})
            cleaned.append({'product_id': product_id, 'quantity': quantity, 'detail': raw.get('detail')})
        references = {}
        for name, value in (('place_id', place_id), ('table_id', table_id)):
            parsed = coerce_positive_id(value) if value not in (None, '') else None
            if value not in (None, '') and parsed is None:
                return ServiceResponse.validation_error({name: 'Use a positive ID.'})
            references[name] = parsed
        return CustomerOrderService.create_order(
            user_id=user_id, items=cleaned, order_type=order_type, phone_number=phone_number,
            description=description, **references,
        )

    @staticmethod
    def get_order(order_id, waiter_user_id):
        order = OrderRepository.get_by_id_with_relations(order_id)
        if not order:
            return ServiceResponse.not_found("Order not found")

        ownership = _check_waiter_ownership(order, waiter_user_id)
        if ownership:
            return ownership

        return ServiceResponse.success(data={"order": _serialize_order_detail(order)})

    @staticmethod
    def add_item(order_id, product_id, quantity, waiter_user_id):
        return CustomerOrderService.add_item_to_order(
            order_id, product_id, quantity, user_id=waiter_user_id, user_role='WAITER',
        )

    @staticmethod
    def update_item(order_id, item_id, quantity, waiter_user_id):
        return CustomerOrderService.update_order_item(
            order_id, item_id, quantity, user_id=waiter_user_id, user_role='WAITER',
        )

    @staticmethod
    def remove_item(order_id, item_id, waiter_user_id):
        return CustomerOrderService.remove_item_from_order(
            order_id, item_id, user_id=waiter_user_id, user_role='WAITER',
        )

    @staticmethod
    def mark_ready(order_id, waiter_user_id):
        return CustomerOrderService.mark_order_ready(
            order_id, user_id=waiter_user_id, user_role='WAITER',
        )

    @staticmethod
    @transaction.atomic
    def request_payment(order_id, waiter_user_id):
        """Waiter "send to cashier": flag the order so the cashier screen knows
        the waiter wants payment collected. Stamps payment_requested_at once
        (idempotent — repeat calls don't move the timestamp). Advisory only: it
        does NOT take payment, change status, or touch the cash register — the
        cashier still rings it up on the till."""
        order = OrderRepository.get_for_update(order_id)
        if not order:
            return ServiceResponse.not_found("Order not found")

        ownership = _check_waiter_ownership(order, waiter_user_id)
        if ownership:
            return ownership

        if order.is_paid:
            return ServiceResponse.error("Order is already paid")

        if order.status == "CANCELED":
            return ServiceResponse.error("Cannot request payment for a cancelled order")

        if order.payment_requested_at is None:
            order.payment_requested_at = timezone.now()
            order.save(update_fields=["payment_requested_at"])

        return ServiceResponse.success(
            data={
                "order_id": order.id,
                "display_id": order.display_id,
                "payment_requested_at": order.payment_requested_at.isoformat(),
            },
            message="Payment requested from cashier",
        )

    @staticmethod
    def cancel_order(order_id, waiter_user_id):
        return CustomerOrderService.update_order_status(
            order_id, 'CANCELED', user_id=waiter_user_id, user_role='WAITER',
            reason='Canceled from waiter app',
        )

    @staticmethod
    def list_places(branch_id=None):
        places = PlaceRepository.get_active().annotate(active_table_count=Count('tables', filter=Q(tables__is_deleted=False, tables__is_active=True)))
        if branch_id:
            places = places.filter(branch_id__in=['', branch_id])
        data = [
            {
                "id": p.id,
                "name": p.name,
                "place_type": p.place_type,
                "capacity": p.capacity,
                "tables_count": p.active_table_count,
            }
            for p in places
        ]
        return ServiceResponse.success(data={"places": data})

    @staticmethod
    def list_tables(place_id=None, branch_id=None):
        if place_id:
            tables = TableRepository.get_for_place(place_id)
        else:
            tables = TableRepository.get_active()

        if branch_id:
            tables = tables.filter(branch_id__in=['', branch_id], place__branch_id__in=['', branch_id])
        data = [
            {
                "id": t.id,
                "number": t.number,
                "capacity": t.capacity,
                "status": t.status,
                "is_active": t.is_active,
                "place": {
                    "id": t.place.id,
                    "name": t.place.name,
                }
                if t.place
                else None,
            }
            for t in tables.select_related("place")
        ]
        return ServiceResponse.success(data={"tables": data})

    @staticmethod
    @transaction.atomic
    def update_table_status(table_id, status, actor_user_id=None, actor_role=None):
        from base.services.order_floor import live_orders
        if status not in Table.Status.values:
            return ServiceResponse.validation_error({'status': 'Choose a valid table status.'})
        table = Table.objects.select_for_update().filter(pk=table_id, is_deleted=False, is_active=True).first()
        from base.services.branch_scope import resolve_actor_branch
        actor = UserRepository.get_by_id(actor_user_id)
        branch = resolve_actor_branch(actor) if actor else None
        if (not table or not actor or table.branch_id not in ('', branch) or
                not table.place or not table.place.is_active or table.place.is_deleted or
                table.place.branch_id not in ('', branch)):
            return ServiceResponse.not_found('Table not found')
        active = live_orders(table_id)
        if actor_role != 'ADMIN' and not active.filter(
            Q(waiter_id=actor_user_id) | Q(waiter_id__isnull=True, user_id=actor_user_id),
        ).exists():
            return ServiceResponse.forbidden('You can only update a table you are serving')
        has_ticket = active.exists()
        if (status == 'OCCUPIED') != has_ticket:
            return ({'success': False, 'code': 'TABLE_STATE_CONFLICT',
                     'message': 'Table status must match its active tickets.'}, 409)
        table.status = status
        table.save(update_fields=['status'])
        return ServiceResponse.success(data={'id': table.pk, 'number': table.number, 'status': table.status})
