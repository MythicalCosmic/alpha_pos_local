"""Synchronous evidence boundary for local order mutations.

These requests never appear in cloud web logs because the cashier browser talks
to 127.0.0.1/LAN first. Capturing request receipt before the view and the final
response after it closes the exact blind spot seen in Shift 102: money could be
collected despite a local create/pay failure that never produced a database row.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from desktop import order_audit


_MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024
_UUID_PATH_SEGMENT_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_OPAQUE_PATH_SEGMENT_RE = re.compile(r'^[A-Za-z0-9._~:-]{20,}$')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_order_mutation(request) -> bool:
    path = str(getattr(request, 'path', '') or '')
    method = str(getattr(request, 'method', '') or '').upper()
    return method in _MUTATING_METHODS and (
        '/orders' in path or '/order/' in path
    )


def _path_evidence(request) -> dict[str, Any]:
    """Keep route shape and correlation hash, never an opaque URL credential."""
    raw = str(getattr(request, 'path', '') or '')
    safe_segments = []
    segments = raw.split('/')
    for index, segment in enumerate(segments):
        prefix = '/'.join(segments[max(0, index - 3):index]).lower()
        route_secret = prefix.endswith('api/qr/order') or prefix.endswith(
            'orders/print-jobs'
        )
        if (
            route_secret
            or _UUID_PATH_SEGMENT_RE.fullmatch(segment)
            or _OPAQUE_PATH_SEGMENT_RE.fullmatch(segment)
        ):
            safe_segments.append(':opaque')
        else:
            safe_segments.append(segment)
    resolver_match = getattr(request, 'resolver_match', None)
    route = str(getattr(resolver_match, 'route', '') or '')
    return {
        'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        'safe_path': '/'.join(safe_segments),
        'route': route,
    }


def _opaque_identifier(value: Any) -> dict[str, Any]:
    raw = str(value or '')
    return {
        'present': bool(raw),
        'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest() if raw else '',
    }


def _body_evidence(raw: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'truncated': len(raw) > _MAX_CAPTURE_BYTES,
    }
    visible = raw[:_MAX_CAPTURE_BYTES]
    try:
        text = visible.decode('utf-8')
    except UnicodeDecodeError:
        result['utf8'] = False
        return result
    result['utf8'] = True
    try:
        result['json'] = json.loads(text) if text else None
    except (TypeError, ValueError):
        result['text'] = text
    return result


def _user_evidence(request) -> dict[str, Any]:
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'authenticated': False}
    return {
        'authenticated': True,
        'id': getattr(user, 'pk', None),
        'uuid': str(getattr(user, 'uuid', '') or ''),
        'role': str(getattr(user, 'role', '') or ''),
        'email': str(getattr(user, 'email', '') or ''),
    }


class OrderMutationEvidenceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _is_order_mutation(request):
            return self.get_response(request)

        request_id = str(uuid.uuid4())
        started = time.monotonic()
        try:
            raw_request = bytes(request.body or b'')
        except Exception as exc:  # noqa: BLE001
            raw_request = b''
            body_error = str(exc)[:300]
        else:
            body_error = ''

        received = {
            'request_id': request_id,
            'phase': 'received_before_view',
            'received_at': _now(),
            'method': request.method,
            'path': _path_evidence(request),
            'query': request.META.get('QUERY_STRING', ''),
            'content_type': request.META.get('CONTENT_TYPE', ''),
            'idempotency_key': _opaque_identifier(
                request.META.get('HTTP_IDEMPOTENCY_KEY')
                or request.META.get('HTTP_X_IDEMPOTENCY_KEY')
                or ''
            ),
            'device_id': request.META.get('HTTP_X_DEVICE_ID', ''),
            'body': _body_evidence(raw_request),
            'body_read_error': body_error,
        }
        # Fsync before entering create/pay logic: this is intentionally on the
        # money path and is the proof of a request that never committed.
        order_audit.record_local_event(
            'order_http_request_received', received, synchronous=True,
        )

        response = self.get_response(request)
        raw_response = b''
        if not getattr(response, 'streaming', False):
            try:
                raw_response = bytes(response.content or b'')
            except Exception:  # noqa: BLE001
                raw_response = b''
        completed = {
            'request_id': request_id,
            'phase': 'response_after_transaction',
            'completed_at': _now(),
            'elapsed_ms': round((time.monotonic() - started) * 1000, 3),
            'method': request.method,
            'path': _path_evidence(request),
            'status_code': int(getattr(response, 'status_code', 0) or 0),
            'user': _user_evidence(request),
            'response': _body_evidence(raw_response),
            'streaming': bool(getattr(response, 'streaming', False)),
        }
        order_audit.record_local_event(
            'order_http_response_completed', completed, synchronous=True,
        )
        return response
