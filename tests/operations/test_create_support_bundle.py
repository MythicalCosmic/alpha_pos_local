"""Support-bundle creation tests."""

import json
import sys
from pathlib import Path

import pytest

from tools import create_support_bundle


def test_support_bundle_keeps_staff_and_local_telegram_credentials_separate(
    monkeypatch,
    tmp_path,
    capsys,
):
    private_key = tmp_path / 'support.key'
    host_key = tmp_path / 'relay.pub'
    output = tmp_path / 'AlphaPOS-Support-Config.json'
    private_key.write_text(
        '-----BEGIN OPENSSH PRIVATE KEY-----\nTEST\n'
        '-----END OPENSSH PRIVATE KEY-----\n',
        encoding='utf-8',
    )
    host_key.write_text('ssh-ed25519 AAAATEST relay\n', encoding='utf-8')
    staff_token = '111111:STAFF_TEST_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    local_token = '222222:LOCAL_TEST_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    monkeypatch.setenv('STAFF_TOKEN_FOR_TEST', staff_token)
    monkeypatch.setenv('LOCAL_TOKEN_FOR_TEST', local_token)
    monkeypatch.setattr(create_support_bundle, '_protect_output', lambda _path: None)
    monkeypatch.setattr(sys, 'argv', [
        'create_support_bundle.py',
        '--private-key', str(private_key),
        '--host-public-key', str(host_key),
        '--relay-host', 'relay.example.test',
        '--output', str(output),
        '--audit-chat-ids', '-1001000000001',
        '--telegram-token-env', 'STAFF_TOKEN_FOR_TEST',
        '--local-audit-chat-ids=-1002000000002,@owner_channel',
        '--local-audit-token-env', 'LOCAL_TOKEN_FOR_TEST',
        '--local-telegram-enabled',
        '--no-local-order-paid',
        '--local-shift-report-format', 'MD',
    ])

    assert create_support_bundle.main() == 0
    payload = json.loads(output.read_text(encoding='utf-8'))['config']
    stdout = capsys.readouterr().out

    assert payload['TELEGRAM_BOT_TOKEN'] == staff_token
    assert payload['ORDER_AUDIT_TELEGRAM_CHAT_IDS'] == '-1001000000001'
    assert payload['LOCAL_TELEGRAM_AUDIT_BOT_TOKEN'] == local_token
    assert payload['LOCAL_TELEGRAM_AUDIT_CHAT_IDS'] == (
        '-1002000000002,@owner_channel'
    )
    assert payload['LOCAL_TELEGRAM_AUDIT_ENABLED'] == 'True'
    assert payload['LOCAL_TELEGRAM_ORDER_RECORDED_ENABLED'] == 'True'
    assert payload['LOCAL_TELEGRAM_ORDER_PAID_ENABLED'] == 'False'
    assert payload['LOCAL_TELEGRAM_SHIFT_REPORT_ENABLED'] == 'True'
    assert payload['LOCAL_TELEGRAM_SHIFT_REPORT_FORMAT'] == 'MD'
    assert staff_token not in stdout
    assert local_token not in stdout


def test_enabled_local_bundle_fails_closed_when_token_env_is_empty(
    monkeypatch,
    tmp_path,
    capsys,
):
    private_key = tmp_path / 'support.key'
    host_key = tmp_path / 'relay.pub'
    output = tmp_path / 'bundle.json'
    private_key.write_text('PRIVATE KEY\n', encoding='utf-8')
    host_key.write_text('ssh-ed25519 AAAATEST relay\n', encoding='utf-8')
    monkeypatch.delenv('MISSING_LOCAL_TOKEN', raising=False)
    monkeypatch.setattr(create_support_bundle, '_protect_output', lambda _path: None)
    monkeypatch.setattr(sys, 'argv', [
        'create_support_bundle.py',
        '--private-key', str(private_key),
        '--host-public-key', str(host_key),
        '--relay-host', 'relay.example.test',
        '--output', str(output),
        '--local-audit-chat-ids', '-1002000000002',
        '--local-audit-token-env', 'MISSING_LOCAL_TOKEN',
        '--local-telegram-enabled',
    ])

    with pytest.raises(SystemExit, match='token environment variable'):
        create_support_bundle.main()
    captured = capsys.readouterr()
    assert 'MISSING_LOCAL_TOKEN' not in captured.out
    assert not output.exists()


def test_support_bundle_protects_empty_temp_before_plaintext_write(
    monkeypatch,
    tmp_path,
):
    private_key = tmp_path / 'support.key'
    host_key = tmp_path / 'relay.pub'
    output = tmp_path / 'AlphaPOS-Support-Config.json'
    private_key.write_text('PRIVATE KEY\n', encoding='utf-8')
    host_key.write_text('ssh-ed25519 AAAATEST relay\n', encoding='utf-8')
    monkeypatch.setenv(
        'LOCAL_TOKEN_FOR_ORDER_TEST',
        '333333:LOCAL_TEST_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    )
    events = []
    original_open = Path.open

    def observe_open(path, *args, **kwargs):
        if path.parent == tmp_path and path.name.startswith(f'.{output.name}.'):
            events.append(('write', path.stat().st_size))
        return original_open(path, *args, **kwargs)

    def observe_protection(path):
        events.append(('protect', path.stat().st_size))

    monkeypatch.setattr(Path, 'open', observe_open)
    monkeypatch.setattr(
        create_support_bundle,
        '_protect_output',
        observe_protection,
    )
    monkeypatch.setattr(sys, 'argv', [
        'create_support_bundle.py',
        '--private-key', str(private_key),
        '--host-public-key', str(host_key),
        '--relay-host', 'relay.example.test',
        '--output', str(output),
        '--local-audit-chat-ids', '-1002000000002',
        '--local-audit-token-env', 'LOCAL_TOKEN_FOR_ORDER_TEST',
        '--local-telegram-enabled',
    ])

    assert create_support_bundle.main() == 0
    assert events == [
        ('protect', 0),
        ('write', 0),
        ('protect', output.stat().st_size),
    ]
