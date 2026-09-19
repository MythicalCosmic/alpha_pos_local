"""The panel drives shell-managed updates through the backend lifecycle."""

from __future__ import annotations

import json

import pytest

from desktop import bridge, config_store, lifecycle, updater


@pytest.fixture
def shell(monkeypatch, tmp_path):
    monkeypatch.setenv('ALPHA_POS_SHELL_VERSION', '1.1.0')
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config_store, 'read_config', lambda: dict(config_store.CONFIG_FIELDS))
    monkeypatch.setattr(updater, 'get_status_info', lambda: {
        'version': '1.1.0', 'enabled': False, 'reason': "tufup not available: No module named 'tufup'",
        'pending': False, 'available': None,
    })
    monkeypatch.setattr(lifecycle, 'STATE', lifecycle.Lifecycle())
    api = bridge.Api.__new__(bridge.Api)

    def publish(**status):
        (tmp_path / 'update').mkdir(exist_ok=True)
        (tmp_path / 'update' / 'shell-status.json').write_text(json.dumps(status), encoding='utf-8')

    return api, publish


def test_status_shows_what_the_shell_staged_instead_of_the_legacy_updater(shell):
    api, publish = shell
    status = api.update_status()
    # The legacy updater's "tufup not available" must not read as "disabled".
    assert status['managed_by'] == 'shell'
    assert status['enabled'] is True and status['reason'] == ''
    assert status['staged_version'] is None and status['pending'] is False

    publish(staged_version='1.1.1', checking=False, last_check_at='2026-09-19T04:00:00Z')
    status = api.update_status()
    assert status['staged_version'] == '1.1.1'
    assert status['available'] == '1.1.1'
    assert status['last_check_at'] == '2026-09-19T04:00:00Z'


def test_check_and_restart_are_requests_for_the_shell(shell):
    api, publish = shell
    before = lifecycle.STATE.snapshot()
    assert (before['update_check_seq'], before['update_restart_seq']) == (0, 0)

    assert api.check_updates_only()['requested'] is True
    assert lifecycle.STATE.snapshot()['update_check_seq'] == 1

    # Nothing staged: nothing to restart into.
    refused = api.restart_to_update()
    assert refused['ok'] is False
    assert lifecycle.STATE.snapshot()['update_restart_seq'] == 0

    publish(staged_version='1.1.1')
    assert api.restart_to_update() == {'ok': True, 'requested': True}
    assert lifecycle.STATE.snapshot()['update_restart_seq'] == 1

    # The legacy in-process installer must never run under the shell.
    assert api.check_updates_now()['ok'] is False


def test_without_the_shell_restart_to_update_is_unavailable(monkeypatch):
    monkeypatch.delenv('ALPHA_POS_SHELL_VERSION', raising=False)
    api = bridge.Api.__new__(bridge.Api)
    assert api.restart_to_update()['ok'] is False


def test_features_that_are_not_set_up_are_reported_as_such():
    assert bridge._telegram_response(False, 'Not configured') == {
        'ok': False, 'error': 'Not configured', 'not_configured': True,
    }
    # A real delivery failure stays a failure.
    assert 'not_configured' not in bridge._telegram_response(False, 'chat not found')
    assert bridge._sync_response({'success': False, 'message': 'Sync not enabled'}, operation='Cloud pull')[
        'not_configured'] is True
    assert 'not_configured' not in bridge._sync_response({'success': False, 'message': 'HTTP 502'}, operation='Cloud pull')
