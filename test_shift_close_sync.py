import hashlib
import json

import pytest
from django.test import override_settings
from django.utils import timezone

from desktop import config_store, shift_close_sync
from desktop.bridge import _attach_shift_close_status


@pytest.fixture
def tracker_storage(monkeypatch, tmp_path):
    shift_close_sync.stop()
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config_store, 'STATE_FILE', tmp_path / 'desktop_state.json')
    yield
    shift_close_sync.stop()


def _make_closed_shift(cashier_user, *, methods=('CASH', 'HUMO')):
    from base.models import Shift
    from cashbox.models import ShiftPaymentTotal

    shift = Shift.objects.create(
        user=cashier_user,
        start_time=timezone.now(),
        end_time=timezone.now(),
        status=Shift.Status.ENDED,
        branch_id='branch-a',
        treasury_settlement_eligible=True,
    )
    rows = []
    for index, method in enumerate(methods, start=1):
        amount = index * 1000
        rows.append(ShiftPaymentTotal.objects.create(
            shift=shift,
            method=method,
            expected_amount=amount,
            counted_amount=amount,
            difference=0,
            branch_id='branch-a',
        ))
    manifest = {
        'version': 3,
        'branch_id': 'branch-a',
        'tenders': [
            {
                'uuid': str(row.uuid),
                'method': row.method,
                'expected': f'{row.expected_amount:.2f}',
                'counted': f'{row.counted_amount:.2f}',
                'difference': f'{row.difference:.2f}',
            }
            for row in sorted(rows, key=lambda item: item.method)
        ],
        'expenses': {'count': 0, 'total': '0.00', 'digest': 'none'},
        'money_evidence': {'orders': {'count': 0, 'total': '0.00', 'digest': 'none'}},
    }
    # Build a frozen post-close fixture without triggering another model save;
    # the tracker itself is the code under test, not SyncMixin queue behavior.
    Shift.objects.filter(pk=shift.pk).update(settlement_manifest=manifest)
    shift.refresh_from_db()
    return shift, rows


def _remote(bundle, state, *, reason_code=None, reason=None, **overrides):
    response = {
        'success': True,
        'shift_uuid': bundle['shift_uuid'],
        'state': state,
        'acknowledged': state == 'ACKNOWLEDGED',
        'manifest_version': bundle['manifest_version'],
        'manifest_digest': bundle['manifest_digest'],
        'server_status': 'ENDED',
        'server_sync_version': 4,
        'settlement_rows': {
            'expected': len(bundle['rows']),
            'received': len(bundle['rows']),
        },
        'reason_code': reason_code or f'CLOUD_{state}',
        'reason': reason or state.title(),
        'digest_algorithm': shift_close_sync.DIGEST_ALGORITHM,
    }
    response.update(overrides)
    return response


def test_manifest_digest_is_exact_canonical_json_contract():
    manifest = {'z': 'o\u02bbzbek', 'a': {'b': 2, 'a': 1}}
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')
    assert shift_close_sync.canonical_manifest_digest(manifest) == (
        hashlib.sha256(canonical).hexdigest()
    )


@override_settings(
    SYNC_ENABLED=True,
    DEPLOYMENT_MODE='local',
    BRANCH_ID='branch-a',
)
def test_prepare_persists_pending_and_rebuilds_exact_queue(
    db, cashier_user, tracker_storage,
):
    from base.models import SyncQueueRecord

    shift, rows = _make_closed_shift(cashier_user)
    SyncQueueRecord.objects.all().delete()

    status = shift_close_sync.prepare_for_push()

    assert status['state'] == 'PENDING'
    assert status['pending_count'] == 1
    assert status['conflict_count'] == 0
    assert set(SyncQueueRecord.objects.values_list('model_name', 'record_uuid')) == {
        ('shift', shift.uuid),
        *((('shiftpaymenttotal', row.uuid) for row in rows)),
    }
    persisted = config_store.read_state()[shift_close_sync.STATE_KEY]
    entry = persisted['shifts'][str(shift.uuid)]
    assert entry['state'] == 'PENDING'
    assert entry['manifest_digest'] == shift_close_sync.canonical_manifest_digest(
        shift.settlement_manifest,
    )


@override_settings(
    SYNC_ENABLED=True,
    DEPLOYMENT_MODE='local',
    BRANCH_ID='branch-a',
)
def test_only_exact_cloud_acknowledgement_clears_pending(
    db, cashier_user, tracker_storage, monkeypatch,
):
    from base.models import SyncQueueRecord

    shift, _rows = _make_closed_shift(cashier_user)
    shift_close_sync.prepare_for_push()
    # Model-level HTTP acknowledgement has already removed the queue. That alone
    # must not clear the durable close state.
    SyncQueueRecord.objects.all().delete()
    assert shift_close_sync.get_status()['state'] == 'PENDING'

    monkeypatch.setattr(
        shift_close_sync,
        '_request_cloud_ack',
        lambda bundle: _remote(bundle, 'ACKNOWLEDGED'),
    )
    status = shift_close_sync.after_push({'success': True})

    assert status['state'] == 'ACKNOWLEDGED'
    assert status['clear'] is True
    assert status['pending_count'] == 0
    assert status['last_acknowledged_at']
    assert SyncQueueRecord.objects.count() == 0
    entry = config_store.read_state()[shift_close_sync.STATE_KEY]['shifts'][str(shift.uuid)]
    assert entry['state'] == 'ACKNOWLEDGED'
    assert entry['settlement_rows'] == {'expected': 2, 'received': 2}

    # A later cloud pull/manager status save emits post_save for the same closed
    # Shift. It must not regress matching immutable evidence back to PENDING.
    shift_close_sync._track_committed_shift(shift.pk)
    assert shift_close_sync.get_status()['state'] == 'ACKNOWLEDGED'


@override_settings(
    SYNC_ENABLED=True,
    DEPLOYMENT_MODE='local',
    BRANCH_ID='branch-a',
    SYNC_MAX_QUEUE_ATTEMPTS=3,
)
def test_cloud_pending_requeues_bundle_and_revives_only_its_dead_letters(
    db, cashier_user, tracker_storage, monkeypatch,
):
    from base.models import SyncQueueRecord

    shift, rows = _make_closed_shift(cashier_user)
    shift_close_sync.prepare_for_push()
    SyncQueueRecord.objects.update(attempts=3, last_error='old receiver rejection')
    monkeypatch.setattr(
        shift_close_sync,
        '_request_cloud_ack',
        lambda bundle: _remote(
            bundle, 'PENDING', reason_code='SETTLEMENT_ROWS_MISSING',
            reason='Waiting for settlement rows',
        ),
    )

    status = shift_close_sync.after_push({'success': True})

    assert status['state'] == 'PENDING'
    assert status['message'] == 'Waiting for settlement rows'
    queue = list(SyncQueueRecord.objects.order_by('model_name', 'record_uuid'))
    assert len(queue) == len(rows) + 1
    assert all(record.attempts == 0 and record.last_error == '' for record in queue)
    assert {record.record_uuid for record in queue} == {
        shift.uuid, *(row.uuid for row in rows),
    }


@override_settings(
    SYNC_ENABLED=True,
    DEPLOYMENT_MODE='local',
    BRANCH_ID='branch-a',
    SYNC_MAX_QUEUE_ATTEMPTS=4,
)
def test_cloud_conflict_is_durable_visible_and_parked_without_hot_loop(
    db, cashier_user, tracker_storage, monkeypatch,
):
    from base.models import SyncQueueRecord

    shift, rows = _make_closed_shift(cashier_user)
    shift_close_sync.prepare_for_push()
    SyncQueueRecord.objects.all().delete()  # receiver accepted individual rows
    monkeypatch.setattr(
        shift_close_sync,
        '_request_cloud_ack',
        lambda bundle: _remote(
            bundle, 'CONFLICT', reason_code='MANIFEST_DIGEST_MISMATCH',
            reason='Server manifest differs from the branch manifest',
        ),
    )

    status = shift_close_sync.after_push({'success': True})

    assert status['state'] == 'CONFLICT'
    assert status['clear'] is False
    assert status['conflict_count'] == 1
    assert status['unresolved'][0]['reason_code'] == 'MANIFEST_DIGEST_MISMATCH'
    queue = list(SyncQueueRecord.objects.all())
    assert len(queue) == len(rows) + 1
    assert all(record.attempts == 4 for record in queue)
    assert all('shift-close conflict' in record.last_error.lower() for record in queue)
    persisted = config_store.read_state()[shift_close_sync.STATE_KEY]
    assert persisted['shifts'][str(shift.uuid)]['state'] == 'CONFLICT'

    # If a manual server-side repair later makes the exact immutable bundle
    # valid, authoritative ACK clears only the tracker-parked generations so the
    # ordinary queue/dead-letter panel does not stay red forever.
    monkeypatch.setattr(
        shift_close_sync,
        '_request_cloud_ack',
        lambda bundle: _remote(bundle, 'ACKNOWLEDGED'),
    )
    repaired = shift_close_sync.after_push({'success': True})
    assert repaired['state'] == 'ACKNOWLEDGED'
    assert SyncQueueRecord.objects.count() == 0


@override_settings(
    SYNC_ENABLED=True,
    DEPLOYMENT_MODE='local',
    BRANCH_ID='branch-a',
    SYNC_MAX_QUEUE_ATTEMPTS=5,
)
def test_ack_identity_mismatch_fails_closed_instead_of_false_success(
    db, cashier_user, tracker_storage, monkeypatch,
):
    from base.models import SyncQueueRecord

    _shift, _rows = _make_closed_shift(cashier_user)
    shift_close_sync.prepare_for_push()
    monkeypatch.setattr(
        shift_close_sync,
        '_request_cloud_ack',
        lambda bundle: _remote(
            bundle, 'ACKNOWLEDGED', manifest_digest='0' * 64,
        ),
    )

    status = shift_close_sync.after_push({'success': True})

    assert status['state'] == 'CONFLICT'
    assert status['unresolved'][0]['reason_code'] == 'ACK_CONTRACT_MISMATCH'
    assert SyncQueueRecord.objects.filter(attempts=5).count() == 3


@override_settings(
    CLOUD_SYNC_URL='https://cloud.example/api/sync',
    CLOUD_SYNC_TOKEN='branch-secret',
    BRANCH_ID='branch-a',
    SYNC_TIMEOUT=7,
)
def test_ack_request_uses_branch_auth_and_exact_endpoint(
    db, cashier_user, tracker_storage, monkeypatch,
):
    from base.services.sync import transport

    shift, _rows = _make_closed_shift(cashier_user)
    bundle = shift_close_sync._local_bundle(shift)
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return _remote(bundle, 'PENDING')

    def fake_post(url, **kwargs):
        captured.update({'url': url, **kwargs})
        return Response()

    monkeypatch.setattr(transport.requests, 'post', fake_post)

    result = shift_close_sync._request_cloud_ack(bundle)

    assert result['state'] == 'PENDING'
    assert captured['url'] == 'https://cloud.example/api/sync/shift-close/ack'
    assert captured['headers']['Authorization'] == 'Branch branch-secret'
    assert captured['headers']['X-Branch-ID'] == 'branch-a'
    assert captured['timeout'] == 7
    assert json.loads(captured['data']) == {
        'shift_uuid': str(shift.uuid),
        'manifest_version': 3,
        'manifest_digest': bundle['manifest_digest'],
    }


def test_manual_sync_response_never_says_ok_for_unresolved_close():
    response = _attach_shift_close_status(
        {'ok': True, 'result': {'success': True}},
        {
            'state': 'PENDING', 'clear': False,
            'pending_count': 1, 'conflict_count': 0,
            'message': 'Waiting for two tender rows',
        },
    )
    assert response['ok'] is False
    assert 'awaiting cloud acknowledgement' in response['error'].lower()
    assert response['shift_close']['pending_count'] == 1


def test_ack_history_compacts_without_forgetting_old_manifest_identity():
    entries = {}
    count = shift_close_sync._ACK_HISTORY_LIMIT + 5
    for index in range(count):
        key = f'shift-{index}'
        entries[key] = {
            'shift_uuid': key,
            'shift_id': index,
            'state': 'ACKNOWLEDGED',
            'manifest_version': 3,
            'manifest_digest': f'{index:064x}',
            'digest_algorithm': shift_close_sync.DIGEST_ALGORITHM,
            'first_seen_at': f'2026-01-01T00:00:{index:06d}Z',
            'updated_at': f'2026-01-01T00:00:{index:06d}Z',
            'acknowledged_at': f'2026-01-01T00:00:{index:06d}Z',
            'message': 'large diagnostic payload',
            'settlement_rows': {'expected': 5, 'received': 5},
        }

    shift_close_sync._prune_entries(entries)

    assert len(entries) == count
    oldest = entries['shift-0']
    assert oldest['state'] == 'ACKNOWLEDGED'
    assert oldest['manifest_version'] == 3
    assert oldest['manifest_digest'] == f'{0:064x}'
    assert 'message' not in oldest
    assert entries[f'shift-{count - 1}']['message'] == 'large diagnostic payload'
