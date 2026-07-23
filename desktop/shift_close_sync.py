"""Durable desktop-side acknowledgement for closed-shift settlement bundles.

The ordinary sync queue acknowledges each model batch independently.  A Shift
can therefore receive a successful HTTP response before its immutable
ShiftPaymentTotal children (or the order/payment evidence named by its close
manifest) have reached the cloud.  Treating that generic push as "finished"
made an incomplete close indistinguishable from a fully verified one.

This module adds a desktop-only state machine around the existing queue:

* a post-commit Shift signal records PENDING as soon as a local close commits;
* unresolved Shift + ShiftPaymentTotal rows are retained/requeued;
* only the branch-authenticated cloud acknowledgement contract may transition
  the close to ACKNOWLEDGED;
* receiver conflicts remain durable and visible for manual repair.

The protected ``desktop_state.json`` is intentionally used for the small state
index.  If PostgreSQL itself becomes unavailable, the desktop can still tell an
operator that a previously closed shift was not acknowledged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid as uuid_module
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from desktop import config_store


logger = logging.getLogger('desktop.shift_close_sync')

STATE_KEY = 'shift_close_cloud_ack'
STATE_VERSION = 1
DIGEST_ALGORITHM = 'sha256-canonical-json-v1'
ACK_PATH = '/shift-close/ack'
_CLOSED_STATUSES = frozenset({'ENDED', 'COMPLETED'})
_REMOTE_STATES = frozenset({'PENDING', 'CONFLICT', 'ACKNOWLEDGED'})
_ACK_HISTORY_LIMIT = 200
_MAX_PROBES_PER_RUN = 25

_STATE_LOCK = threading.RLock()
_RUN_LOCK = threading.Lock()
_START_LOCK = threading.RLock()
_STARTED = False


def _utc_now() -> str:
    from django.utils import timezone

    return timezone.now().isoformat()


def canonical_manifest_digest(manifest: dict[str, Any]) -> str:
    """Return the exact digest required by the cloud acknowledgement API."""
    if not isinstance(manifest, dict):
        raise ValueError('close manifest must be a JSON object')
    encoded = json.dumps(
        manifest,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _money(value: Any) -> str | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite():
        return None
    return format(amount, 'f')


def _state_document() -> dict[str, Any]:
    raw = config_store.read_state().get(STATE_KEY)
    if not isinstance(raw, dict) or raw.get('version') != STATE_VERSION:
        return {'version': STATE_VERSION, 'shifts': {}}
    shifts = raw.get('shifts')
    if not isinstance(shifts, dict):
        shifts = {}
    return {'version': STATE_VERSION, 'shifts': shifts}


def _read_entries() -> dict[str, dict[str, Any]]:
    with _STATE_LOCK:
        return deepcopy(_state_document()['shifts'])


def _prune_entries(entries: dict[str, dict[str, Any]]) -> None:
    """Compact old ACK rows without forgetting their immutable identity.

    Deleting an old acknowledgement makes discovery treat that shift as new on
    the next startup. Once a till has more than ``_ACK_HISTORY_LIMIT`` closes,
    that creates an endless requeue/probe cycle through historical shifts. Keep
    a small digest tombstone for every acknowledged close and retain the rich
    diagnostic fields only for the newest rows.
    """
    acknowledged = [
        (key, row) for key, row in entries.items()
        if row.get('state') == 'ACKNOWLEDGED'
    ]
    acknowledged.sort(
        key=lambda pair: str(
            pair[1].get('acknowledged_at')
            or pair[1].get('updated_at')
            or ''
        ),
        reverse=True,
    )
    for key, row in acknowledged[_ACK_HISTORY_LIMIT:]:
        entries[key] = {
            'shift_uuid': row.get('shift_uuid') or key,
            'shift_id': row.get('shift_id'),
            'state': 'ACKNOWLEDGED',
            'manifest_version': row.get('manifest_version'),
            'manifest_digest': row.get('manifest_digest'),
            'digest_algorithm': row.get('digest_algorithm') or DIGEST_ALGORITHM,
            'first_seen_at': row.get('first_seen_at'),
            'updated_at': row.get('updated_at'),
            'acknowledged_at': row.get('acknowledged_at'),
        }


def _persist_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Atomically replace one tracker row and log meaningful transitions."""
    shift_uuid = str(entry['shift_uuid'])
    previous: dict[str, Any] | None = None

    def mutate(root: dict[str, Any]) -> dict[str, Any]:
        nonlocal previous
        document = root.get(STATE_KEY)
        if not isinstance(document, dict) or document.get('version') != STATE_VERSION:
            document = {'version': STATE_VERSION, 'shifts': {}}
        shifts = document.get('shifts')
        if not isinstance(shifts, dict):
            shifts = {}
        previous = deepcopy(shifts.get(shift_uuid))
        shifts[shift_uuid] = deepcopy(entry)
        _prune_entries(shifts)
        root[STATE_KEY] = {'version': STATE_VERSION, 'shifts': shifts}
        return root

    with _STATE_LOCK:
        config_store.update_state(mutate)

    prior_marker = (
        (previous or {}).get('state'),
        (previous or {}).get('reason_code'),
        (previous or {}).get('manifest_digest'),
    )
    marker = (
        entry.get('state'), entry.get('reason_code'), entry.get('manifest_digest'),
    )
    if prior_marker != marker:
        detail = (
            'shift=%s uuid=%s state=%s reason=%s digest=%s'
            % (
                entry.get('shift_id'), shift_uuid, entry.get('state'),
                entry.get('reason_code') or '-',
                str(entry.get('manifest_digest') or '')[:12],
            )
        )
        if entry.get('state') == 'CONFLICT':
            logger.error('cloud shift-close conflict: %s; %s', detail, entry.get('message'))
        elif entry.get('state') == 'PENDING':
            logger.warning('cloud shift-close pending: %s; %s', detail, entry.get('message'))
        else:
            logger.info('cloud shift-close acknowledged: %s', detail)
    return previous


def _base_entry(bundle: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    now = _utc_now()
    prior = previous or {}
    return {
        'shift_uuid': bundle['shift_uuid'],
        'shift_id': bundle['shift_id'],
        'shift_status': bundle['shift_status'],
        'end_time': bundle.get('end_time'),
        'manifest_version': bundle.get('manifest_version'),
        'manifest_digest': bundle.get('manifest_digest'),
        'digest_algorithm': DIGEST_ALGORITHM,
        'tender_count': len(bundle.get('rows') or []),
        'tender_methods': [
            str(getattr(row, 'method', '') or '').upper()
            for row in (bundle.get('rows') or [])
        ],
        'first_seen_at': prior.get('first_seen_at') or now,
        'updated_at': now,
        'last_probe_at': prior.get('last_probe_at'),
        'acknowledged_at': prior.get('acknowledged_at'),
        'probe_count': int(prior.get('probe_count') or 0),
        'server_status': prior.get('server_status'),
        'server_sync_version': prior.get('server_sync_version'),
        'settlement_rows': prior.get('settlement_rows'),
    }


def _entry_for(
    bundle: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    state: str,
    reason_code: str,
    message: str,
    remote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = _base_entry(bundle, previous)
    entry.update({
        'state': state,
        'reason_code': str(reason_code or ''),
        'message': str(message or '')[:500],
    })
    if remote is not None:
        entry['last_probe_at'] = _utc_now()
        entry['probe_count'] += 1
        entry['server_status'] = remote.get('server_status')
        entry['server_sync_version'] = remote.get('server_sync_version')
        rows = remote.get('settlement_rows')
        if isinstance(rows, dict):
            entry['settlement_rows'] = {
                'expected': rows.get('expected'),
                'received': rows.get('received'),
            }
    if state == 'ACKNOWLEDGED':
        entry['acknowledged_at'] = entry.get('acknowledged_at') or _utc_now()
    elif previous and previous.get('state') == 'ACKNOWLEDGED':
        # A changed local manifest must not keep an old acknowledgement stamp.
        entry['acknowledged_at'] = None
    return entry


def _local_bundle(shift: Any) -> dict[str, Any]:
    """Build and locally validate the immutable Shift/SPT close bundle."""
    from cashbox.models import ShiftPaymentTotal

    manifest = shift.settlement_manifest
    bundle = {
        'shift': shift,
        'shift_uuid': str(shift.uuid),
        'shift_id': shift.pk,
        'shift_status': str(shift.status),
        'end_time': shift.end_time.isoformat() if shift.end_time else None,
        'manifest': manifest if isinstance(manifest, dict) else {},
        'manifest_version': None,
        'manifest_digest': None,
        'rows': [],
        'local_error': '',
    }
    if not isinstance(manifest, dict) or not manifest:
        bundle['local_error'] = 'Close manifest is missing or is not a JSON object'
        return bundle
    version = manifest.get('version')
    if not isinstance(version, int):
        bundle['local_error'] = 'Close manifest version is missing or invalid'
        return bundle
    bundle['manifest_version'] = version
    try:
        bundle['manifest_digest'] = canonical_manifest_digest(manifest)
    except (TypeError, ValueError) as exc:
        bundle['local_error'] = f'Close manifest cannot be hashed: {exc}'
        return bundle

    tenders = manifest.get('tenders')
    if not isinstance(tenders, list):
        bundle['local_error'] = 'Close manifest tender list is missing or invalid'
        return bundle

    expected: dict[str, dict[str, Any]] = {}
    for raw in tenders:
        if not isinstance(raw, dict):
            bundle['local_error'] = 'Close manifest contains a malformed tender row'
            return bundle
        try:
            row_uuid = str(uuid_module.UUID(str(raw.get('uuid'))))
        except (TypeError, ValueError, AttributeError):
            bundle['local_error'] = 'Close manifest contains an invalid tender UUID'
            return bundle
        method = str(raw.get('method') or '').strip().upper()
        candidate = {
            'uuid': row_uuid,
            'method': method,
            'expected': _money(raw.get('expected')),
            'counted': _money(raw.get('counted')),
            'difference': _money(raw.get('difference')),
        }
        if (
            not method
            or any(candidate[key] is None for key in ('expected', 'counted', 'difference'))
        ):
            bundle['local_error'] = 'Close manifest contains an invalid tender amount/method'
            return bundle
        if row_uuid in expected:
            bundle['local_error'] = 'Close manifest repeats a tender UUID'
            return bundle
        expected[row_uuid] = candidate

    rows = list(
        ShiftPaymentTotal.objects.filter(shift_id=shift.pk, is_deleted=False)
        .order_by('method', 'uuid')
    )
    actual: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_uuid = str(row.uuid)
        actual[row_uuid] = {
            'uuid': row_uuid,
            'method': str(row.method or '').strip().upper(),
            'expected': _money(row.expected_amount),
            'counted': _money(row.counted_amount),
            'difference': _money(row.difference),
        }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatched = sorted(
        row_uuid for row_uuid in set(expected) & set(actual)
        if expected[row_uuid] != actual[row_uuid]
    )
    if missing or extra or mismatched:
        detail = []
        if missing:
            detail.append(f'missing={len(missing)}')
        if extra:
            detail.append(f'extra={len(extra)}')
        if mismatched:
            detail.append(f'mismatched={len(mismatched)}')
        bundle['local_error'] = (
            'Local ShiftPaymentTotal rows do not match the frozen close manifest '
            f'({", ".join(detail)})'
        )
        bundle['rows'] = rows
        return bundle
    bundle['rows'] = rows
    return bundle


def _discover_bundles() -> dict[str, dict[str, Any]]:
    from base.models import Shift

    candidates = Shift.objects.filter(
        status__in=_CLOSED_STATUSES,
        is_deleted=False,
    ).order_by('-pk')
    bundles: dict[str, dict[str, Any]] = {}
    for shift in candidates.iterator():
        # Pre-rollout/legacy rows intentionally lack both flags.  A current
        # eligible close missing its manifest is a conflict and must be shown.
        if not shift.settlement_manifest and not shift.treasury_settlement_eligible:
            continue
        bundle = _local_bundle(shift)
        bundles[bundle['shift_uuid']] = bundle
    return bundles


def _ensure_discovered_entries(
    bundles: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    entries = _read_entries()
    for shift_uuid, bundle in bundles.items():
        previous = entries.get(shift_uuid)
        if bundle.get('local_error'):
            entry = _entry_for(
                bundle, previous,
                state='CONFLICT', reason_code='LOCAL_BUNDLE_INVALID',
                message=bundle['local_error'],
            )
        elif (
            previous
            and previous.get('manifest_digest')
            and previous.get('manifest_digest') != bundle.get('manifest_digest')
        ):
            entry = _entry_for(
                bundle, previous,
                state='CONFLICT', reason_code='LOCAL_MANIFEST_CHANGED',
                message=(
                    'The frozen close manifest changed after it was first tracked; '
                    'cloud acknowledgement is blocked for manual investigation.'
                ),
            )
        elif (
            previous
            and previous.get('state') == 'ACKNOWLEDGED'
            and previous.get('manifest_digest') == bundle.get('manifest_digest')
        ):
            # Keep the durable proof without probing an already-acknowledged
            # immutable bundle on every application launch.
            continue
        elif previous and previous.get('state') == 'CONFLICT':
            # Preserve the authoritative/manual conflict until the next cloud
            # probe can prove that a repair resolved it.
            entry = _entry_for(
                bundle, previous,
                state='CONFLICT',
                reason_code=previous.get('reason_code') or 'CLOUD_CONFLICT',
                message=previous.get('message') or 'Cloud close conflict requires repair.',
            )
        else:
            entry = _entry_for(
                bundle, previous,
                state='PENDING', reason_code='AWAITING_CLOUD_ACK',
                message=(
                    'The shift is closed locally, but the cloud has not yet '
                    'verified its manifest and settlement rows.'
                ),
            )
        _persist_entry(entry)
        entries[shift_uuid] = entry

    # If an unresolved source row vanishes, keep the warning rather than silently
    # dropping the only desktop evidence that the close was never acknowledged.
    for shift_uuid, previous in list(entries.items()):
        if previous.get('state') == 'ACKNOWLEDGED' or shift_uuid in bundles:
            continue
        missing = dict(previous)
        missing.update({
            'state': 'CONFLICT',
            'reason_code': 'LOCAL_SHIFT_MISSING',
            'message': 'The local shift disappeared before cloud acknowledgement.',
            'updated_at': _utc_now(),
        })
        _persist_entry(missing)
        entries[shift_uuid] = missing
    return entries


def _retain_bundle(bundle: dict[str, Any], *, reset_dead_letters: bool = False) -> None:
    """Ensure exact Shift/SPT evidence remains in the existing durable queue."""
    if bundle.get('local_error'):
        return
    from base.models import SyncQueueRecord
    from base.services.sync.config import (
        SyncConfig, get_sync_max_queue_attempts,
    )
    from base.services.sync.service import SyncService

    if not SyncConfig.is_enabled():
        return
    shift = bundle['shift']
    SyncService.queue_record(shift)
    for row in bundle.get('rows') or []:
        SyncService.queue_record(row)

    if reset_dead_letters:
        cap = get_sync_max_queue_attempts()
        if cap:
            refs = [('shift', shift.uuid)] + [
                ('shiftpaymenttotal', row.uuid) for row in (bundle.get('rows') or [])
            ]
            reset = 0
            for model_name, record_uuid in refs:
                reset += SyncQueueRecord.objects.filter(
                    model_name=model_name,
                    record_uuid=record_uuid,
                    attempts__gte=cap,
                ).update(attempts=0, last_error='')
            if reset:
                logger.warning(
                    're-enabled %d dead-lettered close record(s) after the cloud '
                    'reported the bundle still PENDING (shift=%s)',
                    reset, bundle['shift_id'],
                )


def _park_conflict_bundle(bundle: dict[str, Any], message: str) -> None:
    """Retain conflict evidence without hot-looping a permanent rejection."""
    if bundle.get('local_error'):
        return
    from base.models import SyncQueueRecord
    from base.services.sync.config import get_sync_max_queue_attempts

    _retain_bundle(bundle)
    cap = get_sync_max_queue_attempts()
    if not cap:
        return
    refs = [('shift', bundle['shift'].uuid)] + [
        ('shiftpaymenttotal', row.uuid) for row in (bundle.get('rows') or [])
    ]
    for model_name, record_uuid in refs:
        SyncQueueRecord.objects.filter(
            model_name=model_name, record_uuid=record_uuid,
        ).update(
            attempts=cap,
            last_error=f'Cloud shift-close conflict: {str(message)[:430]}',
        )


def _clear_parked_bundle_after_ack(bundle: dict[str, Any]) -> None:
    """Drop only tracker-parked generations after authoritative cloud ACK.

    A concurrent legitimate save rotates/reset the queue row and therefore no
    longer matches the attempts/error marker below; that newer generation is
    deliberately left for the ordinary generation-safe pusher.
    """
    from django.db import transaction
    from base.models import SyncQueueRecord
    from base.services.sync.config import get_sync_max_queue_attempts
    from base.services.sync.evidence import emit_sync_evidence
    from base.services.sync.queue import SyncQueue

    cap = get_sync_max_queue_attempts()
    if not cap:
        return
    refs = [('shift', bundle['shift'].uuid)] + [
        ('shiftpaymenttotal', row.uuid) for row in (bundle.get('rows') or [])
    ]
    removed = []
    with transaction.atomic():
        for model_name, record_uuid in refs:
            rows = list(
                SyncQueueRecord.objects.select_for_update().filter(
                    model_name=model_name,
                    record_uuid=record_uuid,
                    attempts__gte=cap,
                    last_error__startswith='Cloud shift-close conflict:',
                )
            )
            if rows:
                removed.extend(SyncQueue._to_dict(row) for row in rows)
                SyncQueueRecord.objects.filter(
                    pk__in=[row.pk for row in rows],
                ).delete()
    if removed:
        emit_sync_evidence(
            'queue_removed',
            reason='cloud_shift_close_acknowledged',
            records=removed,
        )
        logger.info(
            'cleared %d tracker-parked close record(s) after authoritative ACK '
            '(shift=%s)', len(removed), bundle['shift_id'],
        )


def _request_cloud_ack(bundle: dict[str, Any]) -> dict[str, Any]:
    """Call the branch-authenticated, read-only cloud close verifier once."""
    from base.services.sync import transport
    from base.services.sync.config import get_cloud_url, get_sync_timeout

    url = get_cloud_url()
    if not url:
        return {
            'state': 'UNAVAILABLE',
            'reason_code': 'CLOUD_URL_MISSING',
            'reason': 'Cloud sync URL is not configured.',
        }
    guard = transport._guard_url(url)  # reuse the sync engine's HTTPS policy
    if guard:
        return {
            'state': 'UNAVAILABLE',
            'reason_code': 'CLOUD_URL_REJECTED',
            'reason': guard,
        }
    request_payload = {
        'shift_uuid': bundle['shift_uuid'],
        'manifest_version': bundle['manifest_version'],
        'manifest_digest': bundle['manifest_digest'],
    }
    try:
        response = transport.requests.post(
            f'{url}{ACK_PATH}',
            headers=transport._auth_headers(),
            data=json.dumps(request_payload, separators=(',', ':')),
            # This endpoint is a tiny indexed read. Cap its timeout so one
            # unreachable hub cannot hold the sync worker for the ordinary
            # 30-second batch timeout for every historical close.
            timeout=min(10, max(1, get_sync_timeout())),
        )
    except Exception as exc:  # noqa: BLE001 - retry occurs on the next sync tick
        return {
            'state': 'UNAVAILABLE',
            'reason_code': 'ACK_REQUEST_FAILED',
            'reason': f'Cloud acknowledgement request failed: {exc}',
        }
    if response.status_code != 200:
        return {
            'state': 'UNAVAILABLE',
            'reason_code': f'ACK_HTTP_{response.status_code}',
            'reason': (
                'Cloud close acknowledgement endpoint returned HTTP '
                f'{response.status_code}.'
            ),
        }
    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        return {
            'state': 'UNAVAILABLE',
            'reason_code': 'ACK_RESPONSE_INVALID_JSON',
            'reason': f'Cloud acknowledgement response was not valid JSON: {exc}',
        }
    if not isinstance(data, dict):
        return {
            'state': 'UNAVAILABLE',
            'reason_code': 'ACK_RESPONSE_INVALID',
            'reason': 'Cloud acknowledgement response was not an object.',
        }
    return data


def _validated_remote_result(
    bundle: dict[str, Any], remote: dict[str, Any],
) -> tuple[str, str, str]:
    """Fail closed unless the response echoes the exact requested identity."""
    state = str(remote.get('state') or '').upper()
    reason_code = str(remote.get('reason_code') or '')
    reason = str(remote.get('reason') or '')[:500]
    if state == 'UNAVAILABLE':
        return 'PENDING', reason_code or 'ACK_UNAVAILABLE', reason
    try:
        echoed_version = int(remote.get('manifest_version'))
    except (TypeError, ValueError):
        echoed_version = None
    identity_matches = (
        remote.get('success') is True
        and str(remote.get('shift_uuid') or '') == bundle['shift_uuid']
        and echoed_version == bundle['manifest_version']
        and str(remote.get('manifest_digest') or '') == bundle['manifest_digest']
        and remote.get('digest_algorithm') == DIGEST_ALGORITHM
        and state in _REMOTE_STATES
    )
    if not identity_matches:
        return (
            'CONFLICT', 'ACK_CONTRACT_MISMATCH',
            'Cloud acknowledgement did not echo the exact shift, manifest, and digest contract.',
        )
    if state == 'ACKNOWLEDGED' and remote.get('acknowledged') is not True:
        return (
            'CONFLICT', 'ACK_CONTRACT_MISMATCH',
            'Cloud returned ACKNOWLEDGED without acknowledged=true.',
        )
    if state != 'ACKNOWLEDGED' and remote.get('acknowledged') is True:
        return (
            'CONFLICT', 'ACK_CONTRACT_MISMATCH',
            'Cloud returned acknowledged=true for a non-acknowledged state.',
        )
    if state == 'ACKNOWLEDGED':
        return 'ACKNOWLEDGED', reason_code or 'CLOUD_ACKNOWLEDGED', reason or (
            'The cloud verified the complete shift close bundle.'
        )
    if state == 'CONFLICT':
        return 'CONFLICT', reason_code or 'CLOUD_CONFLICT', reason or (
            'The cloud found a conflict in the shift close bundle.'
        )
    return 'PENDING', reason_code or 'CLOUD_PENDING', reason or (
        'The cloud is still waiting for shift close evidence.'
    )


def _refresh(*, probe_cloud: bool, retain: bool) -> dict[str, Any]:
    bundles = _discover_bundles()
    entries = _ensure_discovered_entries(bundles)
    ordered = sorted(
        bundles.items(),
        key=lambda pair: (
            0 if not (entries.get(pair[0]) or {}).get('last_probe_at') else 1,
            0 if (entries.get(pair[0]) or {}).get('state') == 'PENDING' else 1,
            -int(pair[1].get('shift_id') or 0),
        ),
    )
    probes = 0
    unavailable: dict[str, Any] | None = None
    for shift_uuid, bundle in ordered:
        entry = entries.get(shift_uuid) or {}
        if entry.get('state') == 'ACKNOWLEDGED':
            continue
        if bundle.get('local_error'):
            continue
        if not probe_cloud:
            if retain and entry.get('state') == 'PENDING':
                _retain_bundle(bundle)
            elif retain and entry.get('state') == 'CONFLICT':
                _park_conflict_bundle(bundle, entry.get('message') or '')
            continue

        if probes >= _MAX_PROBES_PER_RUN:
            # Leave the durable state unchanged; the next 10-second worker tick
            # continues with the remaining rows. Newest pending closes are
            # intentionally first so a large historical backlog never hides the
            # shift that was just closed at the till.
            if entry.get('state') == 'CONFLICT':
                _park_conflict_bundle(bundle, entry.get('message') or '')
            else:
                _retain_bundle(bundle)
            continue
        if unavailable is None:
            remote = _request_cloud_ack(bundle)
            probes += 1
            if str(remote.get('state') or '').upper() == 'UNAVAILABLE':
                unavailable = remote
        else:
            # One transport/auth/404 failure is enough for this cycle. Reusing
            # the failure bounds an outage to one short request instead of
            # timeout * number-of-shifts.
            remote = unavailable
        state, reason_code, message = _validated_remote_result(bundle, remote)
        updated = _entry_for(
            bundle, entry,
            state=state, reason_code=reason_code, message=message,
            remote=remote,
        )
        _persist_entry(updated)
        entries[shift_uuid] = updated
        if state == 'PENDING':
            # An explicit PENDING proves the cloud has not accepted the complete
            # bundle. Revive only these exact close rows if an old receiver
            # rejection exhausted their poison-message allowance.
            _retain_bundle(
                bundle,
                reset_dead_letters=(str(remote.get('state') or '').upper() == 'PENDING'),
            )
        elif state == 'CONFLICT':
            _park_conflict_bundle(bundle, message)
        elif state == 'ACKNOWLEDGED':
            _clear_parked_bundle_after_ack(bundle)
    return get_status()


def prepare_for_push() -> dict[str, Any]:
    """Discover closes and retain their evidence before a generic push."""
    ensure_started()
    with _RUN_LOCK:
        return _refresh(probe_cloud=False, retain=True)


def after_push(_push_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ask the cloud for an authoritative bundle verdict after a push attempt."""
    ensure_started()
    with _RUN_LOCK:
        return _refresh(probe_cloud=True, retain=True)


def get_status() -> dict[str, Any]:
    entries = _read_entries()
    pending = [row for row in entries.values() if row.get('state') == 'PENDING']
    conflicts = [row for row in entries.values() if row.get('state') == 'CONFLICT']
    acknowledged = [
        row for row in entries.values() if row.get('state') == 'ACKNOWLEDGED'
    ]
    unresolved = conflicts + pending
    unresolved.sort(
        key=lambda row: (
            0 if row.get('state') == 'CONFLICT' else 1,
            str(row.get('end_time') or ''),
            int(row.get('shift_id') or 0),
        ),
        reverse=False,
    )
    if conflicts:
        state = 'CONFLICT'
        message = conflicts[0].get('message') or 'A shift close has a cloud conflict.'
    elif pending:
        state = 'PENDING'
        message = pending[0].get('message') or 'A shift close is awaiting cloud acknowledgement.'
    elif acknowledged:
        state = 'ACKNOWLEDGED'
        message = 'All tracked shift closes were acknowledged by the cloud.'
    else:
        state = 'IDLE'
        message = 'No shift close is awaiting cloud acknowledgement.'
    return {
        'state': state,
        'clear': not pending and not conflicts,
        'pending_count': len(pending),
        'conflict_count': len(conflicts),
        'acknowledged_count': len(acknowledged),
        'message': str(message)[:500],
        'unresolved': deepcopy(unresolved[:25]),
        'last_acknowledged_at': max(
            (str(row.get('acknowledged_at') or '') for row in acknowledged),
            default='',
        ) or None,
        'digest_algorithm': DIGEST_ALGORITHM,
    }


def _track_committed_shift(shift_pk: int) -> None:
    """Post-commit callback: persist pending without making a network call."""
    try:
        from base.models import Shift

        shift = Shift.objects.filter(pk=shift_pk).first()
        if shift is None or shift.status not in _CLOSED_STATUSES:
            return
        if not shift.settlement_manifest and not shift.treasury_settlement_eligible:
            return
        bundle = _local_bundle(shift)
        previous = _read_entries().get(bundle['shift_uuid'])
        if bundle.get('local_error'):
            entry = _entry_for(
                bundle, previous,
                state='CONFLICT', reason_code='LOCAL_BUNDLE_INVALID',
                message=bundle['local_error'],
            )
        elif previous and previous.get('manifest_digest') not in (
            None, bundle.get('manifest_digest'),
        ):
            entry = _entry_for(
                bundle, previous,
                state='CONFLICT', reason_code='LOCAL_MANIFEST_CHANGED',
                message='The frozen close manifest changed after it was first tracked.',
            )
        elif (
            previous
            and previous.get('state') == 'ACKNOWLEDGED'
            and previous.get('manifest_digest') == bundle.get('manifest_digest')
        ):
            # Cloud pull/reconciliation can legitimately save the same immutable
            # Shift again (for example ENDED -> COMPLETED). Do not regress a
            # matching authoritative acknowledgement back to PENDING.
            return
        elif previous and previous.get('state') == 'CONFLICT':
            entry = _entry_for(
                bundle, previous,
                state='CONFLICT',
                reason_code=previous.get('reason_code') or 'CLOUD_CONFLICT',
                message=previous.get('message') or 'Cloud close conflict requires repair.',
            )
        else:
            entry = _entry_for(
                bundle, previous,
                state='PENDING', reason_code='AWAITING_CLOUD_ACK',
                message=(
                    'The shift is closed locally, but the cloud has not yet '
                    'verified its manifest and settlement rows.'
                ),
            )
        _persist_entry(entry)
    except Exception:  # noqa: BLE001 - a committed close must still return
        logger.exception('could not persist committed shift-close pending state')


def _on_shift_saved(sender: Any, instance: Any, **_kwargs: Any) -> None:
    if str(getattr(instance, 'status', '')) not in _CLOSED_STATUSES:
        return
    if not getattr(instance, 'settlement_manifest', None) and not getattr(
        instance, 'treasury_settlement_eligible', False,
    ):
        return
    from django.db import transaction

    transaction.on_commit(
        lambda pk=instance.pk: _track_committed_shift(pk),
        using=getattr(instance._state, 'db', None),
        robust=True,
    )


def ensure_started() -> bool:
    """Register the close signal exactly once; discovery handles missed events."""
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return False
        from django.db.models.signals import post_save
        from base.models import Shift

        post_save.connect(
            _on_shift_saved,
            sender=Shift,
            weak=False,
            dispatch_uid='desktop.shift_close_sync.shift.save',
        )
        _STARTED = True
    try:
        with _RUN_LOCK:
            _refresh(probe_cloud=False, retain=False)
    except Exception:  # noqa: BLE001 - migrations may still be starting
        logger.exception('initial shift-close acknowledgement discovery failed')
    return True


def stop() -> None:
    """Disconnect the signal (used by tests and destructive desktop reset)."""
    global _STARTED
    with _START_LOCK:
        if not _STARTED:
            return
        try:
            from django.db.models.signals import post_save
            from base.models import Shift

            post_save.disconnect(
                _on_shift_saved,
                sender=Shift,
                dispatch_uid='desktop.shift_close_sync.shift.save',
            )
        finally:
            _STARTED = False
