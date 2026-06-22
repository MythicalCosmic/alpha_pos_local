"""Waiter convenience endpoints (C2/C3/C5): menu aliases under /api/waiters/,
today's per-waiter stats, and the venue capability/config payload.

The menu aliases delegate to the customer product/category services — the same
data the cashier till serves — so the waiter app has a single base URL
(/api/waiters/) instead of mixing surfaces. Both apps live on the local edition,
so the customer services are always importable here."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from base.helpers.request import safe_page, safe_per_page
from base.security.auth import login_required, role_required
from waiters.services.waiter_service import WaiterService

# Same gate as the order surface: a WAITER session authenticates here, but pin
# to WAITER/ADMIN so a stolen USER/CASHIER token can't read waiter stats.
WAITER_ROLES = ('WAITER', 'ADMIN')


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def menu_products(request):
    from customers.services.product_service import CustomerProductService
    popular = request.GET.get('popular', 'true').lower() not in ('false', '0', 'no')
    result, status_code = CustomerProductService.get_all_products(
        page=safe_page(request),
        per_page=safe_per_page(request, 50),
        search=request.GET.get('search'),
        category_ids=request.GET.get('category_ids'),
        order_by=request.GET.get('order_by', '-created_at'),
        popular=popular,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def menu_categories(request):
    from customers.services.category_service import CustomerCategoryService
    # The waiter app only needs the live (active) menu categories.
    result, status_code = CustomerCategoryService.get_active_categories()
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def stats(request):
    result, status_code = WaiterService.get_stats(
        waiter_user_id=request.user.id,
        date_from=request.GET.get('date_from'),
        date_to=request.GET.get('date_to'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*WAITER_ROLES)
def venue_config(request):
    result, status_code = WaiterService.get_venue_config()
    return JsonResponse(result, status=status_code)
