"""Shift control for the local till.

Login creates or resumes the caller's shift. These endpoints remain available
for an explicit start/current check and the explicit close workflow.

Managers can close a selected cashier shift on the bound terminal through the
targeted endpoint. It uses the same branch, unpaid-order, tender-integrity, and
settlement guards as a cashier close.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from base.security.auth import login_required, role_required
from base.security.permissions import manager_required
from core.shifts.service import ShiftService

STAFF_ROLES = ('ADMIN', 'CASHIER', 'MANAGER', 'WAITER')


def _optional_body(request):
    """Lenient parse — start/end take an optional body, so an empty/blank POST
    is valid and yields {} rather than a 400."""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def start_shift(request):
    result, status_code = ShiftService.start_shift(
        user_id=request.user.id,
        shift_template_id=_optional_body(request).get('shift_template_id'),
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@login_required
@role_required(*STAFF_ROLES)
def end_shift(request):
    # Body: { notes?, counted?: { CASH, UZCARD, HUMO, PAYME } } — `counted` is the
    # cashier's blind per-tender count; thread it through so the per-method
    # ShiftPaymentTotal reconciliation rows are created on close.
    body = _optional_body(request)
    result, status_code = ShiftService.end_active_for_user(
        user_id=request.user.id,
        notes=body.get('notes', ''),
        counted=body.get('counted'),
        actor=request.user,
        terminal_origin=True,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
@manager_required
def manager_end_shift(request, shift_id):
    body = _optional_body(request)
    result, status_code = ShiftService.end_shift(
        shift_id=shift_id,
        user_id=request.user.id,
        notes=body.get('notes', ''),
        counted=body.get('counted'),
        actor=request.user,
        require_complete_counted=True,
        terminal_origin=True,
    )
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_GET
@login_required
@role_required(*STAFF_ROLES)
def current_shift(request):
    result, status_code = ShiftService.current_for_user(request.user.id)
    return JsonResponse(result, status=status_code)
