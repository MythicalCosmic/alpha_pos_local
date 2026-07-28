"""Restricted support-tunnel tests."""

import base64
import os
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from desktop import support_tunnel


def _ed25519_public_blob(seed: bytes = b'\x01' * 32) -> str:
    algorithm = b'ssh-ed25519'
    blob = (
        len(algorithm).to_bytes(4, 'big') + algorithm
        + len(seed).to_bytes(4, 'big') + seed
    )
    return base64.b64encode(blob).decode()


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
        'known_host': (
            '78.111.90.65 ssh-ed25519 '
            + _ed25519_public_blob()
        ),
        'local_db_port': '5433',
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
    assert ['-F', os.devnull] == command[1:3]
    assert f'GlobalKnownHostsFile={os.devnull}' in command
    assert 'IdentityAgent=none' in command
    assert 'ProxyCommand=none' in command
    assert 'HostKeyAlgorithms=ssh-ed25519' in command
    assert command[-1] == 'alphapos-support@78.111.90.65'
    assert 'PRIVATE KEY' in (tmp_path / 'id_ed25519').read_text()
    assert (
        (tmp_path / 'known_hosts').read_text().strip()
        == _settings()['known_host']
    )
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
    with pytest.raises(RuntimeError, match='not a valid'):
        support_tunnel._command(settings)
    settings = _settings()
    settings['remote_db_port'] = '70000'
    with pytest.raises(RuntimeError, match='between 1 and 65535'):
        support_tunnel._command(settings)


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('user', 'support@root', 'safe SSH account'),
        ('remote_db_port', '22', 'unprivileged'),
        ('remote_api_port', '15433', 'must be different'),
        (
            'known_host',
            'other.example ssh-ed25519 ' + _ed25519_public_blob(),
            'does not match',
        ),
        (
            'known_host',
            '78.111.90.65 ssh-rsa ' + _ed25519_public_blob(),
            'must use ssh-ed25519',
        ),
        (
            'known_host',
            '78.111.90.65 ssh-ed25519 ' + base64.b64encode(b'bad').decode(),
            'not an Ed25519',
        ),
        (
            'known_host',
            '78.111.90.65 ssh-ed25519 ' + base64.b64encode(
                base64.b64decode(_ed25519_public_blob())[:-1]
            ).decode(),
            'not an Ed25519',
        ),
        (
            'known_host',
            '78.111.90.65 ssh-ed25519 ' + base64.b64encode(
                base64.b64decode(_ed25519_public_blob()) + b'trailing'
            ).decode(),
            'not an Ed25519',
        ),
    ],
)
def test_configuration_rejects_unsafe_ssh_boundary(field, value, message):
    settings = _settings()
    settings[field] = value
    with pytest.raises(RuntimeError, match=message):
        support_tunnel._validate_configuration(settings)


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


@pytest.mark.skipif(os.name != 'nt', reason='Windows icacls contract')
def test_windows_directory_acl_is_inheritable_and_private(tmp_path, monkeypatch):
    directory = tmp_path / 'support'
    directory.mkdir()
    private_key = directory / 'id_ed25519'
    private_key.write_text('test')
    commands = []

    def hidden_run(command, **_kwargs):
        commands.append(command)
        if command[0] == 'whoami.exe':
            return subprocess.CompletedProcess(
                command, 0, '"DESKTOP\\\\tester","S-1-5-21-1000"\r\n', '',
            )
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(support_tunnel, '_windows_executable', lambda name: name)
    monkeypatch.setattr(support_tunnel, '_hidden_run', hidden_run)

    support_tunnel._harden_windows_private_key(directory, rights='F')
    support_tunnel._harden_windows_private_key(private_key)

    icacls = [command for command in commands if command[0] == 'icacls.exe']
    assert '*S-1-5-21-1000:(OI)(CI)(F)' in icacls[0]
    assert '*S-1-5-21-1000:(R)' in icacls[1]


def test_acl_hardening_failure_removes_private_key(tmp_path, monkeypatch):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    def harden(path, **_kwargs):
        if path == tmp_path / 'id_ed25519':
            raise RuntimeError('ACL denied')

    monkeypatch.setattr(support_tunnel, '_harden_windows_private_key', harden)

    with pytest.raises(RuntimeError, match='ACL denied'):
        support_tunnel._write_credentials(_settings())

    assert not (tmp_path / 'id_ed25519').exists()


def test_known_host_acl_hardening_failure_removes_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(support_tunnel, 'SUPPORT_DIR', tmp_path)
    monkeypatch.setattr(support_tunnel, 'PRIVATE_KEY_FILE', tmp_path / 'id_ed25519')
    monkeypatch.setattr(support_tunnel, 'KNOWN_HOSTS_FILE', tmp_path / 'known_hosts')
    calls = 0

    def harden(path, **_kwargs):
        nonlocal calls
        if path != tmp_path:
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


def test_supervisor_never_queries_database_before_ssh_session_is_verified(
    monkeypatch,
):
    class StopBeforeVerification:
        def __init__(self):
            self.stopped = False
            self.one_second_waits = 0

        def is_set(self):
            return self.stopped

        def wait(self, delay):
            if delay == 1:
                self.one_second_waits += 1
                if self.one_second_waits == 3:
                    self.stopped = True
                    return True
            return False

    class Process:
        alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self, **_kwargs):
            self.alive = False
            return 0

    probes = []
    stop = StopBeforeVerification()
    monkeypatch.setattr(support_tunnel, '_STOP', stop)
    monkeypatch.setattr(support_tunnel, '_settings', _settings)
    monkeypatch.setattr(support_tunnel, '_command', lambda _settings: ['ssh'])
    monkeypatch.setattr(support_tunnel, '_hidden_popen', lambda _command: Process())
    monkeypatch.setattr(
        support_tunnel, '_probe_local_targets',
        lambda _settings: probes.append(True),
    )
    monkeypatch.setattr(support_tunnel, '_PROCESS', None)

    support_tunnel._supervisor()

    assert probes == []


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
    monkeypatch.setattr(support_tunnel, '_LOCAL_API_REACHABLE', True)
    monkeypatch.setattr(support_tunnel, '_LAST_PROBE_AT', '2026-07-22T12:00:01Z')
    monkeypatch.setattr(support_tunnel, '_LAST_PROBE_MONOTONIC', time.monotonic())
    monkeypatch.setattr(support_tunnel, '_LAST_DB_PROBE_ERROR', '')
    monkeypatch.setattr(support_tunnel, '_LAST_API_PROBE_ERROR', '')
    monkeypatch.setattr(support_tunnel, '_LAST_PROBE_ERROR', '')
    monkeypatch.setattr(support_tunnel, '_LAST_ERROR', '')

    result = support_tunnel.status()

    assert result['state'] == 'ready'
    assert result['ready'] is True
    assert result['db_ready'] is True
    assert result['backend_ready'] is True
    assert result['connected'] is True
    assert result['ssh_process_alive'] is True
    assert result['local_db_query_verified'] is True
    assert result['local_api_reachable'] is True
    assert result['remote_db'] == '127.0.0.1:15433'
    assert result['remote_api'] == '127.0.0.1:18000'
    assert result['connector_artifact'] == 'AlphaPOS-Support-Connector.ps1'
    assert result['operator_db'] == '127.0.0.1:25433'
    assert result['operator_api'] == 'http://127.0.0.1:28000'
    assert 'full database' in result['operator_access_warning']
    assert result['db_label'] == 'DB Ready'
    assert result['backend_label'] == 'Backend Ready'
    assert result['pinned_host_fingerprint'].startswith('SHA256:')

    monkeypatch.setattr(support_tunnel, '_LOCAL_DB_QUERY_VERIFIED', False)
    degraded = support_tunnel.status()
    assert degraded['state'] == 'partial_ready'
    assert degraded['ready'] is False
    assert degraded['db_status'] == 'unavailable'
    assert degraded['backend_status'] == 'ready'

    monkeypatch.setattr(
        support_tunnel, '_LAST_PROBE_MONOTONIC',
        time.monotonic() - support_tunnel._PROBE_MAX_AGE_SECONDS - 1,
    )
    stale = support_tunnel.status()
    assert stale['state'] == 'degraded'
    assert stale['probe_fresh'] is False
    assert stale['db_status'] == 'checking'
    assert stale['backend_status'] == 'checking'


def test_status_reports_configuration_error_without_crashing(monkeypatch):
    settings = _settings()
    settings['known_host'] = 'wrong-host ssh-ed25519 ' + _ed25519_public_blob()
    monkeypatch.setattr(support_tunnel, '_settings', lambda: settings)
    monkeypatch.setattr(support_tunnel, '_PROCESS', None)
    monkeypatch.setattr(support_tunnel, '_LAST_ERROR', '')

    result = support_tunnel.status()

    assert result['state'] == 'configuration_required'
    assert result['configured'] is False
    assert 'does not match' in result['configuration_error']
    assert result['relay_host'] == ''
    assert result['pinned_host_fingerprint'] == ''


def test_probe_uses_minimal_authenticated_query_and_exact_backend_health(
    monkeypatch,
):
    from config.urls import healthz

    executed = []
    connect_kwargs = {}

    class Context:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self.value

        def __exit__(self, *_args):
            return False

    class Cursor:
        def execute(self, query):
            executed.append(query)

        @staticmethod
        def fetchone():
            return (1,)

    class Connection:
        @staticmethod
        def cursor():
            return Context(Cursor())

    def connect(**kwargs):
        connect_kwargs.update(kwargs)
        return Context(Connection())

    class Response:
        status = 200

        @staticmethod
        def read(_size):
            return healthz(None).content

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        support_tunnel.socket, 'create_connection',
        lambda *_args, **_kwargs: Context(object()),
    )
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(connect=connect))
    monkeypatch.setattr(
        support_tunnel.urllib.request, 'urlopen',
        lambda *_args, **_kwargs: Response(),
    )

    support_tunnel._probe_local_targets(_settings())

    assert executed == ['SELECT 1']
    assert connect_kwargs['host'] == '127.0.0.1'
    assert connect_kwargs['port'] == 5433
    assert connect_kwargs['application_name'] == 'alphapos_support_readiness'
    assert support_tunnel._LOCAL_DB_QUERY_VERIFIED is True
    assert support_tunnel._LOCAL_API_REACHABLE is True


def test_probe_accepts_real_local_health_contract_and_rejects_lookalikes(
    monkeypatch,
):
    from config.urls import healthz
    from desktop.version import __version__

    monkeypatch.setenv('APP_GIT_SHA', 'abc1234-release.1')
    actual = healthz(None).content
    assert actual == b'ok abc1234-release.1'
    assert support_tunnel._valid_backend_health_body(actual) is True
    assert support_tunnel._valid_backend_health_body(b'ok') is True

    monkeypatch.delenv('APP_GIT_SHA')
    versioned = healthz(None).content
    assert versioned == f'ok desktop-{__version__}'.encode()
    assert support_tunnel._valid_backend_health_body(versioned) is True

    for malformed in (
        b'not-ok',
        b'okay',
        b'prefix ok abc1234',
        b'ok abc/1234',
        b'ok abc1234\n',
        b'ok ' + (b'a' * 65),
    ):
        assert support_tunnel._valid_backend_health_body(malformed) is False


def test_probe_and_status_redact_passwords(monkeypatch):
    secret = 'restaurant-db-password-123'
    monkeypatch.setenv('DB_PASSWORD', secret)
    redacted = support_tunnel._redact_text(
        f'connection failed password={secret}; token=abc123',
        _settings(),
    )
    assert secret not in redacted
    assert 'abc123' not in redacted
    assert redacted.count('[REDACTED]') == 2


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
