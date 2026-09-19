"""Saving settings from the panel must only act on what the operator changed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from desktop import bridge, config_store, support_tunnel

MASK = '••••••••'


def _api(monkeypatch, current, *, running=True):
    writes, restarts = [], []
    monkeypatch.setattr(config_store, 'read_config', lambda: dict(current))
    monkeypatch.setattr(config_store, 'write_config', lambda values: writes.append(dict(values)))
    monkeypatch.setattr(support_tunnel, 'restart', lambda: restarts.append(True) or True)
    api = bridge.Api.__new__(bridge.Api)
    api.server = SimpleNamespace(is_running=lambda: running, ensure_django=lambda: None)
    return api, writes, restarts


@pytest.mark.django_db
def test_saving_the_whole_form_keeps_staff_telegram_recipients(monkeypatch):
    from notifications.models import NotificationSettings

    settings = NotificationSettings.load()
    settings.chat_ids = ['111', '222']
    settings.bot_token = 'staff-token'
    settings.save()

    current = dict(config_store.CONFIG_FIELDS)
    current.update({'TELEGRAM_CHAT_IDS': '', 'TELEGRAM_BOT_TOKEN': '', 'CLOUD_SYNC_TOKEN': 'secret'})
    api, writes, restarts = _api(monkeypatch, current)

    # The 1.1.0 panel posted every field, secrets masked, recipients blank.
    form = dict(current, CLOUD_SYNC_TOKEN=MASK, CLOUD_SYNC_URL='https://example.test/api/sync')
    result = api.save_config(form)

    assert result['ok'] is True
    saved = NotificationSettings.load()
    assert saved.chat_ids == ['111', '222']
    assert saved.bot_token == 'staff-token'
    assert restarts == []  # untouched tunnel settings do not restart the tunnel
    assert writes[0]['CLOUD_SYNC_TOKEN'] == 'secret'
    assert result['changed'] == ['CLOUD_SYNC_URL']
    assert result['restart_required'] is False  # sync URL applies live


@pytest.mark.django_db
def test_changed_recipients_and_token_reach_the_database(monkeypatch):
    from notifications.models import NotificationSettings

    current = dict(config_store.CONFIG_FIELDS)
    api, _writes, _restarts = _api(monkeypatch, current)

    result = api.save_config({'TELEGRAM_CHAT_IDS': '333, 444', 'TELEGRAM_BOT_TOKEN': ' new-token '})

    assert result['ok'] is True
    saved = NotificationSettings.load()
    assert saved.chat_ids == ['333', '444']
    assert saved.bot_token == 'new-token'


def test_port_change_needs_a_restart_and_tunnel_change_restarts_the_tunnel(monkeypatch):
    current = dict(config_store.CONFIG_FIELDS)
    api, _writes, restarts = _api(monkeypatch, current)

    assert api.save_config({'PORT': '8010'})['restart_required'] is True
    assert restarts == []
    tunnel = api.save_config({'SUPPORT_TUNNEL_HOST': '78.111.90.65'})
    assert tunnel['restart_required'] is False
    assert restarts == [True]

    stopped, _w, _r = _api(monkeypatch, current, running=False)
    assert stopped.save_config({'PORT': '8010'})['restart_required'] is False
