"""Synchronous evidence boundary for local order and identity mutations.

These requests never appear in cloud web logs because the cashier browser talks
to 127.0.0.1/LAN first. Capturing request receipt before the view and the final
response after it closes the exact blind spot seen in Shift 102: money could be
collected despite a local create/pay failure that never produced a database row.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl

_MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024
_UUID_PATH_SEGMENT_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_OPAQUE_PATH_SEGMENT_RE = re.compile(r'^[A-Za-z0-9._~:-]{20,}$')
logger = logging.getLogger('desktop.order_http_audit')


def _record_local_event(event: str, payload: dict[str, Any]) -> bool:
    """Write optional evidence without making checkout depend on its storage.

    Importing ``desktop.order_audit`` at middleware-import time made a damaged
    or unreadable evidence file abort Django's middleware construction and
    therefore Uvicorn itself. Keep both the import and the synchronous write
    inside this fail-open boundary: evidence errors remain loud in the durable
    application log, while the order request continues through its real view.
    """
    try:
        from desktop import order_audit
        order_audit.record_local_event(event, payload, synchronous=True)
        return True
    except Exception:  # noqa: BLE001 - diagnostics cannot become checkout uptime
        logger.exception('local order HTTP evidence write failed (%s)', event)
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_order_mutation(request) -> bool:
    path = str(getattr(request, 'path', '') or '')
    method = str(getattr(request, 'method', '') or '').upper()
    return method in _MUTATING_METHODS and (
        '/orders' in path or '/order/' in path
        or path.rstrip('/').endswith('/auth-login')
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


def _query_evidence(request) -> dict[str, Any]:
    """Retain query shape without persisting credentials from its values."""
    raw = str(request.META.get('QUERY_STRING', '') or '')
    names: list[str] = []
    if raw:
        try:
            names = sorted({
                str(name)[:128]
                for name, _value in parse_qsl(
                    raw, keep_blank_values=True, strict_parsing=False,
                )
            })
        except (TypeError, ValueError):
            names = []
    return {
        **_opaque_identifier(raw),
        'parameter_names': names[:100],
    }


def _bounded_text(value: Any, *, limit: int) -> dict[str, Any]:
    raw = str(value or '')
    visible = raw[:limit]
    return {
        **_opaque_identifier(raw),
        'value': visible,
        'truncated': len(raw) > limit,
    }


def _client_evidence(request) -> dict[str, Any]:
    """Network/client correlation evidence, with deliberately bounded strings."""
    return {
        'remote_addr': str(request.META.get('REMOTE_ADDR', '') or '')[:128],
        'user_agent': _bounded_text(
            request.META.get('HTTP_USER_AGENT', ''), limit=256,
        ),
        'x_device_id': _bounded_text(
            request.META.get('HTTP_X_DEVICE_ID', ''), limit=256,
        ),
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
    if user is None:
        return {'authenticated': False}

    # Alpha POS uses its own ``base.User`` model, not Django's auth model, so
    # authenticated request users legitimately have no ``is_authenticated``
    # property. A persisted primary key is the reliable custom-user signal.
    # Still honour an explicit false marker so Django AnonymousUser remains
    # unauthenticated.
    marker = getattr(user, 'is_authenticated', None)
    if callable(marker):
        try:
            marker = marker()
        except Exception:  # noqa: BLE001 - evidence must stay fail-open
            marker = False
    user_id = getattr(user, 'pk', getattr(user, 'id', None))
    if marker is False or user_id is None:
        return {'authenticated': False}
    return {
        'authenticated': True,
        'id': user_id,
        'uuid': str(getattr(user, 'uuid', '') or ''),
        'role': str(getattr(user, 'role', '') or ''),
        'email': str(getattr(user, 'email', '') or ''),
    }


def _auth_evidence(request) -> dict[str, Any]:
    """Describe credential selection and resolution without storing a secret.

    Alpha POS rejects different cookie/Bearer sessions instead of letting one
    silently override the other. Matching dual credentials are one unambiguous
    session, while a mismatch deliberately has no selected session.
    """
    cookie_value = getattr(request, 'COOKIES', {}).get('session_key')
    cookie = cookie_value if isinstance(cookie_value, str) and cookie_value else ''
    header_value = request.META.get('HTTP_AUTHORIZATION', '')
    raw_header = header_value if isinstance(header_value, str) else ''
    raw_scheme, separator, header_credential = raw_header.partition(' ')
    scheme_key = raw_scheme.casefold()
    # Never mistake a malformed credential-without-a-space for a safe scheme.
    header_scheme = (
        scheme_key
        if scheme_key in {'bearer', 'basic', 'branch', 'cloud'}
        else ('other' if raw_header else '')
    )
    bearer = (
        header_credential.strip()
        if (
            separator
            and scheme_key == 'bearer'
        )
        else ''
    )
    resolved = str(getattr(request, 'session_key', '') or '')
    both_present = bool(cookie and bearer)
    same_credential = bool(
        both_present
        and hmac.compare_digest(
            cookie.encode('utf-8', errors='surrogatepass'),
            bearer.encode('utf-8', errors='surrogatepass'),
        )
    )
    conflict = bool(both_present and not same_credential)
    if conflict:
        selected = ''
        selected_source = 'conflict'
    elif both_present:
        selected = cookie
        selected_source = 'cookie+bearer'
    elif cookie:
        selected = cookie
        selected_source = 'cookie'
    elif bearer:
        selected = bearer
        selected_source = 'bearer'
    else:
        selected = ''
        selected_source = ''

    return {
        'cookie': _opaque_identifier(cookie),
        'header': _opaque_identifier(raw_header),
        'header_scheme': header_scheme,
        'bearer': _opaque_identifier(bearer),
        'both_present': both_present,
        'credential_conflict': conflict,
        'selected_source': selected_source,
        'selected_session_fingerprint': _opaque_identifier(selected),
        'resolved_session_fingerprint': _opaque_identifier(resolved),
        'resolved_matches_selected': bool(resolved and resolved == selected),
        'resolved_matches_cookie': bool(resolved and resolved == cookie),
        'resolved_matches_bearer': bool(resolved and resolved == bearer),
        'resolved_user': _user_evidence(request),
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
            'query': _query_evidence(request),
            'content_type': request.META.get('CONTENT_TYPE', ''),
            'idempotency_key': _opaque_identifier(
                request.META.get('HTTP_IDEMPOTENCY_KEY')
                or request.META.get('HTTP_X_IDEMPOTENCY_KEY')
                or ''
            ),
            'client': _client_evidence(request),
            'auth_evidence': _auth_evidence(request),
            'body': _body_evidence(raw_request),
            'body_read_error': body_error,
        }
        # Fsync before entering create/pay logic: this is intentionally on the
        # money path and is the proof of a request that never committed.
        _record_local_event('order_http_request_received', received)

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
            'client': _client_evidence(request),
            'auth_evidence': _auth_evidence(request),
            'response': _body_evidence(raw_response),
            'streaming': bool(getattr(response, 'streaming', False)),
        }
        _record_local_event('order_http_response_completed', completed)
        return response
