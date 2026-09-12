from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from base.helpers.request import parse_json_body
from base.helpers.response import json_response
from base.security.permissions import manager_required
from base.security.audit import audit
from base.services.waiter_settings import policy_payload, update_policy


@csrf_exempt
@require_http_methods(['GET', 'PUT'])
@manager_required
def settings(request):
    if request.method == 'GET':
        return JsonResponse({'success': True, 'data': {'settings': policy_payload()}})
    data, error = parse_json_body(request)
    if error:
        return json_response(error)
    result, status = update_policy(data)
    if status < 400:
        audit(request, 'WAITER_POLICY_UPDATE', target_type='AppSettings', target_id=1,
              metadata=result['data']['settings'])
    return JsonResponse(result, status=status)
