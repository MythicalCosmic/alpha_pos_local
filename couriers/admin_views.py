"""Back-office endpoints the desktop POS calls to dispatch a delivery to a
courier. Session-auth'd as staff (ADMIN/MANAGER), mounted under
/api/admins/couriers/."""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import secrets

from django.conf import settings

from base.helpers.request import parse_json_body
from base.security.permissions import manager_required
from base.models import Order, User
from base.security.hashing import hash_password

from couriers.models import Courier
from couriers import services


@require_GET
@manager_required
def couriers_list(request):
    """Couriers available for assignment (the desktop's picker)."""
    rows = []
    for c in Courier.objects.select_related('user').all():
        rows.append({
            'id': c.code, 'pk': c.id, 'name': c.full_name, 'phone': c.phone,
            'vehicle': c.vehicle, 'plate': c.plate, 'online': c.online,
            'rating': float(c.rating), 'branch': c.branch_name or c.branch_id,
        })
    return JsonResponse({'success': True, 'data': rows})


@csrf_exempt
@require_POST
@manager_required
def assign_order(request):
    """POST /api/admins/couriers/assign
    { order_id, courier (code) | courier_id (pk), fee, addr_text, addr_landmark,
      addr_lat, addr_lng, distance_km } -> emits order.assigned to the courier."""
    data, error = parse_json_body(request)
    if error:
        return JsonResponse(error[0], status=error[1])

    order_id = data.get('order_id')
    if not order_id:
        return JsonResponse({'success': False, 'message': 'order_id required'}, status=400)
    order = get_object_or_404(Order, pk=order_id)

    courier = None
    if data.get('courier_id'):
        courier = Courier.objects.filter(pk=data['courier_id']).first()
    elif data.get('courier'):
        courier = Courier.objects.filter(code=data['courier']).first()
    if not courier:
        return JsonResponse({'success': False, 'message': 'courier not found'}, status=404)

    assignment = services.assign(
        order, courier,
        fee=data.get('fee', 0),
        addr_text=data.get('addr_text', ''),
        addr_landmark=data.get('addr_landmark', ''),
        addr_lat=data.get('addr_lat'),
        addr_lng=data.get('addr_lng'),
        distance_km=data.get('distance_km'),
    )
    return JsonResponse({'success': True, 'message': 'assigned',
                         'data': {'order_id': order.id, 'courier': courier.code,
                                  'step': assignment.step}})


# --------------------------------------------------------------------------- #
# provisioning: create a courier + login QR (net-new on local)
# --------------------------------------------------------------------------- #
def _next_courier_code():
    """Next stable, unique human-facing courier code (CR-001, CR-002, ...)."""
    n = Courier.objects.count() + 1
    while Courier.objects.filter(code=f'CR-{n:03d}').exists():
        n += 1
    return f'CR-{n:03d}'


def _courier_qr(request, courier, password):
    """The login-QR payload the desktop renders. token = 'phone:password' — the
    exact scheme couriers.views.courier_login decodes from a scanned {qr}."""
    server = request.build_absolute_uri('/').rstrip('/')
    return {
        'courier': {'id': courier.code, 'pk': courier.id,
                    'name': courier.full_name, 'phone': courier.phone},
        'password': password,     # plaintext, for the manager to relay/print once
        'qr': {'v': 1, 'type': 'courier_login', 'server': server,
               'token': f'{courier.phone}:{password}'},
    }


@csrf_exempt
@require_POST
@manager_required
def create_courier(request):
    """POST /api/couriers/create  {first_name,last_name,phone} -> provision a
    courier (base.User + Courier) with a login credential and return the login-QR.
    The rider scans the QR; the app POSTs {qr: token} to /auth/courier/login."""
    data, error = parse_json_body(request)
    if error:
        return JsonResponse(error[0], status=error[1])
    first = (data.get('first_name') or '').strip()[:50]
    last = (data.get('last_name') or '').strip()[:50]
    phone = (data.get('phone') or '').strip()[:24]
    if not phone:
        return JsonResponse({'success': False, 'message': 'phone required'}, status=400)
    if Courier.objects.filter(phone=phone).exists():
        return JsonResponse({'success': False,
                             'message': 'A courier with this phone already exists'}, status=409)
    password = secrets.token_urlsafe(6)      # short, manager-relayable
    user = User.objects.create(
        first_name=first or 'Courier', last_name=last,
        email=f'courier.{phone}@local',
        role=getattr(User.RoleChoices, 'CASHIER', 'CASHIER'), status='ACTIVE',
        password=hash_password(password))
    courier = Courier.objects.create(
        user=user, code=_next_courier_code(), first_name=first or 'Courier',
        last_name=last, phone=phone, branch_id=getattr(settings, 'BRANCH_ID', ''))
    return JsonResponse({'success': True, 'data': _courier_qr(request, courier, password)})


@csrf_exempt
@require_POST
@manager_required
def regenerate_credential(request, courier_id):
    """POST /api/couriers/<pk>/regenerate -> reset the courier password + return a
    fresh login-QR (the previous QR/password stops working)."""
    courier = Courier.objects.select_related('user').filter(pk=courier_id).first()
    if not courier:
        return JsonResponse({'success': False, 'message': 'courier not found'}, status=404)
    password = secrets.token_urlsafe(6)
    courier.user.password = hash_password(password)
    courier.user.save(update_fields=['password'])
    return JsonResponse({'success': True, 'data': _courier_qr(request, courier, password)})
