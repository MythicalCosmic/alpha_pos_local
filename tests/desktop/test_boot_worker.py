"""Launcher boot-worker and server status regressions."""
import threading




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


class _FakeKey:
    def __init__(self, version):
        self.version = version

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_winreg(installed):
    """A winreg stand-in where only the keys in ``installed`` exist."""
    import types

    def open_key(hive, path):
        if path not in installed:
            raise OSError(2, 'not found')
        return _FakeKey(installed[path])

    return types.SimpleNamespace(
        HKEY_LOCAL_MACHINE='HKLM', HKEY_CURRENT_USER='HKCU',
        OpenKey=open_key, QueryValueEx=lambda key, name: (key.version, 1),
    )


def test_webview2_runtime_is_detected_per_machine_or_user(monkeypatch):
    import sys

    from desktop import app

    runtime = r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    monkeypatch.setitem(sys.modules, 'winreg', _fake_winreg({runtime: '131.0.2903.70'}))
    assert app._webview2_installed() is True
    monkeypatch.setitem(sys.modules, 'winreg', _fake_winreg({runtime: '0.0.0.0'}))
    assert app._webview2_installed() is False
    monkeypatch.setitem(sys.modules, 'winreg', _fake_winreg({}))
    assert app._webview2_installed() is False


def test_no_webview2_means_no_blank_ie_window(monkeypatch):
    import sys

    from desktop import app

    monkeypatch.setattr(app, '_webview2_installed', lambda: False)
    monkeypatch.setitem(sys.modules, 'webview', None)  # importing it would fail loudly
    assert app._run_pywebview('http://127.0.0.1:8765/') is False


def test_native_window_allows_downloads_and_keeps_its_profile(monkeypatch):
    import sys
    import types

    from desktop import app

    calls = {}
    fake = types.SimpleNamespace(
        settings={'ALLOW_DOWNLOADS': False},
        create_window=lambda *a, **k: calls.setdefault('window', (a, k)),
        start=lambda **k: calls.setdefault('start', k),
    )
    monkeypatch.setattr(app, '_webview2_installed', lambda: True)
    monkeypatch.setattr(app, '_profile_dir', lambda: '/data/AlphaPOS/edge-profile')
    monkeypatch.setitem(sys.modules, 'webview', fake)

    assert app._run_pywebview('http://127.0.0.1:8765/') is True
    # Config -> Export is a download; pywebview cancels downloads by default.
    assert fake.settings['ALLOW_DOWNLOADS'] is True
    assert calls['start']['gui'] == 'edgechromium'
    assert calls['start']['private_mode'] is False
    assert calls['start']['storage_path'].endswith('webview2-profile')
