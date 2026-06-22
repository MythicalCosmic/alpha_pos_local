from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from base.helpers.request import parse_json_body, validate_pagination, coerce_quantity
from base.helpers.response import json_response
from base.security.auth import login_required, role_required
from base.security.audit import audit
from base.security.idempotency import idempotent
from base.security.rate_limit import rate_limit, rate_limit_by
from base.models import AuditLog
from waiters.services.order_service import WaiterOrderService

# Routes under /api/waiters/ are reachable with any valid session token —
# WaiterAuthService refuses non-WAITER at login, but a USER or CASHIER
# session minted by a sibling auth endpoint authenticates here just as
# well. Pin every mutation to WAITER or ADMIN so a stolen USER token can't
# create / cancel / modify orders or flip table state through this surface.
WAITER_ROLES = ('WAITER', 'ADMIN')


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def my_orders(request):
    page, per_page = validate_pagination(request)
    status = request.GET.get('status')

    result, status_code = WaiterOrderService.list_my_orders(
        waiter_user_id=request.user.id,
        page=page,
        per_page=per_page,
        status=status,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
@idempotent('orders.create')
def create_order(request):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    items = data.get('items')
    if not items:
        return json_response(({
            "success": False,
            "message": "At least one item is required",
            "errors": {"items": "items is required"}
        }, 422))

    result, status_code = WaiterOrderService.create_order(
        user_id=request.user.id,
        items=items,
        place_id=data.get('place_id'),
        table_id=data.get('table_id'),
        order_type=data.get('order_type', 'HALL'),
        phone_number=data.get('phone_number'),
        description=data.get('description'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def get_order(request, order_id):
    result, status_code = WaiterOrderService.get_order(order_id, request.user.id)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
def add_item(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    product_id = data.get('product_id')
    quantity = coerce_quantity(data.get('quantity', 1))

    if not product_id:
        return json_response(({
            "success": False,
            "message": "Missing product_id",
            "errors": {"product_id": "product_id is required"}
        }, 422))

    # Coerce so a non-numeric product_id returns a clean 422 instead of a 500
    # from the ORM PK lookup deep in the service.
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return json_response(({
            "success": False,
            "message": "Invalid product_id",
            "errors": {"product_id": "product_id must be an integer"}
        }, 422))

    if quantity is None:
        return json_response(({
            "success": False,
            "message": "Invalid quantity",
            "errors": {"quantity": "quantity must be a positive integer"}
        }, 422))

    result, status_code = WaiterOrderService.add_item(
        order_id, product_id, quantity, waiter_user_id=request.user.id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
@role_required(*WAITER_ROLES)
def update_item(request, order_id, item_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    quantity = coerce_quantity(data.get('quantity'))
    if quantity is None:
        return json_response(({
            "success": False,
            "message": "Invalid quantity",
            "errors": {"quantity": "quantity must be a positive integer"}
        }, 422))

    result, status_code = WaiterOrderService.update_item(
        order_id, item_id, quantity, waiter_user_id=request.user.id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
@role_required(*WAITER_ROLES)
def remove_item(request, order_id, item_id):
    result, status_code = WaiterOrderService.remove_item(
        order_id, item_id, waiter_user_id=request.user.id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
def mark_ready(request, order_id):
    result, status_code = WaiterOrderService.mark_ready(order_id, waiter_user_id=request.user.id)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
def request_payment(request, order_id):
    result, status_code = WaiterOrderService.request_payment(
        order_id, waiter_user_id=request.user.id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
@idempotent('orders.cancel')
def cancel_order(request, order_id):
    result, status_code = WaiterOrderService.cancel_order(order_id, waiter_user_id=request.user.id)
    if result.get('success'):
        audit(
            request,
            AuditLog.Action.ORDER_CANCEL,
            target_type='Order',
            target_id=order_id,
            metadata={'role': 'WAITER'},
        )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def places(request):
    result, status_code = WaiterOrderService.list_places()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def tables(request):
    place_id = request.GET.get('place_id')
    if place_id:
        try:
            place_id = int(place_id)
        except (TypeError, ValueError):
            return json_response(({
                "success": False,
                "message": "place_id must be an integer",
            }, 400))

    result, status_code = WaiterOrderService.list_tables(place_id=place_id)
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
@role_required(*WAITER_ROLES)
def table_status(request, table_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    status = data.get('status')
    if not status:
        return json_response(({
            "success": False,
            "message": "Missing status",
            "errors": {"status": "status is required"}
        }, 422))

    result, status_code = WaiterOrderService.update_table_status(
        table_id, status,
        actor_user_id=request.user.id, actor_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
def apply_discount(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    # The discount views call DiscountService directly (it has no ownership
    # concept — it's the shared cashier surface), so we must enforce the same
    # per-order ownership gate every other waiter mutation uses. Without it a
    # waiter could lower/raise another waiter's bill (total_amount tampering).
    _order, denied = WaiterOrderService.get_owned_order(order_id, request.user.id)
    if denied:
        return json_response(denied)
    from discounts.services import DiscountService
    result, status = DiscountService.apply_to_order(order_id, data.get('code', ''), request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
def remove_discount(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    _order, denied = WaiterOrderService.get_owned_order(order_id, request.user.id)
    if denied:
        return json_response(denied)
    order_discount_id = data.get('order_discount_id')
    if order_discount_id is not None:
        # Coerce so a non-numeric id returns 422 instead of a 500 from the PK lookup.
        try:
            order_discount_id = int(order_discount_id)
        except (TypeError, ValueError):
            return json_response(({
                "success": False,
                "message": "Invalid order_discount_id",
                "errors": {"order_discount_id": "must be an integer"}
            }, 422))
    from discounts.services import DiscountService
    result, status = DiscountService.remove_from_order(order_id, order_discount_id, request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@login_required
@role_required(*WAITER_ROLES)
# Throttle so a stolen/compromised waiter session can't brute-force the secret
# word at request-loop speed — matches the cashier surface's protection. Per-IP
# plus a per-order axis so one attacker can't burn the budget across targets.
@rate_limit('discount_secret_word', 5, 60)
@rate_limit_by(
    'discount_secret_word_order', 5, 300,
    lambda r: r.resolver_match.kwargs.get('order_id') if r.resolver_match else None,
)
def check_secret_word(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    _order, denied = WaiterOrderService.get_owned_order(order_id, request.user.id)
    if denied:
        return json_response(denied)
    from discounts.services import DiscountService
    result, status = DiscountService.validate_secret_word(data.get('word', ''), order_id, request.user.id)
    return JsonResponse(result, status=status)
