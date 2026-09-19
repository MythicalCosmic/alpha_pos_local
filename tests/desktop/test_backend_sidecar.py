"""Windowless backend contract used by the Tauri desktop shell."""
import http.client
import json
import os
import threading
import time
from pathlib import Path

import pytest

from desktop import control_server as cs
from desktop import lifecycle, shutdown

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fresh_lifecycle(monkeypatch):
    state = lifecycle.Lifecycle()
    monkeypatch.setattr(lifecycle, 'STATE', state)
    return state


@pytest.fixture
def panel():
    httpd = cs.serve(preferred_port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def _request(port, method, path, token=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'Host': f'127.0.0.1:{port}'}
    if token is not None:
        headers['X-Control-Token'] = token
    conn.request(method, path, body=b'' if method == 'POST' else None, headers=headers)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, json.loads(body)


def test_shell_token_is_used_and_removed_from_environment(tmp_path, monkeypatch):
    from desktop import config_store
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    token = 'shell-token-' + 'x' * 40
    monkeypatch.setenv(cs.SHELL_TOKEN_ENV, token)

    assert cs._load_or_make_token() == token
    assert cs.SHELL_TOKEN_ENV not in os.environ
    # The shell token is per launch and must not overwrite the persisted one.
    assert not (tmp_path / '.control_token').exists()


def test_short_shell_token_is_ignored(tmp_path, monkeypatch):
    from desktop import config_store
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    monkeypatch.setenv(cs.SHELL_TOKEN_ENV, 'short')

    assert cs._load_or_make_token() != 'short'
    assert cs.SHELL_TOKEN_ENV not in os.environ


def test_lifecycle_endpoint_requires_the_token(panel, fresh_lifecycle):
    fresh_lifecycle.set('database')

    status, body = _request(panel, 'GET', '/lifecycle')
    assert status == 403 and body['ok'] is False

    status, body = _request(panel, 'GET', '/lifecycle', token=cs.CONTROL_TOKEN)
    assert status == 200
    assert body['phase'] == 'database'
    assert body['pid'] == os.getpid()


def test_shutdown_endpoint_runs_handler_once(panel, fresh_lifecycle):
    calls = []
    done = threading.Event()
    fresh_lifecycle.set_shutdown_handler(lambda: (calls.append(1), done.set()))

    status, _ = _request(panel, 'POST', '/lifecycle/shutdown')
    assert status == 403
    assert not calls

    status, body = _request(panel, 'POST', '/lifecycle/shutdown', token=cs.CONTROL_TOKEN)
    assert status == 200 and body['accepted'] is True and body['phase'] == 'stopping'
    assert done.wait(2)

    status, body = _request(panel, 'POST', '/lifecycle/shutdown', token=cs.CONTROL_TOKEN)
    assert body['accepted'] is False
    assert calls == [1]


def test_stopping_phase_is_not_overwritten_by_boot_progress(fresh_lifecycle):
    fresh_lifecycle.set_shutdown_handler(lambda: None)
    fresh_lifecycle.request_shutdown()
    fresh_lifecycle.set('serving')
    assert fresh_lifecycle.snapshot()['phase'] == 'stopping'
    with pytest.raises(ValueError):
        fresh_lifecycle.set('bogus')


def test_ready_file_is_written_atomically(tmp_path):
    target = tmp_path / 'run' / 'backend-ready.json'
    lifecycle.write_ready_file(target, port=51234, version='1.1.0')

    payload = json.loads(target.read_text(encoding='utf-8'))
    assert payload['port'] == 51234
    assert payload['pid'] == os.getpid()
    assert payload['version'] == '1.1.0'
    assert [p.name for p in target.parent.iterdir()] == ['backend-ready.json']


def test_parent_watch_fires_when_parent_disappears():
    alive = {'value': True}
    fired = threading.Event()
    lifecycle.watch_parent(1234, fired.set, interval=0.01, alive=lambda pid: alive['value'])
    time.sleep(0.05)
    assert not fired.is_set()
    alive['value'] = False
    assert fired.wait(1)


def test_pid_alive_for_self_and_invalid_pids():
    assert lifecycle.pid_alive(os.getpid())
    assert not lifecycle.pid_alive(0)
    assert not lifecycle.pid_alive('not-a-pid')


def test_shutdown_stops_postgres_last():
    order = []
    steps = {
        'optional_workers': lambda: order.append('optional_workers'),
        'pos_server': lambda: order.append('pos_server'),
        'db_connections': lambda: order.append('db_connections'),
        'postgres': lambda: order.append('postgres'),
    }
    result = shutdown.stop_backend(budget=20, steps=steps)

    assert order[-2:] == ['db_connections', 'postgres']
    assert set(order[:2]) == {'optional_workers', 'pos_server'}
    assert result['postgres_stopped'] is True


def test_hung_workers_cannot_starve_postgres():
    release = threading.Event()
    postgres_calls = []
    steps = {
        'optional_workers': lambda: release.wait(10),
        'pos_server': lambda: None,
        'db_connections': lambda: None,
        'postgres': lambda: postgres_calls.append(time.monotonic()),
    }
    budget = 4.0  # reserve = half the budget, so workers may use at most ~2 s
    started = time.monotonic()
    try:
        result = shutdown.stop_backend(budget=budget, steps=steps)
    finally:
        release.set()

    assert postgres_calls, 'postgres stop must still run'
    assert postgres_calls[0] - started <= budget / 2 + 0.6
    assert result['optional_workers']['finished'] is False
    assert result['postgres_stopped'] is True


def test_postgres_failure_is_reported():
    def boom():
        raise RuntimeError('pg_ctl failed')

    steps = {name: (lambda: None) for name in ('optional_workers', 'pos_server', 'db_connections')}
    steps['postgres'] = boom
    result = shutdown.stop_backend(budget=3, steps=steps)
    assert result['postgres_stopped'] is False
    assert 'pg_ctl failed' in result['postgres']['error']


def test_backend_args_parse():
    from desktop import backend_main
    args = backend_main.parse_args(['--parent-pid', '42', '--ready-file', 'C:/x/ready.json'])
    assert args.parent_pid == 42 and args.ready_file == 'C:/x/ready.json' and not args.selftest


def test_boot_worker_can_skip_the_legacy_updater(monkeypatch):
    from desktop import app, control_server
    calls = []
    monkeypatch.setattr(control_server._API.server, 'ensure_django', lambda **kwargs: None)
    monkeypatch.setattr('desktop.support_tunnel.start', lambda: None)
    monkeypatch.setattr(app.atexit, 'register', lambda *a, **k: None)
    monkeypatch.setattr(app.threading, 'Thread', lambda **kw: type('T', (), {'start': lambda self: calls.append(kw['name'])})())
    monkeypatch.setattr('desktop.updater.check_only', lambda: calls.append('check_only'))

    app._boot_worker(shutdown_event=threading.Event(), check_updates=False)

    assert calls == ['autostart']


def test_server_status_reports_started_at_only_while_running():
    from desktop.server_manager import ServerManager
    manager = ServerManager()
    manager._started_at = '2026-09-16T08:00:00+00:00'
    manager.lan_ip = lambda force=False: '127.0.0.1'
    assert manager.status()['started_at'] is None


def test_backend_mutex_name_is_distinct():
    from desktop import single_instance
    assert single_instance.BACKEND_MUTEX_NAME != single_instance._MUTEX_NAME
    assert single_instance.acquire(single_instance.BACKEND_MUTEX_NAME) is True


def test_backend_spec_is_windowless_console_without_gui_or_updater():
    spec = (ROOT / 'AlphaPOSBackend.spec').read_text(encoding='utf-8')
    assert "'desktop', 'backend_main.py'" in spec
    assert "name='AlphaPOSBackend'" in spec
    assert 'console=True' in spec
    code = '\n'.join(
        line for line in spec.splitlines()
        if not line.lstrip().startswith('#') and 'excludes=' not in line
    )
    for forbidden in ('webview', 'tufup', 'tuf_root', 'update_helper.ps1', 'clr_loader'):
        assert forbidden not in code
    assert "'webview'" in spec and "'tufup'" in spec  # explicitly excluded
    assert "('desktop/ui', 'desktop/ui')" in spec


def test_update_status_reports_updates_managed_by_the_shell(monkeypatch):
    from desktop import updater
    from desktop.bridge import Api
    monkeypatch.setattr(updater, 'get_status_info', lambda: {'version': '1.1.0', 'enabled': False})
    monkeypatch.setattr(Api, '_ensure_update_env', lambda self: None)

    monkeypatch.delenv('ALPHA_POS_SHELL_VERSION', raising=False)
    assert 'managed_by' not in Api().update_status()

    monkeypatch.setenv('ALPHA_POS_SHELL_VERSION', '1.1.0')
    status = Api().update_status()
    assert status['managed_by'] == 'shell' and status['shell_version'] == '1.1.0'

