"""Desktop configuration-import contract tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from desktop import bridge, config_store, local_telegram_audit, support_tunnel


ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / 'desktop' / 'ui' / 'app' / 'config-import.js'
MASK = '••••••••'


def _parse_with_node(source, recognized):
    script = """
const parser = require(process.argv[1]);
const source = process.argv[2];
const recognized = JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify(parser.parseConfigImport(source, recognized)));
"""
    result = subprocess.run(
        ['node', '-e', script, str(PARSER), source, json.dumps(recognized)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)


def test_ui_parser_accepts_wrapped_support_json_and_filters_unknown_keys():
    payload = json.dumps({
        'config': {
            'SUPPORT_TUNNEL_ENABLED': 'True',
            'SUPPORT_TUNNEL_HOST': '78.111.90.65',
            'SUPPORT_TUNNEL_PRIVATE_KEY_B64': 'private-value',
            'UNMANAGED_SETTING': 'must-not-cross-the-bridge',
        },
    })

    parsed = _parse_with_node(payload, [
        'SUPPORT_TUNNEL_ENABLED',
        'SUPPORT_TUNNEL_HOST',
        'SUPPORT_TUNNEL_PRIVATE_KEY_B64',
    ])

    assert parsed == {
        'ok': True,
        'data': {
            'SUPPORT_TUNNEL_ENABLED': 'True',
            'SUPPORT_TUNNEL_HOST': '78.111.90.65',
            'SUPPORT_TUNNEL_PRIVATE_KEY_B64': 'private-value',
        },
    }


def test_ui_parser_keeps_legacy_key_value_import_compatible():
    parsed = _parse_with_node(
        '# legacy export\nPORT=8123\nSUPPORT_TUNNEL_ENABLED=True\nUNKNOWN=x\n',
        ['PORT', 'SUPPORT_TUNNEL_ENABLED'],
    )

    assert parsed == {
        'ok': True,
        'data': {'PORT': '8123', 'SUPPORT_TUNNEL_ENABLED': 'True'},
    }


def test_ui_parser_rejects_invalid_json_and_unrecognized_files():
    invalid = _parse_with_node(
        '{"config": ',
        ['SUPPORT_TUNNEL_ENABLED'],
    )
    unknown = _parse_with_node(
        '{"config": {"NOT_ALPHA_POS": true}}',
        ['SUPPORT_TUNNEL_ENABLED'],
    )

    assert invalid == {
        'ok': False,
        'error': 'The configuration JSON is invalid.',
    }
    assert unknown == {
        'ok': False,
        'error': 'The file contains no recognized Alpha POS settings.',
    }


def test_config_picker_accepts_json_support_bundles():
    source = (
        ROOT / 'desktop' / 'ui' / 'app' / 'screens-admin.jsx'
    ).read_text(encoding='utf-8')

    assert 'accept=".env,.json,text/plain,application/json"' in source


def test_bridge_import_preserves_masked_secret_and_restarts_tunnel(monkeypatch):
    current = dict(config_store.CONFIG_FIELDS)
    current.update({
        'SUPPORT_TUNNEL_ENABLED': 'False',
        'SUPPORT_TUNNEL_HOST': '',
        'SUPPORT_TUNNEL_PRIVATE_KEY_B64': 'existing-private-key',
    })
    writes = []
    restarts = []
    monkeypatch.setattr(config_store, 'read_config', lambda: dict(current))
    monkeypatch.setattr(
        config_store, 'write_config', lambda values: writes.append(dict(values)),
    )
    monkeypatch.setattr(
        support_tunnel, 'restart', lambda: restarts.append(True) or True,
    )
    api = bridge.Api.__new__(bridge.Api)
    api.server = SimpleNamespace(is_running=lambda: True)

    result = api.import_config({
        'config': {
            'SUPPORT_TUNNEL_ENABLED': 'True',
            'SUPPORT_TUNNEL_HOST': '78.111.90.65',
            'SUPPORT_TUNNEL_PRIVATE_KEY_B64': MASK,
            'UNMANAGED_SETTING': 'ignored',
        },
    })

    assert result['ok'] is True
    assert result['restart_required'] is True
    assert writes == [{
        'SUPPORT_TUNNEL_ENABLED': 'True',
        'SUPPORT_TUNNEL_HOST': '78.111.90.65',
        'SUPPORT_TUNNEL_PRIVATE_KEY_B64': 'existing-private-key',
    }]
    assert restarts == [True]


def test_bridge_rejects_non_object_wrapper_and_unknown_only_payload(monkeypatch):
    monkeypatch.setattr(config_store, 'read_config', lambda: {})
    monkeypatch.setattr(
        config_store,
        'write_config',
        lambda _values: (_ for _ in ()).throw(AssertionError('must not write')),
    )
    api = bridge.Api.__new__(bridge.Api)
    api.server = SimpleNamespace(is_running=lambda: False)

    invalid = api.import_config({'config': []})
    unknown = api.import_config({'NOT_ALPHA_POS': 'value'})

    assert invalid == {'ok': False, 'error': 'Expected config to be an object'}
    assert unknown == {
        'ok': False,
        'error': 'No recognised settings in the file',
    }


def test_bridge_import_applies_local_telegram_config_immediately(monkeypatch):
    current = dict(config_store.CONFIG_FIELDS)
    current['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'] = (
        '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef'
    )
    writes = []
    started = []
    woke = []
    django_ready = []
    watermarks = []
    monkeypatch.setattr(config_store, 'read_config', lambda: dict(current))
    monkeypatch.setattr(
        config_store, 'write_config', lambda values: writes.append(dict(values)),
    )
    monkeypatch.setattr(
        local_telegram_audit,
        'start_background_notifier',
        lambda: started.append(True),
    )
    monkeypatch.setattr(
        local_telegram_audit,
        'wake',
        lambda: woke.append(True),
    )
    monkeypatch.setattr(
        local_telegram_audit,
        '_reset_enable_watermark',
        lambda moment=None: watermarks.append(moment),
    )
    api = bridge.Api.__new__(bridge.Api)
    api.server = SimpleNamespace(
        ensure_django=lambda: django_ready.append(True),
        is_running=lambda: True,
    )

    result = api.import_config({
        'config': {
            'LOCAL_TELEGRAM_AUDIT_ENABLED': 'True',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': MASK,
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '-1002000000002',
        },
    })

    assert result['ok'] is True
    assert writes == [{
        'LOCAL_TELEGRAM_AUDIT_ENABLED': 'True',
        'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': (
            '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef'
        ),
        'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '-1002000000002',
    }]
    assert len(watermarks) == 1
    assert django_ready == [True]
    assert started == [True]
    assert woke == [True]


def test_bridge_import_rejects_invalid_local_telegram_before_write_or_watermark(
    monkeypatch,
):
    current = dict(config_store.CONFIG_FIELDS)
    writes = []
    monkeypatch.setattr(config_store, 'read_config', lambda: dict(current))
    monkeypatch.setattr(
        config_store, 'write_config', lambda values: writes.append(dict(values)),
    )
    monkeypatch.setattr(
        local_telegram_audit,
        '_reset_enable_watermark',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('invalid import must not move the watermark'),
        ),
    )
    api = bridge.Api.__new__(bridge.Api)
    api.server = SimpleNamespace(is_running=lambda: False)

    result = api.import_config({
        'config': {
            'LOCAL_TELEGRAM_AUDIT_ENABLED': 'True',
            'LOCAL_TELEGRAM_AUDIT_BOT_TOKEN': 'not-a-telegram-token',
            'LOCAL_TELEGRAM_AUDIT_CHAT_IDS': '-1002000000002',
        },
    })

    assert result['ok'] is False
    assert 'token format is invalid' in result['error']
    assert writes == []
