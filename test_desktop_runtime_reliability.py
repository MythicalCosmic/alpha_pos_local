import hashlib
import http.client
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from django.test import override_settings

from desktop import config_store, control_server, pg_embedded
from desktop.server_manager import ServerManager


def _config_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    mapping = {
        'ENV_FILE': '.env',
        'SECRET_FILE': '.secret_key',
        'FERNET_FILE': '.license_fernet_key',
        'DEVICE_FILE': '.device_id',
        'STATE_FILE': 'desktop_state.json',
        'CREDS_FILE': 'admin_credentials.json',
        'RESET_FLAG': '.reset_pending',
        'LEGACY_MIGRATION_MARKER': '.legacy_env_migrated',
        'LEGACY_PG_MIGRATION_MARKER': '.legacy_pgdata_migrated',
    }
    for attr, filename in mapping.items():
        monkeypatch.setattr(config_store, attr, tmp_path / filename)
    monkeypatch.setattr(config_store, '_INSTALL_VALUE_FILES', {
        'SECRET_KEY': tmp_path / '.secret_key',
        'LICENSE_FERNET_KEY': tmp_path / '.license_fernet_key',
        'DEVICE_ID': tmp_path / '.device_id',
    })


def test_frozen_data_dir_is_stable_without_localappdata(monkeypatch):
    monkeypatch.setattr(config_store.sys, 'frozen', True, raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setenv('USERPROFILE', r'C:\Users\Till')
    assert config_store._data_dir() == Path(
        r'C:\Users\Till/AppData/Local/AlphaPOS'
    )


def test_postgres_uses_the_same_canonical_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    assert pg_embedded._data_dir() == tmp_path / 'pgdata'


def test_sole_legacy_postgres_cluster_is_moved_atomically(monkeypatch, tmp_path):
    data_root = tmp_path / 'canonical'
    _config_paths(monkeypatch, data_root)
    canonical = data_root / 'pgdata'
    canonical.mkdir(parents=True)  # failed/aborted initdb can leave this behind
    legacy = tmp_path / 'legacy' / 'pgdata'
    legacy.mkdir(parents=True)
    (legacy / 'PG_VERSION').write_text('15\n', encoding='utf-8')
    (legacy / 'order-evidence').write_text('preserved\n', encoding='utf-8')
    monkeypatch.setattr(
        pg_embedded, '_legacy_data_candidates', lambda _canonical: (legacy,),
    )

    assert pg_embedded._migrate_legacy_cluster(canonical) == legacy
    assert not legacy.exists()
    assert (canonical / 'PG_VERSION').read_text(encoding='utf-8') == '15\n'
    assert (canonical / 'order-evidence').read_text(encoding='utf-8') == 'preserved\n'
    assert config_store.LEGACY_PG_MIGRATION_MARKER.read_text().strip() == 'migrated'


def test_split_postgres_clusters_never_merge_and_warning_persists(
        monkeypatch, tmp_path):
    data_root = tmp_path / 'canonical'
    _config_paths(monkeypatch, data_root)
    canonical = data_root / 'pgdata'
    legacy = tmp_path / 'legacy' / 'pgdata'
    canonical.mkdir(parents=True)
    legacy.mkdir(parents=True)
    (canonical / 'PG_VERSION').write_text('15\n', encoding='utf-8')
    (legacy / 'PG_VERSION').write_text('15\n', encoding='utf-8')
    (canonical / 'canonical-order').write_text('keep\n', encoding='utf-8')
    (legacy / 'legacy-order').write_text('keep\n', encoding='utf-8')
    monkeypatch.setattr(
        pg_embedded, '_legacy_data_candidates', lambda _canonical: (legacy,),
    )

    assert pg_embedded._migrate_legacy_cluster(canonical) is None
    assert (canonical / 'canonical-order').exists()
    assert (legacy / 'legacy-order').exists()
    assert config_store.LEGACY_PG_MIGRATION_MARKER.read_text().strip() == 'split-detected'
    assert 'Both canonical and legacy' in pg_embedded.migration_status()['warning']

    # The durable marker must not make the warning disappear on next launch.
    assert pg_embedded._migrate_legacy_cluster(canonical) is None
    assert 'Both canonical and legacy' in pg_embedded.migration_status()['warning']


def test_completed_postgres_migration_never_recreates_an_empty_database(
        monkeypatch, tmp_path):
    data_root = tmp_path / 'canonical'
    _config_paths(monkeypatch, data_root)
    canonical = data_root / 'pgdata'
    config_store.LEGACY_PG_MIGRATION_MARKER.parent.mkdir(parents=True)
    config_store.LEGACY_PG_MIGRATION_MARKER.write_text('migrated\n', encoding='utf-8')
    monkeypatch.setattr(pg_embedded, '_legacy_data_candidates', lambda _canonical: ())

    with pytest.raises(pg_embedded.EmbeddedPostgresError, match='canonical cluster is missing'):
        pg_embedded._migrate_legacy_cluster(canonical)


def test_frozen_build_never_falls_back_when_postgres_binaries_are_missing(
        monkeypatch):
    monkeypatch.setattr(pg_embedded.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(pg_embedded, '_binaries_dir', lambda: None)
    monkeypatch.delenv('DB_HOST', raising=False)
    with pytest.raises(pg_embedded.EmbeddedPostgresError, match='binaries are missing'):
        pg_embedded.start()
    assert 'binaries are missing' in pg_embedded.migration_status()['error']


def test_explicit_localhost_postgres_is_not_replaced_by_embedded(monkeypatch):
    monkeypatch.setattr(pg_embedded, '_configured_embedded', False)
    monkeypatch.setenv('DB_ENGINE', 'django.db.backends.postgresql')
    monkeypatch.setenv('DB_NAME', 'operator_db')
    monkeypatch.setenv('DB_USER', 'operator')
    monkeypatch.setenv('DB_HOST', '127.0.0.1')
    monkeypatch.setenv('DB_PORT', '5432')
    monkeypatch.setattr(
        pg_embedded, '_binaries_dir',
        lambda: (_ for _ in ()).throw(AssertionError('embedded lookup must not run')),
    )
    assert pg_embedded.start() is False


def test_partial_external_database_config_fails_closed(monkeypatch):
    monkeypatch.setattr(pg_embedded, '_configured_embedded', False)
    for key in ('DB_ENGINE', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_PORT'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('DB_HOST', 'localhost')
    with pytest.raises(pg_embedded.EmbeddedPostgresError, match='incomplete/unsafe'):
        pg_embedded.start()


def test_tcp_listener_cannot_spoof_embedded_postgres_readiness(monkeypatch, tmp_path):
    data_root = tmp_path / 'canonical'
    _config_paths(monkeypatch, data_root)
    data = data_root / 'pgdata'
    data.mkdir(parents=True)
    (data / 'PG_VERSION').write_text('15\n', encoding='utf-8')
    statuses = iter([
        subprocess.CompletedProcess([], 3, '', 'not running'),
        subprocess.CompletedProcess([], 3, '', 'not running'),
    ])
    monkeypatch.setattr(pg_embedded, '_configured_embedded', False)
    monkeypatch.setattr(pg_embedded, '_started', False)
    monkeypatch.delenv('DB_HOST', raising=False)
    monkeypatch.delenv('DB_PORT', raising=False)
    monkeypatch.setattr(pg_embedded, '_binaries_dir', lambda: tmp_path)
    monkeypatch.setattr(pg_embedded, '_data_dir', lambda: data)
    monkeypatch.setattr(pg_embedded, '_legacy_data_candidates', lambda _canonical: ())
    monkeypatch.setattr(pg_embedded, '_run', lambda *_args, **_kwargs: next(statuses))
    monkeypatch.setattr(
        pg_embedded.subprocess, 'run',
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, '', ''),
    )
    monkeypatch.setattr(pg_embedded, '_wait_ready', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        pg_embedded, '_role_exists',
        lambda *_args: (_ for _ in ()).throw(AssertionError('must not modify listener')),
    )

    with pytest.raises(pg_embedded.EmbeddedPostgresError, match='port collision'):
        pg_embedded.start()


def test_postgres_stop_failure_is_reported_before_destructive_operations(
        monkeypatch, tmp_path):
    data = tmp_path / 'pgdata'
    data.mkdir()
    (data / 'PG_VERSION').write_text('15\n', encoding='utf-8')
    results = iter([
        subprocess.CompletedProcess([], 0, '', ''),
        subprocess.CompletedProcess([], 1, '', 'access denied'),
    ])
    monkeypatch.setattr(pg_embedded, '_binaries_dir', lambda: tmp_path)
    monkeypatch.setattr(pg_embedded, '_data_dir', lambda: data)
    monkeypatch.setattr(pg_embedded, '_run', lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(pg_embedded, '_started', True)

    assert pg_embedded.stop() is False
    assert pg_embedded._started is True


def test_stranded_sqlite_orders_are_reported_read_only_for_recovery(
        monkeypatch, tmp_path):
    import sqlite3

    _config_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(pg_embedded.sys, 'frozen', True, raising=False)
    legacy = tmp_path / 'db.sqlite3'
    connection = sqlite3.connect(legacy)
    connection.execute('CREATE TABLE base_order (id INTEGER PRIMARY KEY, synced_at TEXT)')
    connection.execute('CREATE TABLE sync_queue_record (id INTEGER PRIMARY KEY)')
    connection.executemany('INSERT INTO base_order DEFAULT VALUES', [(), ()])
    connection.execute('INSERT INTO sync_queue_record DEFAULT VALUES')
    connection.commit()
    connection.close()

    evidence = pg_embedded.detect_stranded_sqlite()
    assert evidence == {
        'path': str(legacy), 'orders': 2, 'sync_queue': 1, 'unsynced_orders': 2,
    }
    warning = pg_embedded.migration_status()['warning']
    assert 'do not delete' in warning.lower()
    assert 'orders=2' in warning
    assert legacy.exists()


def test_env_parser_handles_windows_editor_and_dotenv_syntax(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    config_store.ENV_FILE.write_text(
        '\ufeffexport BRANCH_ID="branch 7"\n'
        'CLOUD_SYNC_TOKEN=abc#123\n'
        'PORT=8123  # panel port\n',
        encoding='utf-8',
    )
    assert config_store.parse_env_file() == {
        'BRANCH_ID': 'branch 7',
        'CLOUD_SYNC_TOKEN': 'abc#123',
        'PORT': '8123',
    }


def test_damaged_env_fails_loud_instead_of_using_partial_defaults(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    config_store.ENV_FILE.write_text(
        'BRANCH_ID=correct\nthis line was truncated', encoding='utf-8',
    )
    with pytest.raises(config_store.ConfigError, match='line 2'):
        config_store.apply_env_to_process()
    assert 'expected KEY=value' in config_store.env_status()['error']


def test_apply_env_migrates_install_identity_and_honors_file(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    _config_paths(monkeypatch, tmp_path)
    fernet = Fernet.generate_key().decode('ascii')
    config_store.ENV_FILE.write_text(
        f'BRANCH_ID=branch-file\nPORT=8124\nSECRET_KEY=legacy-secret\n'
        f'LICENSE_FERNET_KEY={fernet}\nDEVICE_ID=legacy-device\n',
        encoding='utf-8',
    )
    fake_env = {'PORT': '9999', 'ALPHA_POS_DATA_DIR': 'wrong'}
    monkeypatch.setattr(config_store.os, 'environ', fake_env)
    config_store.apply_env_to_process()

    assert fake_env['BRANCH_ID'] == 'branch-file'
    assert fake_env['PORT'] == '8124'
    assert fake_env['ALPHA_POS_DATA_DIR'] == str(tmp_path)
    assert fake_env['SECRET_KEY'] == 'legacy-secret'
    assert fake_env['LICENSE_FERNET_KEY'] == fernet
    assert fake_env['DEVICE_ID'] == 'legacy-device'
    assert config_store.SECRET_FILE.read_text().strip() == 'legacy-secret'
    assert config_store.FERNET_FILE.read_text().strip() == fernet


def test_genuinely_fresh_install_has_no_baked_tenant_identity(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config_store, '_legacy_env_candidates', lambda: ())
    fake_env = {}
    monkeypatch.setattr(config_store.os, 'environ', fake_env)
    config_store.apply_env_to_process()
    assert fake_env['SYNC_ENABLED'] == 'False'
    assert fake_env.get('BRANCH_ID', '') == ''
    assert fake_env.get('CLOUD_SYNC_TOKEN', '') == ''


def test_frozen_config_clears_hostile_or_stale_managed_environment(
        monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config_store.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(config_store, '_legacy_env_candidates', lambda: ())
    config_store.ENV_FILE.write_text(
        'BRANCH_ID=canonical-branch\n', encoding='utf-8',
    )
    fake_env = {
        'BRANCH_ID': 'hostile-parent-branch',
        'CLOUD_SYNC_TOKEN': 'hostile-parent-token',
        'SYNC_ENABLED': 'True',
        'PORT': 'not-an-integer',
        'DB_ENGINE': 'django.db.backends.postgresql',
        'DB_HOST': 'wrong-restaurant-db.example',
    }
    monkeypatch.setattr(config_store.os, 'environ', fake_env)

    config_store.apply_env_to_process()
    assert fake_env['BRANCH_ID'] == 'canonical-branch'
    assert fake_env['CLOUD_SYNC_TOKEN'] == ''
    assert fake_env['SYNC_ENABLED'] == 'False'
    assert fake_env['PORT'] == '8000'
    assert 'DB_ENGINE' not in fake_env
    assert 'DB_HOST' not in fake_env

    # Removing a previously applied key must clear it on a second apply too.
    config_store.ENV_FILE.write_text('SYNC_ENABLED=False\n', encoding='utf-8')
    config_store.apply_env_to_process()
    assert fake_env['BRANCH_ID'] == ''
    assert fake_env['CLOUD_SYNC_TOKEN'] == ''


def test_valid_legacy_env_is_migrated_once_without_overwrite(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path / 'canonical')
    legacy = tmp_path / 'legacy' / '.env'
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        'BRANCH_ID=restaurant-9\nSYNC_ENABLED=True\n'
        'CLOUD_SYNC_TOKEN=persisted-token\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(config_store, '_legacy_env_candidates', lambda: (legacy,))
    fake_env = {}
    monkeypatch.setattr(config_store.os, 'environ', fake_env)
    migrated = config_store.migrate_legacy_env_if_needed()

    assert migrated == legacy
    assert not legacy.exists()
    assert config_store.LEGACY_MIGRATION_MARKER.exists()
    assert config_store.parse_env_file()['BRANCH_ID'] == 'restaurant-9'
    assert config_store.parse_env_file()['CLOUD_SYNC_TOKEN'] == 'persisted-token'

    # Once canonical exists, a reappearing stale legacy copy can never replace it.
    legacy.write_text(
        'BRANCH_ID=wrong\nSYNC_ENABLED=True\nCLOUD_SYNC_TOKEN=wrong-token\n',
        encoding='utf-8',
    )
    assert config_store.migrate_legacy_env_if_needed() is None
    assert config_store.parse_env_file()['BRANCH_ID'] == 'restaurant-9'


def test_factory_reset_never_resurrects_legacy_tenant_config(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path / 'canonical')
    legacy = tmp_path / 'legacy.env'
    legacy.write_text(
        'BRANCH_ID=old-tenant\nSYNC_ENABLED=True\nCLOUD_SYNC_TOKEN=old-token\n',
        encoding='utf-8',
    )
    config_store.ENV_FILE.parent.mkdir(parents=True)
    config_store.ENV_FILE.write_text(
        'BRANCH_ID=current\nSYNC_ENABLED=True\nCLOUD_SYNC_TOKEN=current-token\n',
        encoding='utf-8',
    )
    config_store.RESET_FLAG.write_text('1', encoding='utf-8')
    config_store.LEGACY_PG_MIGRATION_MARKER.write_text(
        'split-detected\n', encoding='utf-8',
    )
    monkeypatch.setattr(config_store, '_legacy_env_candidates', lambda: (legacy,))
    fake_env = {}
    monkeypatch.setattr(config_store.os, 'environ', fake_env)

    config_store.apply_env_to_process()
    assert fake_env.get('BRANCH_ID', '') == ''
    assert fake_env['SYNC_ENABLED'] == 'False'
    assert legacy.exists()
    assert config_store.LEGACY_MIGRATION_MARKER.read_text().strip() == 'factory-reset'
    assert config_store.LEGACY_PG_MIGRATION_MARKER.read_text().strip() == 'factory-reset'


def test_locked_factory_reset_stays_armed_and_backend_refuses_to_boot(
        monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    config_store.ENV_FILE.write_text('BRANCH_ID=old\nSYNC_ENABLED=False\n', encoding='utf-8')
    config_store.RESET_FLAG.write_text('1', encoding='utf-8')
    monkeypatch.setattr(config_store, '_wipe_data', lambda: [])
    with pytest.raises(config_store.ConfigError, match='locked data'):
        config_store.apply_env_to_process()
    assert config_store.RESET_FLAG.exists()
    assert config_store.ENV_FILE.exists()


def test_factory_reset_removes_raw_order_audit_and_exports(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    audit_dir = tmp_path / 'order_audit'
    local_telegram_dir = tmp_path / 'local_telegram_audit'
    exports = audit_dir / 'exports'
    exports.mkdir(parents=True)
    local_telegram_dir.mkdir(parents=True)
    (audit_dir / 'orders.raw.jsonl').write_text('raw order\n', encoding='utf-8')
    (audit_dir / '.orders.raw.index.json').write_text('{}\n', encoding='utf-8')
    (exports / 'raw-export.jsonl').write_text('export\n', encoding='utf-8')
    (local_telegram_dir / 'outbox.sqlite3').write_bytes(b'private outbox')
    monkeypatch.setattr(pg_embedded, 'stop', lambda: None)

    removed = config_store._wipe_data()

    assert str(audit_dir) in removed
    assert str(local_telegram_dir) in removed
    assert not audit_dir.exists()
    assert not local_telegram_dir.exists()


def test_pending_reset_refuses_completion_if_order_audit_survives(
        monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    audit_dir = tmp_path / 'order_audit'
    audit_dir.mkdir(parents=True)
    (audit_dir / 'orders.raw.jsonl').write_text('private\n', encoding='utf-8')
    config_store.RESET_FLAG.write_text('1\n', encoding='utf-8')
    monkeypatch.setattr(config_store, '_wipe_data', lambda: [])

    with pytest.raises(config_store.ConfigError, match='order_audit'):
        config_store.consume_reset_pending()
    assert config_store.RESET_FLAG.exists()
    assert audit_dir.exists()


def test_invalid_existing_fernet_key_is_never_silently_rotated(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    config_store.FERNET_FILE.write_text('broken\n', encoding='utf-8')
    with pytest.raises(config_store.ConfigError, match='restore'):
        config_store.load_or_generate_fernet()
    assert config_store.FERNET_FILE.read_text(encoding='utf-8') == 'broken\n'


def test_config_write_is_atomic_and_round_trips_sensitive_values(monkeypatch, tmp_path):
    _config_paths(monkeypatch, tmp_path)
    config_store.write_config({
        'BRANCH_ID': 'branch one',
        'CLOUD_SYNC_TOKEN': 'token # with comment characters',
    })
    parsed = config_store.parse_env_file()
    assert parsed['BRANCH_ID'] == 'branch one'
    assert parsed['CLOUD_SYNC_TOKEN'] == 'token # with comment characters'
    assert not list(tmp_path.glob('.*.tmp'))


def test_packaged_windows_private_data_uses_owner_only_inheritable_acl(
        monkeypatch, tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    calls = []
    config_store._HARDENED_WINDOWS_PATHS.clear()
    monkeypatch.setattr(config_store.os, 'name', 'nt')
    monkeypatch.setattr(config_store.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(
        config_store, '_current_windows_sid', lambda: 'S-1-5-21-1234',
    )
    monkeypatch.setattr(
        config_store, '_windows_executable', lambda name: name,
    )
    monkeypatch.setattr(
        config_store, '_hidden_windows_command',
        lambda command: calls.append(command) or subprocess.CompletedProcess(
            command, 0, 'processed', '',
        ),
    )

    config_store._harden_windows_private_path(
        private, directory=True, recursive=True,
    )

    assert calls == [[
        'icacls.exe', str(private), '/inheritance:r', '/grant:r',
        '*S-1-5-21-1234:(OI)(CI)F', '/T', '/C',
    ]]


class _WaitSequence:
    def __init__(self, iterations):
        self.iterations = iterations
        self.delays = []

    def wait(self, delay):
        self.delays.append(delay)
        self.iterations -= 1
        return self.iterations < 0


@override_settings(
    LICENSE_HEARTBEAT_INTERVAL=30,
    LICENSE_BACKOFF_SCHEDULE_S=(40, 80),
)
def test_heartbeat_records_failure_backoff_and_recovery(monkeypatch):
    from licensing.services import heartbeat

    results = iter([
        ({'message': 'offline'}, 502),
        ({'success': True}, 200),
    ])
    monkeypatch.setattr(heartbeat, 'do_heartbeat', lambda: next(results))
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)
    manager = ServerManager()
    stop = _WaitSequence(iterations=2)
    manager._heartbeat_loop(stop)

    assert stop.delays == [5, 40, 30]
    state = manager._worker_state['heartbeat']
    assert state['last_status'] == 200
    assert state['consecutive_failures'] == 0
    assert state['last_success_at']


@override_settings(
    LICENSE_HEARTBEAT_INTERVAL=300,
    LICENSE_BACKOFF_SCHEDULE_S=(60, 120),
)
def test_heartbeat_failure_retry_is_not_suppressed_by_normal_interval(monkeypatch):
    from licensing.services import heartbeat

    results = iter([
        ({'message': 'offline'}, 503),
        ({'success': True}, 200),
    ])
    monkeypatch.setattr(heartbeat, 'do_heartbeat', lambda: next(results))
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)
    manager = ServerManager()
    stop = _WaitSequence(iterations=2)
    manager._heartbeat_loop(stop)

    assert stop.delays == [5, 60, 300]


def test_lan_ip_first_call_always_probes_even_just_after_boot(monkeypatch):
    import socket
    from desktop import server_manager

    calls = []

    class FakeSocket:
        def settimeout(self, _timeout):
            pass

        def connect(self, address):
            calls.append(address)

        def getsockname(self):
            return ('192.168.1.77', 12345)

        def close(self):
            pass

    monkeypatch.setattr(server_manager.time, 'monotonic', lambda: 10.0)
    monkeypatch.setattr(socket, 'socket', lambda *_args: FakeSocket())
    manager = ServerManager()
    assert manager.lan_ip() == '192.168.1.77'
    assert calls == [('8.8.8.8', 80)]


def test_lan_ip_uses_private_adapter_when_restaurant_lan_is_offline(monkeypatch):
    import socket

    class OfflineSocket:
        def settimeout(self, _timeout):
            pass

        def connect(self, _address):
            raise OSError('no internet route')

        def close(self):
            pass

    monkeypatch.setattr(socket, 'socket', lambda *_args: OfflineSocket())
    monkeypatch.setattr(socket, 'gethostname', lambda: 'till-1')
    monkeypatch.setattr(
        socket, 'gethostbyname_ex',
        lambda _name: ('till-1', [], ['127.0.0.1', '192.168.50.12']),
    )
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *_args: [])
    manager = ServerManager()
    assert manager.lan_ip() == '192.168.50.12'


def test_sync_uses_bounded_retry_then_returns_to_normal_interval(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService

    pushes = iter([
        {'success': False, 'message': 'cloud offline'},
        {'success': True},
    ])
    monkeypatch.setattr(sync_config.SyncConfig, 'is_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'is_local_mode', lambda: True)
    monkeypatch.setattr(sync_config, 'get_cloud_url', lambda: 'https://cloud')
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: False)
    monkeypatch.setattr(sync_config, 'get_sync_interval', lambda: 10)
    monkeypatch.setattr(sync_config, 'get_sync_retry_interval', lambda: 60)
    monkeypatch.setattr(SyncService, 'push', lambda: next(pushes))
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)
    manager = ServerManager()
    manager._ensure_heartbeat_worker = lambda: None
    stop = _WaitSequence(iterations=2)
    manager._sync_loop(stop)

    assert stop.delays == [2, 60, 10]
    state = manager._worker_state['sync']
    assert state['last_status'] == 'ok'
    assert state['consecutive_failures'] == 0


def test_pull_recovery_backoff_never_exceeds_presence_lease(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService

    pulls = iter([
        {'success': False, 'message': 'hub restarting'},
        {'success': False, 'message': 'hub still starting'},
        {'success': True},
    ])
    monkeypatch.setattr(sync_config.SyncConfig, 'is_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'is_local_mode', lambda: True)
    monkeypatch.setattr(sync_config, 'get_cloud_url', lambda: 'https://cloud')
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'get_sync_interval', lambda: 30)
    monkeypatch.setattr(sync_config, 'get_sync_retry_interval', lambda: 60)
    monkeypatch.setattr(SyncService, 'pull_from_cloud', lambda: next(pulls))
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)

    manager = ServerManager()
    stop = _WaitSequence(iterations=3)
    manager._pull_loop(stop)

    # Presence has a 95-second lease. Repeated scheduler failures must not grow
    # the post-recovery probe gap to the former 120/240/.../900 seconds.
    assert stop.delays == [2, 60, 60, 30]
    state = manager._worker_state['pull']
    assert state['last_status'] == 'ok'
    assert state['consecutive_failures'] == 0


def test_pull_lock_contention_keeps_normal_presence_cadence(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService

    pulls = iter([
        {'success': False, 'message': 'Pull already in progress'},
        {'success': True},
    ])
    monkeypatch.setattr(sync_config.SyncConfig, 'is_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'is_local_mode', lambda: True)
    monkeypatch.setattr(sync_config, 'get_cloud_url', lambda: 'https://cloud')
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'get_sync_interval', lambda: 30)
    monkeypatch.setattr(sync_config, 'get_sync_retry_interval', lambda: 60)
    monkeypatch.setattr(SyncService, 'pull_from_cloud', lambda: next(pulls))
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)

    manager = ServerManager()
    stop = _WaitSequence(iterations=2)
    manager._pull_loop(stop)

    assert stop.delays == [2, 30, 30]
    assert manager._worker_state['pull']['consecutive_failures'] == 0


def test_pull_normal_interval_stays_inside_presence_lease(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService

    monkeypatch.setattr(sync_config.SyncConfig, 'is_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'is_local_mode', lambda: True)
    monkeypatch.setattr(sync_config, 'get_cloud_url', lambda: 'https://cloud')
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'get_sync_interval', lambda: 300)
    monkeypatch.setattr(sync_config, 'get_sync_retry_interval', lambda: 60)
    monkeypatch.setattr(SyncService, 'pull_from_cloud', lambda: {'success': True})
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)

    manager = ServerManager()
    stop = _WaitSequence(iterations=1)
    manager._pull_loop(stop)

    assert stop.delays == [2, 60]
    assert manager._worker_state['pull']['last_status'] == 'ok'


def test_slow_push_cannot_starve_pull_or_presence(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService

    push_started = threading.Event()
    release_push = threading.Event()
    pull_finished = threading.Event()

    def slow_push():
        push_started.set()
        assert release_push.wait(2)
        return {'success': True}

    def quick_pull():
        pull_finished.set()
        return {'success': True}

    monkeypatch.setattr(sync_config.SyncConfig, 'is_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'is_local_mode', lambda: True)
    monkeypatch.setattr(sync_config, 'get_cloud_url', lambda: 'https://cloud')
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: True)
    monkeypatch.setattr(sync_config, 'get_sync_interval', lambda: 30)
    monkeypatch.setattr(sync_config, 'get_sync_retry_interval', lambda: 60)
    monkeypatch.setattr(SyncService, 'push', slow_push)
    monkeypatch.setattr(SyncService, 'pull_from_cloud', quick_pull)
    monkeypatch.setattr('django.db.close_old_connections', lambda: None)

    manager = ServerManager()
    manager._ensure_heartbeat_worker = lambda: None
    push_thread = threading.Thread(
        target=manager._sync_loop, args=(_WaitSequence(iterations=1),),
    )
    pull_thread = threading.Thread(
        target=manager._pull_loop, args=(_WaitSequence(iterations=1),),
    )
    push_thread.start()
    assert push_started.wait(1)
    pull_thread.start()
    try:
        assert pull_finished.wait(1), 'pull was starved behind the outbound backlog'
    finally:
        release_push.set()
        push_thread.join(2)
        pull_thread.join(2)

    assert not push_thread.is_alive()
    assert not pull_thread.is_alive()


def test_background_worker_watchdog_and_shutdown_include_pull(monkeypatch):
    manager = ServerManager()
    started = []
    monkeypatch.setattr(manager, 'is_running', lambda: True)
    monkeypatch.setattr(manager, 'wants_running', lambda: True)
    monkeypatch.setattr(
        manager, '_ensure_heartbeat_worker', lambda: started.append('heartbeat'),
    )
    monkeypatch.setattr(
        manager, '_ensure_sync_worker', lambda: started.append('sync'),
    )
    monkeypatch.setattr(
        manager, '_ensure_pull_worker', lambda: started.append('pull'),
    )

    manager.ensure_background_workers()

    assert started == ['heartbeat', 'sync', 'pull']

    # The real worker loops are Event-driven; stop must wake the new pull loop
    # just like the pre-existing push/license workers.
    assert not manager._pull_stop_event.is_set()
    result = manager.stop(worker_timeout=0)
    assert manager._pull_stop_event.is_set()
    assert result['workers_quiescent'] is True
    assert manager._worker_state['pull']['last_status'] == 'stopped'


def test_automatic_start_respects_operator_stop():
    manager = ServerManager()
    manager._desired_running = False
    result = manager.start(automatic=True)
    assert result == {
        'running': False, 'message': 'Server intentionally stopped',
    }


def test_failed_required_setup_never_persists_setup_signature(monkeypatch):
    from base.models import User
    from django.core import management

    writes = []

    class FakeUsers:
        @staticmethod
        def exists():
            return False

    def fake_call(command, *args, **kwargs):
        if command == 'bootstrap_admin':
            raise RuntimeError('temporary bootstrap failure')
        return None

    monkeypatch.setattr(User, 'objects', FakeUsers())
    monkeypatch.setattr(management, 'call_command', fake_call)
    monkeypatch.setattr(config_store, 'read_state', lambda: {})
    monkeypatch.setattr(config_store, 'update_state', lambda value: writes.append(value))
    manager = ServerManager()
    manager.ensure_django = lambda: None

    with pytest.raises(RuntimeError, match='temporary bootstrap failure'):
        manager.first_time_install()
    assert writes == []


def test_matching_setup_signature_skips_only_when_live_schema_is_current(monkeypatch):
    from django.core import management
    from desktop import server_manager

    logs = []
    monkeypatch.setattr(
        server_manager, '_setup_signature_and_schema_current',
        lambda: ('1.2.3:abc', True),
    )
    monkeypatch.setattr(config_store, 'read_state', lambda: {'setup_sig': '1.2.3:abc'})
    monkeypatch.setattr(
        management, 'call_command',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('current schema must use the warm-start shortcut'),
        ),
    )
    manager = ServerManager()
    manager.ensure_django = lambda: None

    manager.first_time_install(log=logs.append)
    assert logs == ['Setup already current — skipping migrate/seed/collectstatic.']


def test_matching_setup_signature_repairs_empty_or_stale_database(monkeypatch):
    from base.models import User
    from django.core import management
    from desktop import server_manager

    calls = []
    state_writes = []

    class ExistingUsers:
        @staticmethod
        def exists():
            return True

    monkeypatch.setattr(User, 'objects', ExistingUsers())
    monkeypatch.setattr(
        server_manager, '_setup_signature_and_schema_current',
        lambda: ('1.2.3:abc', False),
    )
    monkeypatch.setattr(config_store, 'read_state', lambda: {'setup_sig': '1.2.3:abc'})
    monkeypatch.setattr(config_store, 'update_state', lambda values: state_writes.append(values))
    monkeypatch.setattr(
        management, 'call_command',
        lambda command, *_args, **_kwargs: calls.append(command),
    )
    manager = ServerManager()
    manager.ensure_django = lambda: None

    manager.first_time_install()
    assert calls == ['migrate', 'bootstrap_admin', 'seed_templates', 'collectstatic']
    assert state_writes == [{'setup_sig': '1.2.3:abc'}]


def test_first_time_install_supplies_streams_without_a_gui_console(monkeypatch):
    from base.models import User
    from django.core import management
    from desktop import server_manager

    calls = []
    logs = []

    class ExistingUsers:
        @staticmethod
        def exists():
            return True

    def fake_call(command, *_args, **options):
        stdout = options.get('stdout')
        stderr = options.get('stderr')
        assert stdout is not None
        assert stderr is not None
        stdout.write(f'{command} output\n')
        stderr.write(f'{command} warning\n')
        calls.append(command)

    monkeypatch.setattr(User, 'objects', ExistingUsers())
    monkeypatch.setattr(
        server_manager, '_setup_signature_and_schema_current',
        lambda: ('1.2.3:abc', False),
    )
    monkeypatch.setattr(config_store, 'read_state', lambda: {})
    monkeypatch.setattr(config_store, 'update_state', lambda _values: None)
    monkeypatch.setattr(management, 'call_command', fake_call)
    manager = ServerManager()
    manager.ensure_django = lambda: None

    # A PyInstaller ``--windowed`` executable has no process console.
    with monkeypatch.context() as gui:
        gui.setattr(sys, 'stdout', None)
        gui.setattr(sys, 'stderr', None)
        manager.first_time_install(log=logs.append)

    assert calls == ['migrate', 'bootstrap_admin', 'seed_templates', 'collectstatic']
    for command in calls:
        assert f'  [{command}] {command} output' in logs
        assert f'  [{command}] {command} warning' in logs


def test_management_command_logs_output_before_reraising(monkeypatch):
    from django.core import management

    logs = []

    def failing_call(_command, *_args, **options):
        options['stdout'].write('completed step one\n')
        options['stderr'].write('database unavailable\n')
        raise RuntimeError('setup failed')

    monkeypatch.setattr(management, 'call_command', failing_call)

    with pytest.raises(RuntimeError, match='setup failed'):
        ServerManager.run_management_command(
            'migrate', '--noinput', log=logs.append,
        )

    assert logs == [
        '  [migrate] completed step one',
        '  [migrate] database unavailable',
    ]


def test_django_bootstrap_verifies_postgres_before_settings_setup(monkeypatch):
    import django

    calls = []
    monkeypatch.setattr(
        config_store, 'apply_env_to_process', lambda: calls.append('env'),
    )
    monkeypatch.setattr(pg_embedded, 'start', lambda: calls.append('postgres'))
    monkeypatch.setattr(django, 'setup', lambda: calls.append('django'))
    manager = ServerManager()

    manager.ensure_django()
    assert calls == ['env', 'postgres', 'django']
    assert manager._django_ready is True


def test_django_never_configures_sqlite_when_postgres_verification_fails(monkeypatch):
    import django

    calls = []
    monkeypatch.setattr(config_store, 'apply_env_to_process', lambda: calls.append('env'))
    monkeypatch.setattr(
        pg_embedded, 'start',
        lambda: (_ for _ in ()).throw(
            pg_embedded.EmbeddedPostgresError('database unavailable'),
        ),
    )
    monkeypatch.setattr(django, 'setup', lambda: calls.append('django'))
    manager = ServerManager()

    with pytest.raises(pg_embedded.EmbeddedPostgresError):
        manager.ensure_django()
    assert calls == ['env']
    assert manager._django_ready is False


def test_postgres_bootstrap_failure_retries_without_starting_unsafe_backend(monkeypatch):
    from desktop import app

    class StopAfterRetry:
        def __init__(self):
            self.stopped = False
            self.delays = []

        def is_set(self):
            return self.stopped

        def wait(self, delay):
            self.delays.append(delay)
            self.stopped = True
            return True

    monkeypatch.setattr(
        control_server._API.server, 'ensure_django',
        lambda: (_ for _ in ()).throw(
            pg_embedded.EmbeddedPostgresError('unsafe database state'),
        ),
    )
    spawned = []
    monkeypatch.setattr(
        app.threading, 'Thread',
        lambda *args, **kwargs: spawned.append((args, kwargs)),
    )
    shutdown = StopAfterRetry()

    app._boot_worker(shutdown_event=shutdown)
    assert spawned == []
    assert shutdown.delays == [3]


def test_transient_bootstrap_failure_recovers_without_app_restart(monkeypatch):
    from desktop import app, support_tunnel

    attempts = []

    def ensure_django():
        attempts.append('django')
        if len(attempts) == 1:
            raise pg_embedded.EmbeddedPostgresError('temporary sharing violation')

    class RetryEvent:
        def __init__(self):
            self.delays = []

        @staticmethod
        def is_set():
            return False

        def wait(self, delay):
            self.delays.append(delay)
            return False

    class StartedThread:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get('name')

        def start(self):
            spawned.append(self.name)

    spawned = []
    shutdown = RetryEvent()
    monkeypatch.setattr(control_server._API.server, 'ensure_django', ensure_django)
    monkeypatch.setattr(app.threading, 'Thread', StartedThread)
    monkeypatch.setattr(app.atexit, 'register', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(support_tunnel, 'start', lambda: True)
    monkeypatch.setattr(app.sys, 'argv', ['AlphaPOS.exe', '--no-update'])

    app._boot_worker(shutdown_event=shutdown)

    assert attempts == ['django', 'django']
    assert shutdown.delays == [3]
    assert spawned == ['autostart']


def test_second_instance_never_opens_unverified_loopback_service(monkeypatch):
    from desktop import app, single_instance

    monkeypatch.setattr(app, '_configure_boot_logging', lambda: None)
    monkeypatch.setattr(single_instance, 'acquire', lambda: False)
    monkeypatch.setattr(control_server, '_our_panel_at', lambda *_args: False)
    monkeypatch.setattr(
        app, '_run_pywebview',
        lambda _url: (_ for _ in ()).throw(
            AssertionError('unverified loopback URL must not be opened'),
        ),
    )
    monkeypatch.setattr(
        app, '_run_edge',
        lambda _url: (_ for _ in ()).throw(
            AssertionError('unverified loopback URL must not be opened'),
        ),
    )
    monkeypatch.setattr(
        app.webbrowser, 'open',
        lambda _url: (_ for _ in ()).throw(
            AssertionError('unverified loopback URL must not be opened'),
        ),
    )

    assert app.main() is None


def test_update_shutdown_closes_edge_fallback(monkeypatch):
    from desktop import app

    calls = []

    class FakeProcess:
        @staticmethod
        def poll():
            return None

        @staticmethod
        def terminate():
            calls.append('terminate')

        @staticmethod
        def wait(timeout=None):
            calls.append(('wait', timeout))
            return 0

    monkeypatch.setattr(app, '_EDGE_PROC', FakeProcess())
    app._close_edge_fallback()
    assert app._EDGE_PROC is None
    assert calls == ['terminate', ('wait', 3)]


def test_failed_setup_never_binds_or_confirms_update(monkeypatch):
    from desktop import app

    class StopAfterFirstWait:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _delay):
            self.stopped = True
            return True

    class FakeServer:
        start_calls = 0

        def wants_running(self):
            return True

        def is_running(self):
            return False

        def start(self, **_kwargs):
            self.start_calls += 1
            return {'running': True}

    class FakeApi:
        server = FakeServer()

        @staticmethod
        def run_setup():
            # Api.run_setup is @_safe and reports failures as a result object.
            return {'ok': False, 'error': 'migration failed'}

    ready = threading.Event()
    monkeypatch.setattr(app, '_BACKEND_READY', ready)
    monkeypatch.setattr(app, '_UPDATE_SHUTDOWN', StopAfterFirstWait())
    monkeypatch.setattr(control_server, '_API', FakeApi())

    app._autostart_backend()
    assert FakeApi.server.start_calls == 0
    assert not ready.is_set()


def test_autostart_watchdog_restarts_local_telegram_worker(monkeypatch):
    from desktop import app, local_telegram_audit, order_audit

    class StopAfterTwoLoops:
        waits = 0

        def is_set(self):
            return self.waits >= 2

        def wait(self, _delay):
            self.waits += 1
            return self.is_set()

    class FakeServer:
        @staticmethod
        def wants_running():
            return True

        @staticmethod
        def is_running():
            return True

        @staticmethod
        def ensure_background_workers():
            return None

    class FakeApi:
        server = FakeServer()

        @staticmethod
        def run_setup():
            return {'ok': True}

    order_starts = []
    telegram_starts = []
    monkeypatch.setattr(app, '_UPDATE_SHUTDOWN', StopAfterTwoLoops())
    monkeypatch.setattr(control_server, '_API', FakeApi())
    monkeypatch.setattr(
        order_audit,
        'start_background_collector',
        lambda: order_starts.append(True),
    )
    monkeypatch.setattr(
        local_telegram_audit,
        'start_background_notifier',
        lambda: telegram_starts.append(True),
    )

    app._autostart_backend()

    assert order_starts == [True]
    assert telegram_starts == [True, True]


def test_selftest_returns_failure_for_structured_setup_error(monkeypatch):
    from desktop import app, bridge

    stopped = []

    class FakeApi:
        @staticmethod
        def get_state():
            return {'ok': True}

        @staticmethod
        def run_setup():
            return {'ok': False, 'error': 'migration failed'}

        @staticmethod
        def start_server():
            raise AssertionError('server must not start after failed migration')

        @staticmethod
        def stop_server():
            stopped.append(True)
            return {'ok': True}

    monkeypatch.setattr(bridge, 'Api', FakeApi)
    assert app._selftest() == 1
    assert stopped == [True]


@override_settings(BRANCH_ID='selftest-branch')
def test_mock_sync_uses_branch_owned_model_and_cleans_up_directly(monkeypatch):
    from base.models import Customer
    from base.services.sync.receiver import CloudReceiver
    from desktop.bridge import Api

    filters = []
    deleted = []
    received = []

    class Readback:
        def __init__(self, record_uuid):
            self.pk = 41
            self.uuid = record_uuid
            self.branch_id = 'selftest-branch'
            self.name = 'ALPHA POS SYNC SELFTEST'
            self.sync_version = 1
            self.is_deleted = False

    class FakeQuerySet:
        def __init__(self, criteria):
            self.criteria = criteria

        def first(self):
            return Readback(self.criteria['uuid']) if 'uuid' in self.criteria else None

        def delete(self):
            deleted.append(self.criteria)
            return 1, {'base.Customer': 1}

    class FakeManager:
        def filter(self, **criteria):
            filters.append(criteria)
            return FakeQuerySet(criteria)

    def fake_receive(model_name, branch_id, records):
        received.append((model_name, branch_id, records))
        return {
            'success': True, 'created': 1, 'updated': 0,
            'skipped': 0, 'errors': [],
        }

    monkeypatch.setattr(Customer, 'objects', FakeManager())
    monkeypatch.setattr(CloudReceiver, 'receive_batch', fake_receive)
    api = Api()
    api.server.ensure_django = lambda: None

    result = api.send_mock_sync()

    assert Customer.SYNC_PULL_SCOPE == 'branch'
    assert received[0][0:2] == ('customer', 'selftest-branch')
    assert received[0][2][0]['name'] == 'ALPHA POS SYNC SELFTEST'
    assert result['ok'] is True
    assert result['read_back'] is True
    assert result['model'] == 'customer'
    assert len(filters) == 2
    assert deleted == [{'pk': 41}]


@pytest.mark.django_db
@override_settings(BRANCH_ID='selftest-branch', DEPLOYMENT_MODE='local')
def test_mock_sync_roundtrips_through_the_real_receiver():
    from base.models import Customer
    from desktop.bridge import Api

    api = Api()
    api.server.ensure_django = lambda: None

    result = api.send_mock_sync()

    assert result['ok'] is True
    assert result['read_back'] is True
    assert result['model'] == 'customer'
    assert result['received'] == {
        'success': True,
        'created': 1,
        'updated': 0,
        'skipped': 0,
        'errors': [],
    }
    assert not Customer._base_manager.filter(uuid=result['sent']['uuid']).exists()


def test_cloud_push_bridge_does_not_hide_service_failure(monkeypatch):
    from base.services.sync.service import SyncService
    from desktop.bridge import Api

    monkeypatch.setattr(
        SyncService,
        'push',
        lambda: {'success': False, 'message': 'Cannot reach cloud server'},
    )
    api = Api()
    api.server.ensure_django = lambda: None

    result = api.cloud_push()

    assert result['ok'] is False
    assert result['error'] == 'Cannot reach cloud server'
    assert result['result']['success'] is False


def test_cloud_sync_bridge_requires_every_enabled_leg_to_succeed(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService
    from desktop.bridge import Api

    monkeypatch.setattr(SyncService, 'push', lambda: {'success': True, 'synced': 3})
    monkeypatch.setattr(
        SyncService,
        'pull_from_cloud',
        lambda: {'success': False, 'message': 'Pull cursor rejected'},
    )
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: True)
    api = Api()
    api.server.ensure_django = lambda: None

    result = api.cloud_sync_now()

    assert result['ok'] is False
    assert result['error'] == 'Pull cursor rejected'


def test_cloud_sync_bridge_treats_disabled_pull_as_an_explicit_skip(monkeypatch):
    from base.services.sync import config as sync_config
    from base.services.sync.service import SyncService
    from desktop.bridge import Api

    monkeypatch.setattr(SyncService, 'push', lambda: {'success': True, 'synced': 0})
    monkeypatch.setattr(sync_config, 'get_pull_enabled', lambda: False)
    api = Api()
    api.server.ensure_django = lambda: None

    result = api.cloud_sync_now()

    assert result['ok'] is True
    assert result['pull']['success'] is True
    assert result['pull']['skipped'] is True


def test_database_flush_clears_old_setup_signature_and_reports_restart_failure(
        monkeypatch, tmp_path):
    import sys
    from django.db import connections
    from desktop.bridge import Api

    _config_paths(monkeypatch, tmp_path)
    config_store.write_state({'setup_sig': 'old-release:old-schema', 'ui': {'lang': 'uz'}})
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(connections, 'close_all', lambda: None)
    monkeypatch.setattr(pg_embedded, 'stop', lambda: True)
    monkeypatch.setattr(pg_embedded, 'start', lambda: True)

    class FakeServer:
        setup_calls = 0

        @staticmethod
        def stop(**_kwargs):
            return {'workers_quiescent': True}

        def first_time_install(self):
            self.setup_calls += 1

        @staticmethod
        def start():
            return {'running': False, 'error': 'bind failed'}

    api = Api()
    api.server = FakeServer()
    result = api.flush_database(confirm=True)

    assert result['ok'] is False
    assert 'bind failed' in result['error']
    assert api.server.setup_calls == 1
    state = config_store.read_state()
    assert 'setup_sig' not in state
    assert state['ui'] == {'lang': 'uz'}


def test_local_health_check_does_not_hairpin_through_lan_address(monkeypatch):
    import urllib.request
    from desktop.bridge import Api

    requested = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'ok'

    class FakeServer:
        port = 8123

        @staticmethod
        def is_running():
            return True

        @staticmethod
        def url():
            return 'http://192.168.50.12:8123'

    def fake_urlopen(url, timeout):
        requested.append((url, timeout))
        return Response()

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    api = Api()
    api.server = FakeServer()
    assert api.test_server_connection()['ok'] is True
    assert requested == [('http://127.0.0.1:8123/healthz', 5)]


def test_update_launch_is_confirmed_only_after_backend_readiness():
    from desktop import app

    ready = threading.Event()
    shutdown = threading.Event()
    confirmed = threading.Event()

    class FakeUpdater:
        @staticmethod
        def mark_started_ok():
            confirmed.set()

    thread = threading.Thread(
        target=app._confirm_update_start_when_ready,
        kwargs={
            'ready_event': ready,
            'shutdown_event': shutdown,
            'updater_module': FakeUpdater,
        },
    )
    thread.start()
    assert not confirmed.wait(0.1)
    ready.set()
    assert confirmed.wait(1.0)
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def test_server_start_waits_for_real_bind_and_stop_joins(monkeypatch):
    import uvicorn

    class FakeServer:
        def __init__(self, _config):
            self.started = False
            self.should_exit = False

        def run(self):
            time.sleep(0.08)
            self.started = True
            while not self.should_exit:
                time.sleep(0.01)
            self.started = False

    monkeypatch.setattr(uvicorn, 'Config', lambda *a, **k: object())
    monkeypatch.setattr(uvicorn, 'Server', FakeServer)
    manager = ServerManager()
    manager.ensure_django = lambda: None
    manager.ensure_background_workers = lambda: None
    manager.lan_ip = lambda **_kwargs: '192.168.1.20'

    started_at = time.monotonic()
    result = manager.start()
    assert time.monotonic() - started_at >= 0.07
    assert result['running'] is True
    assert manager.is_running()
    manager.stop()
    assert not manager.is_running()
    assert manager._thread is None


def test_server_start_skips_uvicorn_console_logging_without_gui_streams(monkeypatch):
    import uvicorn

    configs = []

    class FakeServer:
        def __init__(self, config):
            configs.append(config)
            self.started = False
            self.should_exit = False

        def run(self):
            self.started = True
            while not self.should_exit:
                time.sleep(0.01)
            self.started = False

    # Keep the real Config constructor: Uvicorn's default log formatter is the
    # exact component that dereferences sys.stderr in a windowed executable.
    monkeypatch.setattr(uvicorn, 'Server', FakeServer)
    manager = ServerManager()
    manager.ensure_django = lambda: None
    manager.ensure_background_workers = lambda: None
    manager.lan_ip = lambda **_kwargs: '192.168.1.20'

    try:
        with monkeypatch.context() as gui:
            gui.setattr(sys, 'stdout', None)
            gui.setattr(sys, 'stderr', None)
            result = manager.start()

        assert result['running'] is True
        assert len(configs) == 1
        assert configs[0].log_config is None
    finally:
        manager.stop()


def test_server_bind_failure_is_reported_not_false_online(monkeypatch):
    import uvicorn

    class FailingServer:
        started = False
        should_exit = False

        def __init__(self, _config):
            pass

        def run(self):
            raise SystemExit('address already in use')

    monkeypatch.setattr(uvicorn, 'Config', lambda *a, **k: object())
    monkeypatch.setattr(uvicorn, 'Server', FailingServer)
    manager = ServerManager()
    manager.ensure_django = lambda: None
    manager.ensure_background_workers = lambda: None
    result = manager.start()
    assert result['running'] is False
    assert 'address already in use' in result['error']
    assert not manager.is_running()


def test_static_assets_revalidate_but_html_is_never_cached():
    httpd = control_server.ThreadingHTTPServer(
        ('127.0.0.1', 0), control_server.Handler,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/app.bundle.js')
        first = conn.getresponse()
        first.read()
        etag = first.getheader('ETag')
        assert first.status == 200
        assert etag
        assert first.getheader('Cache-Control') == 'private, max-age=0, must-revalidate'
        conn.close()

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/app.bundle.js', headers={'If-None-Match': etag})
        second = conn.getresponse()
        second.read()
        assert second.status == 304
        conn.close()

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request('GET', '/')
        html = conn.getresponse()
        html.read()
        assert html.getheader('Cache-Control') == 'no-store'
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_precompiled_ui_bundle_matches_every_source():
    root = Path(__file__).resolve().parent
    ui = root / 'desktop' / 'ui'
    inputs = [
        'app/bridge.js', 'app/config-import.js', 'app/i18n.js', 'app/ui.jsx',
        'app/screens-main.jsx', 'app/screens-admin.jsx',
        'app/screens-ops.jsx', 'app/screens-updates.jsx',
        'app/screens-logs.jsx', 'app/main.jsx',
    ]
    digest = hashlib.sha256()
    for relative in inputs:
        source = (ui / relative).read_text(encoding='utf-8-sig')
        source = source.replace('\r\n', '\n').replace('\r', '\n')
        digest.update(relative.encode())
        digest.update(b'\0')
        digest.update(source.encode())
        digest.update(b'\0')
    bundle = (ui / 'app.bundle.js').read_text(encoding='utf-8')
    match = re.search(r'source-sha256: ([0-9a-f]{64})', bundle)
    assert match and match.group(1) == digest.hexdigest()

    index = (ui / 'index.html').read_text(encoding='utf-8')
    assert 'app.bundle.js' in index
    assert 'type="text/babel"' not in index
    assert 'vendor/babel.min.js' not in index
    assert 'fonts.googleapis.com' not in index
    assert len(bundle.encode('utf-8')) < 250_000

    build = (root / 'build_installer.ps1').read_text(encoding='utf-8')
    compile_pos = build.index("tools\\compile_desktop_ui.js")
    pyinstaller_pos = build.index("& $pyinstaller")
    assert compile_pos < pyinstaller_pos
    assert "AlphaPOS-$version-Setup.exe" in build
    assert "AlphaPOS-$version-Portable.exe" in build
