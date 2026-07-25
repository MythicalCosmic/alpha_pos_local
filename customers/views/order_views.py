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
from customers.services.order_service import (
    CustomerOrderService, _serialize_order_detail,
)
from customers.services import print_service
from customers.requests.order_requests import create_order_request

# Roles permitted to advance an order beyond the customer's own scope: take
# payment, mark items / orders ready, force a status transition, or apply a
# discount at the till. USER (the customer-facing role) must never do these,
# otherwise a customer with their own order can self-issue a CASH receipt
# (and inflate the cash register) or skip the kitchen workflow.
STAFF_ROLES = ('ADMIN', 'CASHIER', 'MANAGER', 'WAITER')


@csrf_exempt
@require_GET
@login_required
def list_orders(request):
    page, per_page = validate_pagination(request)
    payment_status = request.GET.get('payment_status')
    statuses = request.GET.get('statuses')
    category_ids = request.GET.get('category_ids')
    user_id = request.GET.get('user_id')
    cashier_id = request.GET.get('cashier_id')
    order_by = request.GET.get('order_by', '-created_at')

    # Only staff (ADMIN/CASHIER/MANAGER/WAITER) can pull other users' orders or
    # scope by client; everyone else is pinned to their own. Without this, a USER
    # token could pass ?user_id=N / ?customer_id=N to enumerate others' orders.
    customer_id = request.GET.get('customer_id') if request.user.role in STAFF_ROLES else None
    if request.user.role not in STAFF_ROLES:
        user_id = str(request.user.id)
        cashier_id = None

    result, status_code = CustomerOrderService.get_all_orders(
        page=page, per_page=per_page, payment_status=payment_status,
        statuses=statuses, category_ids=category_ids, user_id=user_id,
        cashier_id=cashier_id, order_by=order_by, customer_id=customer_id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
def get_order(request, order_id):
    result, status_code = CustomerOrderService.get_order_by_id(
        order_id, user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


def _print_job_payload(job):
    if job is None:
        return None
    # Use the same authoritative detail projection as GET /orders/<id> so a
    # printer cannot silently omit modifiers, the structured delivery address,
    # courier assignment, or the order_origin that authorized auto-printing.
    order = _serialize_order_detail(job.order)
    return {
        'id': job.pk,
        'claim_token': str(job.claim_token),
        'attempt': job.attempt_count,
        'lease_expires_at': job.lease_expires_at.isoformat(),
        'order': order,
    }


@csrf_exempt
@require_POST
@login_required
@role_required('ADMIN', 'MANAGER', 'CASHIER')
def claim_receipt_print(request):
    """Lease the next unprinted Telegram receipt to this authenticated POS.

    Empty queues return HTTP 200 with ``job: null`` so a frontend poller does
    not need to treat normal idleness as an error. The same session receives
    the same active claim on retry until it acknowledges, fails, or the lease
    expires.
    """
    job = print_service.claim_next(session_key=request.session_key)
    return JsonResponse({
        'success': True,
        'data': {
            'job': _print_job_payload(job),
            'delivery_contract': 'durable-claim-ack-v1',
        },
    })


@csrf_exempt
@require_POST
@login_required
@role_required('ADMIN', 'MANAGER', 'CASHIER')
def acknowledge_receipt_print(request, claim_token):
    """Acknowledge paper/spool success; exact retries are idempotent."""
    try:
        job, already_printed = print_service.acknowledge(
            claim_token=claim_token, session_key=request.session_key,
        )
    except print_service.PrintClaimNotFound:
        return JsonResponse(
            {'success': False, 'message': 'print claim not found'}, status=404,
        )
    except print_service.PrintClaimConflict:
        return JsonResponse(
            {'success': False, 'message': 'print claim is no longer owned'},
            status=409,
        )
    return JsonResponse({
        'success': True,
        'data': {
            'job_id': job.pk,
            'state': job.state,
            'printed_at': job.printed_at.isoformat(),
            'already_printed': already_printed,
        },
    })


@csrf_exempt
@require_POST
@login_required
@role_required('ADMIN', 'MANAGER', 'CASHIER')
def fail_receipt_print(request, claim_token):
    """Report definite printer failure and make the job retryable."""
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    try:
        job = print_service.release_failed(
            claim_token=claim_token,
            session_key=request.session_key,
            error=data.get('error') or data.get('message') or '',
        )
    except print_service.PrintClaimNotFound:
        return JsonResponse(
            {'success': False, 'message': 'print claim not found'}, status=404,
        )
    except print_service.PrintClaimConflict:
        return JsonResponse(
            {'success': False, 'message': 'print claim is no longer owned'},
            status=409,
        )
    return JsonResponse({
        'success': True,
        'data': {'job_id': job.pk, 'state': job.state, 'retryable': True},
    })


@csrf_exempt
@require_POST
@login_required
@idempotent('orders.create')
def create_order(request):
    data, error = create_order_request(request)
    if error:
        return json_response(error)

    user = request.user
    cashier_id = user.id if user.role in ('CASHIER', 'MANAGER') else None

    # Attach a client to the order. An explicit customer_id wins; otherwise build
    # the unified client from a {name, phone} object OR the order's own
    # phone_number field. Customer.resolve converges by phone (so a returning
    # client is the same row across desktop + Telegram) and creates one even when
    # only a phone — no name — is given. Walk-ins with neither stay client-less.
    from base.models import Customer

    customer_id = data.get('customer_id')
    cdict = data.get('customer') if isinstance(data.get('customer'), dict) else {}
    supplied_phone = (
        data.get('phone_number') or cdict.get('phone') or
        cdict.get('phone_number') or ''
    )
    order_phone = Customer.normalize_phone(supplied_phone) or None
    if not customer_id:
        name = (cdict.get('name') or '').strip()
        if order_phone or name:
            client, _ = Customer.resolve(
                phone=order_phone, name=name or None,
            )
            customer_id = client.id

    # New clients send a clean note separately while old clients only send
    # description (historically address + note). Presence, not truthiness,
    # decides precedence so an explicit empty order_note can clear stale text.
    description = (
        data.get('order_note') if 'order_note' in data
        else data.get('description')
    )

    result, status_code = CustomerOrderService.create_order(
        user_id=user.id,
        items=data['items'],
        order_type=data.get('order_type', 'HALL'),
        phone_number=order_phone,
        delivery_address=data.get('delivery_address'),
        description=description,
        cashier_id=cashier_id,
        delivery_person_id=data.get('delivery_person_id'),
        customer_id=customer_id,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
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

    if quantity is None:
        return json_response(({
            "success": False,
            "message": "Invalid quantity",
            "errors": {"quantity": "quantity must be a positive integer"}
        }, 422))

    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.add_item_to_order(
        order_id, product_id, quantity, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
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

    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.update_order_item(
        order_id, item_id, quantity, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def remove_item(request, order_id, item_id):
    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.remove_item_from_order(
        order_id, item_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
@role_required(*STAFF_ROLES)
def update_status(request, order_id):
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

    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.update_order_status(
        order_id, status, cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required
@role_required(*STAFF_ROLES)
def update_order_type(request, order_id):
    """Change an existing order's type (HALL / DELIVERY / PICKUP)."""
    data, error = parse_json_body(request)
    if error:
        return json_response(error)

    order_type = data.get('order_type')
    if not order_type:
        return json_response(({
            "success": False,
            "message": "Missing order_type",
            "errors": {"order_type": "order_type is required"}
        }, 422))

    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.update_order_type(
        order_id, order_type, cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
@idempotent(
    'orders.pay',
    fallback_key_from_request=True,
    expose_action_id=True,
    recover_inflight_after_seconds=5,
)
def pay_order(request, order_id):
    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    body, error = parse_json_body(request)
    if error:
        return json_response(error)

    payment_kwargs = {}
    if 'payment_method' in body:
        payment_kwargs['payment_method'] = body['payment_method']
    if 'payments' in body:
        payment_kwargs['payments'] = body['payments']

    result, status_code = CustomerOrderService.mark_as_paid(
        order_id, cashier_id,
        user_id=request.user.id, user_role=request.user.role,
        discount_percent=body.get('discount_percent', 0),
        payment_action_id=getattr(
            request, 'idempotency_action_id', None,
        ),
        **payment_kwargs,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def mark_ready(request, order_id):
    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.mark_order_ready(
        order_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def mark_item_ready(request, order_id, item_id):
    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.mark_item_ready(
        order_id, item_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def unmark_item_ready(request, order_id, item_id):
    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.unmark_item_ready(
        order_id, item_id, cashier_id=cashier_id,
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@idempotent('orders.cancel')
def cancel_order(request, order_id):
    # Optional cancellation reason (BE-1). Recorded on the audit trail so the
    # inkassa/stats reports can attribute who cancelled, when, and why.
    reason = None
    if request.body:
        body, _ = parse_json_body(request)
        if body:
            reason = (body.get('reason') or '').strip()[:255] or None

    cashier_id = request.user.id if request.user.role in ('CASHIER', 'MANAGER') else None
    result, status_code = CustomerOrderService.update_order_status(
        order_id, 'CANCELED', cashier_id,
        user_id=request.user.id, user_role=request.user.role,
        reason=reason or '',
    )
    if result.get('success'):
        audit(
            request,
            AuditLog.Action.ORDER_CANCEL,
            target_type='Order',
            target_id=order_id,
            metadata={'role': request.user.role, 'reason': reason},
        )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def client_display(request):
    result, status_code = CustomerOrderService.get_client_display_orders()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def chef_display(request):
    result, status_code = CustomerOrderService.get_chef_display_orders()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def list_couriers(request):
    result, status_code = CustomerOrderService.list_couriers()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def assign_courier(request, order_id):
    """Assign / replace / clear the courier on an existing order."""
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    result, status_code = CustomerOrderService.assign_courier(
        order_id, data.get('delivery_person_id'),
        user_id=request.user.id, user_role=request.user.role,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
@login_required
@role_required(*STAFF_ROLES)
def update_order_details(request, order_id):
    """Partially edit order contact, delivery address, note, or courier."""
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    kwargs = {}
    if 'delivery_person_id' in data:
        kwargs['delivery_person_id'] = data.get('delivery_person_id')
    if 'delivery_address' in data:
        kwargs['delivery_address'] = data.get('delivery_address')
    description = (
        data.get('order_note') if 'order_note' in data
        else data.get('description')
    )
    result, status_code = CustomerOrderService.update_order_details(
        order_id,
        phone_number=data.get('phone_number'),
        description=description,
        user_id=request.user.id, user_role=request.user.role,
        **kwargs,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def apply_discount(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    from discounts.services import DiscountService
    result, status = DiscountService.apply_to_order(order_id, data.get('code', ''), request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def remove_discount(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    from discounts.services import DiscountService
    result, status = DiscountService.remove_from_order(order_id, data.get('order_discount_id'), request.user.id)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
# Throttle so a compromised cashier session can't brute-force the secret word
# at request-loop speed. Per-order key adds a second axis so a single attacker
# can't burn the per-IP budget against multiple targets.
@rate_limit('discount_secret_word', 5, 60)
@rate_limit_by(
    'discount_secret_word_order', 5, 300,
    lambda r: r.resolver_match.kwargs.get('order_id') if r.resolver_match else None,
)
def check_secret_word(request, order_id):
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    from discounts.services import DiscountService
    result, status = DiscountService.validate_secret_word(data.get('word', ''), order_id, request.user.id)
    return JsonResponse(result, status=status)
