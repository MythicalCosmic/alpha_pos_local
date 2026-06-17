"""Client base endpoints (the returning-customer lookup for the till).

GET /clients/lookup?phone=<phone>   -> client + order history + frequent products
GET /clients/<id>                   -> same, by client id
GET /clients?q=<text>               -> type-ahead search over name/phone
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from base.security.auth import login_required, role_required

from customers.services.client_service import ClientService

# Only the till staff may pull a client's history (it exposes other customers' orders).
STAFF_ROLES = ('ADMIN', 'CASHIER', 'MANAGER', 'WAITER')


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def client_lookup(request):
    q = request.GET.get('q')
    if q is not None:
        result, status = ClientService.search(q)
    else:
        result, status = ClientService.lookup(phone=request.GET.get('phone'))
    return JsonResponse(result, status=status)


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def client_detail(request, customer_id):
    result, status = ClientService.lookup(customer_id=customer_id)
    return JsonResponse(result, status=status)
