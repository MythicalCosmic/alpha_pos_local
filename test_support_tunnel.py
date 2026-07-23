import base64
import os
import shutil
import subprocess
import threading

import pytest

from desktop import support_tunnel


def _settings():
    private_key = (
        b'-----BEGIN OPENSSH PRIVATE KEY-----\n'
        b'test-only\n'
        b'-----END OPENSSH PRIVATE KEY-----\n'
    )
    return {
        'enabled': True,
        'host': '78.111.90.65',
        'port': '22',
        'user': 'alphapos-support',
        'remote_db_port': '15433',
        'remote_api_port': '18000',
        'private_key_b64': base64.b64encode(private_key).decode(),
        'known_host': '78.111.90.65 ssh-ed25519 AAAATESTONLY',
        'local_api_port': '8000',
    }


def test_support_tunnel_exposes_full_local_services_only_on_relay_loopback(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    monkeypatch.setattr(support_tunnel, '_ssh_executable', lambda: 'ssh.exe')

    command = support_tunnel._command(_settings())

    assert '127.0.0.1:15433:127.0.0.1:5433' in command
    assert '127.0.0.1:18000:127.0.0.1:8000' in command
    assert not any('0.0.0.0' in value for value in command)
    assert 'StrictHostKeyChecking=yes' in command
    assert 'PasswordAuthentication=no' in command
    assert command[-1] == 'alphapos-support@78.111.90.65'
    assert 'PRIVATE KEY' in (tmp_path / 'id_ed25519').read_text()
    assert (tmp_path / 'known_hosts').read_text().strip().endswith('AAAATESTONLY')
    assert _settings()['private_key_b64'] not in ' '.join(command)


def test_support_tunnel_requires_one_pinned_host_key(tmp_path, monkeypatch):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    settings = _settings()
    settings['known_host'] += '\nmalicious ssh-ed25519 AAAA'
    with pytest.raises(RuntimeError, match='single pinned'):
        support_tunnel._write_credentials(settings)


def test_support_tunnel_rejects_unsafe_host_and_invalid_ports(tmp_path, monkeypatch):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    monkeypatch.setattr(support_tunnel, '_ssh_executable', lambda: 'ssh.exe')
    settings = _settings()
    settings['host'] = 'relay;whoami'
    with pytest.raises(RuntimeError, match='unsupported characters'):
        support_tunnel._command(settings)
    settings = _settings()
    settings['remote_db_port'] = '70000'
    with pytest.raises(RuntimeError, match='between 1 and 65535'):
        support_tunnel._command(settings)


@pytest.mark.skipif(os.name != 'nt', reason='Windows OpenSSH ACL contract')
def test_written_private_key_is_accepted_by_windows_openssh(tmp_path, monkeypatch):
    keygen = shutil.which('ssh-keygen.exe') or shutil.which('ssh-keygen')
    if not keygen:
        pytest.skip('Windows OpenSSH client is not installed')
    source = tmp_path / 'source_ed25519'
    generated = subprocess.run(
        [keygen, '-q', '-t', 'ed25519', '-N', '', '-f', str(source)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=15, check=False,
    )
    assert generated.returncode == 0, generated.stderr

    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path / 'support')
    monkeypatch.setattr(
        support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'support' / 'id_ed25519',
    )
    monkeypatch.setattr(
        support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'support' / 'known_hosts',
    )
    settings = _settings()
    settings['private_key_b64'] = base64.b64encode(source.read_bytes()).decode()

    private_key, _known_hosts = support_tunnel._write_credentials(settings)
    loaded = subprocess.run(
        [keygen, '-y', '-f', str(private_key)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=15, check=False,
    )

    assert loaded.returncode == 0, loaded.stderr
    assert loaded.stdout.startswith('ssh-ed25519 ')


def test_acl_hardening_failure_removes_private_key(tmp_path, monkeypatch):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    monkeypatch.setattr(
        support_tunnel, '_harden_windows_private_key',
        lambda _path: (_ for _ in ()).throw(RuntimeError('ACL denied')),
    )

    with pytest.raises(RuntimeError, match='ACL denied'):
        support_tunnel._write_credentials(_settings())

    assert not (tmp_path / 'id_ed25519').exists()


def test_known_host_acl_hardening_failure_removes_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    calls = 0

    def harden(path):
        nonlocal calls
        calls += 1
        if path == tmp_path / 'known_hosts':
            raise RuntimeError('pin ACL denied')

    monkeypatch.setattr(support_tunnel, '_harden_windows_private_key', harden)

    with pytest.raises(RuntimeError, match='pin ACL denied'):
        support_tunnel._write_credentials(_settings())

    assert calls == 2
    assert not (tmp_path / 'known_hosts').exists()


def test_supervisor_recovers_after_transient_config_read_failure(monkeypatch):
    class StopAfterDisabledPoll:
        def __init__(self):
            self.stopped = False
            self.waits = []

        def is_set(self):
            return self.stopped

        def wait(self, delay):
            self.waits.append(delay)
            if delay == 5:
                self.stopped = True
                return True
            return False

    attempts = []

    def settings():
        attempts.append('read')
        if len(attempts) == 1:
            raise RuntimeError('temporary .env sharing violation')
        return {'enabled': False}

    stop = StopAfterDisabledPoll()
    monkeypatch.setattr(support_tunnel, '_STOP', stop)
    monkeypatch.setattr(support_tunnel, '_settings', settings)
    monkeypatch.setattr(support_tunnel, '_PROCESS', None)
    monkeypatch.setattr(support_tunnel, '_LAST_ERROR', '')

    support_tunnel._supervisor()

    assert attempts == ['read', 'read']
    assert stop.waits == [3, 5]
    assert support_tunnel._LAST_ERROR == ''


def test_restart_waits_for_slow_old_supervisor_then_restarts(monkeypatch):
    restarted = threading.Event()

    class SlowOldThread:
        alive = True

        def join(self, _timeout):
            self.alive = False

        def is_alive(self):
            return self.alive

    old = SlowOldThread()
    monkeypatch.setattr(support_tunnel, '_THREAD', old)
    monkeypatch.setattr(support_tunnel, 'stop', lambda **_kwargs: False)
    monkeypatch.setattr(
        support_tunnel, 'start', lambda: restarted.set() or True,
    )

    assert support_tunnel.restart() is True
    assert restarted.wait(1)
    assert support_tunnel._THREAD is None


def test_status_reports_ready_only_after_session_and_database_query(monkeypatch):
    class LiveProcess:
        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(support_tunnel, '_settings', _settings)
    monkeypatch.setattr(support_tunnel, '_PROCESS', LiveProcess())
    monkeypatch.setattr(support_tunnel, '_LAST_SESSION_VERIFIED_AT', '2026-07-22T12:00:00Z')
    monkeypatch.setattr(support_tunnel, '_LOCAL_DB_REACHABLE', True)
    monkeypatch.setattr(support_tunnel, '_LOCAL_DB_QUERY_VERIFIED', True)
    monkeypatch.setattr(support_tunnel, '_LOCAL_API_REACHABLE', False)
    monkeypatch.setattr(support_tunnel, '_LAST_PROBE_AT', '2026-07-22T12:00:01Z')
    monkeypatch.setattr(support_tunnel, '_LAST_PROBE_ERROR', 'local POS API is stopped')
    monkeypatch.setattr(support_tunnel, '_LAST_ERROR', '')

    result = support_tunnel.status()

    assert result['state'] == 'ready'
    assert result['ready'] is True
    assert result['local_db_query_verified'] is True
    assert result['local_api_reachable'] is False
    assert result['remote_db'] == '127.0.0.1:15433'

    monkeypatch.setattr(support_tunnel, '_LOCAL_DB_QUERY_VERIFIED', False)
    degraded = support_tunnel.status()
    assert degraded['state'] == 'degraded'
    assert degraded['ready'] is False


def test_operator_toggle_is_persisted_and_applied_immediately(monkeypatch):
    writes = []
    restarts = []
    monkeypatch.setattr(
        support_tunnel.config_store, 'write_config', lambda values: writes.append(values),
    )
    monkeypatch.setattr(support_tunnel, 'restart', lambda: restarts.append(True) or True)
    monkeypatch.setattr(
        support_tunnel, 'status', lambda: {'enabled': True, 'state': 'connecting'},
    )

    result = support_tunnel.set_enabled(True)

    assert writes == [{'SUPPORT_TUNNEL_ENABLED': 'True'}]
    assert restarts == [True]
    assert result == {'enabled': True, 'state': 'connecting'}
