"""Private-installer release tests."""

import hashlib
import json
from pathlib import Path

import pytest

from desktop import config_store, private_release
from tools import stage_private_release_payload


def _payload(values, *, schema=None):
    document = {'config': values}
    if schema is not None:
        document['schema'] = schema
    return json.dumps(document).encode()


def test_private_payload_allowlist_cannot_change_restaurant_identity():
    forbidden = {
        'BRANCH_ID',
        'CLOUD_SYNC_TOKEN',
        'CLOUD_SYNC_URL',
        'SYNC_ENABLED',
        'DB_PASSWORD',
        'LICENSE_CONTROL_CENTER_URL',
        'FISCAL_SECRET',
    }
    assert private_release.ALLOWED_PRIVATE_KEYS.isdisjoint(forbidden)
    assert (
        private_release.UPDATE_URL_KEY
        in private_release.ALLOWED_PRIVATE_KEYS
    )

    with pytest.raises(
        private_release.PrivateReleasePayloadError,
        match='forbidden settings: BRANCH_ID',
    ):
        private_release.validate_payload_bytes(
            _payload({
                'BRANCH_ID': 'wrong-restaurant',
                'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001',
            })
        )


def test_canonical_payload_accepts_only_current_schema():
    raw = _payload(
        {'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001'},
        schema='alphapos.private-support.v1',
    )
    canonical = private_release.canonical_payload_bytes(raw)
    document = json.loads(canonical)

    assert document['schema'] == 'alphapos.private-support.v1'
    assert document['config'] == {
        'ALPHA_POS_UPDATE_URL': private_release.CANONICAL_UPDATE_URL,
        'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001',
    }

    with pytest.raises(
        private_release.PrivateReleasePayloadError,
        match='unsupported schema',
    ):
        private_release.validate_payload_bytes(
            _payload(
                {'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001'},
                schema='alphapos.private-support.v2',
            )
        )


@pytest.mark.parametrize(
    'alternate',
    [
        'https://updates.example.invalid/updates',
        private_release.CANONICAL_UPDATE_URL + '/',
        ' ' + private_release.CANONICAL_UPDATE_URL,
    ],
)
def test_private_payload_rejects_every_noncanonical_update_url(alternate):
    with pytest.raises(
        private_release.PrivateReleasePayloadError,
        match='non-canonical update URL',
    ):
        private_release.validate_payload_bytes(
            _payload({
                'ALPHA_POS_UPDATE_URL': alternate,
                'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001',
            })
        )


def test_staged_payload_repairs_blank_update_url_on_apply(
    tmp_path,
    monkeypatch,
):
    payload = tmp_path / private_release.PAYLOAD_FILENAME
    marker = tmp_path / 'applied'
    # The protected source does not need to be edited; canonical staging injects
    # the updater endpoint and therefore changes the installed payload digest.
    staged = private_release.canonical_payload_bytes(
        _payload({'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001'})
    )
    payload.write_bytes(staged)
    current = dict(config_store.CONFIG_FIELDS)
    current['ALPHA_POS_UPDATE_URL'] = ''
    writes = []

    monkeypatch.setattr(
        config_store, '_harden_windows_private_path',
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(config_store, 'read_config', lambda: dict(current))

    def write_config(values):
        writes.append(dict(values))
        current.update(values)

    monkeypatch.setattr(config_store, 'write_config', write_config)
    monkeypatch.setattr(
        config_store, '_write_protected',
        lambda path, text: Path(path).write_text(text, encoding='ascii'),
    )

    result = private_release.apply_private_payload(
        payload,
        marker_path=marker,
    )

    assert result['status'] == 'applied'
    assert writes == [{
        'ALPHA_POS_UPDATE_URL': private_release.CANONICAL_UPDATE_URL,
        'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001',
    }]
    assert (
        current['ALPHA_POS_UPDATE_URL']
        == dict(config_store.CONFIG_FIELDS)['ALPHA_POS_UPDATE_URL']
    )
    assert not payload.exists()


def test_apply_hardens_then_merges_without_erasing_identity_or_secrets(
    tmp_path,
    monkeypatch,
):
    payload = tmp_path / private_release.PAYLOAD_FILENAME
    marker = tmp_path / 'applied'
    raw = _payload({
        'SUPPORT_TUNNEL_HOST': 'relay.example',
        'SUPPORT_TUNNEL_PRIVATE_KEY_B64': '',
        'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': '',
        'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001',
    })
    payload.write_bytes(raw)
    current = dict(config_store.CONFIG_FIELDS)
    current.update({
        'BRANCH_ID': 'restaurant-42',
        'CLOUD_SYNC_TOKEN': 'existing-cloud-token',
        'CLOUD_SYNC_URL': 'https://existing.example/sync',
        'SUPPORT_TUNNEL_HOST': 'old-relay.example',
        'SUPPORT_TUNNEL_PRIVATE_KEY_B64': 'existing-support-private-key',
        'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': (
            '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456'
        ),
    })
    hardened = []
    writes = []

    monkeypatch.setattr(
        config_store, '_harden_windows_private_path',
        lambda path, **_kwargs: hardened.append(Path(path)),
    )
    monkeypatch.setattr(
        private_release,
        'validate_payload_bytes',
        lambda _raw: json.loads(_raw)['config'],
    )
    monkeypatch.setattr(
        private_release,
        '_prepare_local_telegram',
        lambda incoming, current: {
            key: (
                current[key]
                if key == 'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'
                and not str(value or '').strip()
                else value
            )
            for key, value in incoming.items()
            if key.startswith('LOCAL_TELEGRAM_')
        },
    )
    monkeypatch.setattr(
        config_store, 'read_config', lambda: dict(current),
    )

    def write_config(values):
        writes.append(dict(values))
        current.update(values)

    monkeypatch.setattr(config_store, 'write_config', write_config)
    monkeypatch.setattr(
        config_store, '_write_protected',
        lambda path, text: Path(path).write_text(text, encoding='ascii'),
    )

    result = private_release.apply_private_payload(
        payload,
        marker_path=marker,
    )

    assert result['status'] == 'applied'
    assert hardened == [payload]
    assert not payload.exists()
    assert marker.read_text().strip() == hashlib.sha256(raw).hexdigest()
    assert current['BRANCH_ID'] == 'restaurant-42'
    assert current['CLOUD_SYNC_TOKEN'] == 'existing-cloud-token'
    assert current['CLOUD_SYNC_URL'] == 'https://existing.example/sync'
    assert (
        current['SUPPORT_TUNNEL_PRIVATE_KEY_B64']
        == 'existing-support-private-key'
    )
    assert (
        current['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN']
        == '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456'
    )
    assert current['SUPPORT_TUNNEL_HOST'] == 'relay.example'
    assert current['ORDER_AUDIT_TELEGRAM_CHAT_IDS'] == '1001'
    assert 'BRANCH_ID' not in writes[0]
    assert 'CLOUD_SYNC_TOKEN' not in writes[0]


def test_applied_digest_makes_leftover_payload_inert(tmp_path, monkeypatch):
    payload = tmp_path / private_release.PAYLOAD_FILENAME
    marker = tmp_path / 'applied'
    raw = _payload({'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001'})
    payload.write_bytes(raw)
    marker.write_text(hashlib.sha256(raw).hexdigest() + '\n')
    monkeypatch.setattr(
        config_store, '_harden_windows_private_path',
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        config_store,
        'write_config',
        lambda _values: (_ for _ in ()).throw(
            AssertionError('already-applied payload must not write')
        ),
    )

    result = private_release.apply_private_payload(
        payload,
        marker_path=marker,
    )

    assert result == {'status': 'already_applied', 'imported_count': 0}
    assert not payload.exists()


def test_stager_writes_only_canonical_ignored_payload(tmp_path, monkeypatch):
    source = tmp_path / 'source.json'
    destination = tmp_path / 'build' / 'private-release' / 'payload.json'
    source.write_bytes(_payload({'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001'}))
    hardened = []
    monkeypatch.setattr(
        stage_private_release_payload,
        '_harden_windows_private_key',
        lambda path, **kwargs: hardened.append((Path(path), kwargs)),
    )

    stage_private_release_payload.stage(source, destination)

    staged = json.loads(destination.read_text())
    assert staged['schema'] == 'alphapos.private-support.v1'
    assert staged['config'] == {
        'ALPHA_POS_UPDATE_URL': private_release.CANONICAL_UPDATE_URL,
        'ORDER_AUDIT_TELEGRAM_CHAT_IDS': '1001',
    }
    if stage_private_release_payload.os.name == 'nt':
        assert hardened[0] == (destination.parent, {'rights': 'F'})
        assert hardened[1] == (destination, {'rights': 'F'})


def test_build_contract_keeps_private_payload_opt_in():
    root = Path(__file__).resolve().parents[2]
    installer = (root / 'installer' / 'AlphaPOS.iss').read_text()
    build = (root / 'build_installer.ps1').read_text()
    onedir = (root / 'AlphaPOS.spec').read_text()
    onefile = (root / 'AlphaPOS-onefile.spec').read_text()
    ignored = (root / '.gitignore').read_text()

    assert '#ifdef PrivateSupportPayload' in installer
    assert 'AlphaPOS-{#AppVersion}-Private-Setup' in installer
    assert 'DestName: ".alphapos-private-support.json"' in installer
    assert '[string]$PrivateSupportConfig' in build
    assert 'check-ignore --quiet' in build
    assert '/DPrivateSupportPayload=' in build
    assert 'finally {' in build
    assert 'private_release_bootstrap.py' in onedir
    assert 'private_release_bootstrap.py' in onefile
    assert '/build/private-release/' in ignored
