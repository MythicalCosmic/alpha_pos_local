"""Setup failures and readiness as the panel and the desktop shell see them."""

from __future__ import annotations

import logging

import pytest

from desktop import bridge, control_server, server_manager
from desktop.server_manager import ServerManager, SetupUnavailable


def _manager(monkeypatch, outcomes):
    """A manager whose setup consumes ``outcomes`` (exception or None) per run."""
    runs = []

    def fake_setup(log=lambda m: None):
        runs.append(True)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    manager = ServerManager()
    monkeypatch.setattr(manager, '_run_first_time_install', fake_setup)
    return manager, runs


def test_a_failed_setup_is_not_rerun_by_every_panel_call(monkeypatch):
    failure = RuntimeError('Could not initialize embedded PostgreSQL: FATAL: locale\nline two of the log')
    manager, runs = _manager(monkeypatch, [failure, None])

    with pytest.raises(RuntimeError, match='embedded PostgreSQL'):
        manager.ensure_django(supervisor=True)
    # Panel polls during the cool-off get the recorded reason, instantly.
    for _ in range(5):
        with pytest.raises(SetupUnavailable) as refused:
            manager.ensure_django()
        assert 'keeps retrying' in str(refused.value)
        assert 'line two' not in str(refused.value)  # one readable line
    assert len(runs) == 1
    status = manager.status()
    assert status['django_ready'] is False
    assert 'keeps retrying' in status['setup_error']

    # The boot supervisor is the one that retries, cool-off or not.
    manager.ensure_django(supervisor=True)
    assert len(runs) == 2
    assert manager.status()['setup_error'] == ''
    manager.ensure_django()  # ready: no further setup runs
    assert len(runs) == 2


def test_panel_calls_retry_setup_once_the_cool_off_passed(monkeypatch):
    manager, runs = _manager(monkeypatch, [RuntimeError('boom'), None])
    with pytest.raises(RuntimeError):
        manager.ensure_django()
    later = manager._setup_failed_at + 60
    monkeypatch.setattr(server_manager.time, 'monotonic', lambda: later)
    manager.ensure_django()
    assert len(runs) == 2


def test_ready_means_django_loaded_and_setup_finished(monkeypatch):
    manager, _runs = _manager(monkeypatch, [None])
    manager._django_ready = True  # django.setup() done, migrations still running
    assert manager.status()['django_ready'] is False
    manager.ensure_django()
    assert manager.status()['django_ready'] is True


def test_operator_refusals_are_not_logged_as_errors(caplog):
    class Api:
        @bridge._safe
        def refuse(self):
            raise RuntimeError('Enable local Telegram audit first.')

        @bridge._safe
        def crash(self):
            return {}['missing']

    with caplog.at_level(logging.INFO, logger='desktop.bridge'):
        assert Api().refuse() == {'ok': False, 'error': 'Enable local Telegram audit first.'}
        assert Api().crash()['ok'] is False
    refused, crashed = caplog.records
    assert (refused.levelno, refused.exc_info) == (logging.INFO, None)
    assert crashed.levelno == logging.ERROR and crashed.exc_info


def test_shell_port_zero_is_not_reported_as_a_problem(caplog):
    with caplog.at_level(logging.INFO, logger='desktop.control'):
        httpd = control_server.serve(preferred_port=0)
    try:
        assert control_server.CONTROL_PORT == httpd.server_address[1]
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    finally:
        httpd.server_close()


def _initdb_recorder(monkeypatch, tmp_path, succeed_on):
    """Fake initdb: succeeds on the attempt whose args contain ``succeed_on``."""
    from types import SimpleNamespace

    from desktop import pg_embedded

    data = tmp_path / 'pgdata'
    attempts = []

    def fake_run(bin_dir, exe, *args, **kwargs):
        assert exe == 'initdb.exe'
        attempts.append(args)
        if succeed_on is not None and succeed_on in args:
            data.mkdir(exist_ok=True)
            (data / 'PG_VERSION').write_text('16\n')
            return SimpleNamespace(returncode=0, stdout='Success', stderr='')
        return SimpleNamespace(returncode=1, stdout='', stderr='FATAL:  new collation (en) is incompatible')

    monkeypatch.setattr(pg_embedded, '_run', fake_run)
    return pg_embedded, data, attempts


def test_initdb_falls_back_to_icu_when_the_windows_locale_is_unusable(monkeypatch, tmp_path):
    pg_embedded, data, attempts = _initdb_recorder(monkeypatch, tmp_path, '--locale-provider=icu')
    pg_embedded._initialise_cluster(tmp_path, data)
    assert len(attempts) == 2
    assert '--locale=C' not in attempts[0]  # the first try is what existing tills used
    assert {'--locale=C', '--locale-provider=icu', '--icu-locale=und'} <= set(attempts[1])


def test_initdb_reports_the_last_error_when_every_locale_fails(monkeypatch, tmp_path):
    pg_embedded, data, attempts = _initdb_recorder(monkeypatch, tmp_path, None)
    with pytest.raises(pg_embedded.EmbeddedPostgresError, match='new collation'):
        pg_embedded._initialise_cluster(tmp_path, data)
    assert len(attempts) == 3


def test_psql_output_is_read_as_utf8(monkeypatch, tmp_path):
    from desktop import pg_embedded
    seen = {}

    def fake_subprocess_run(command, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(pg_embedded.subprocess, 'run', fake_subprocess_run)
    pg_embedded._run(tmp_path, 'psql.exe', '-tAc', 'SHOW data_directory')
    assert seen['encoding'] == 'utf-8' and seen['errors'] == 'replace'
    assert seen['env']['PGCLIENTENCODING'] == 'UTF8'


class _FakeKernel32:
    """CreateMutexW reports ALREADY_EXISTS for the first ``busy_calls`` calls."""

    def __init__(self, ctypes_module, busy_calls):
        self._ctypes = ctypes_module
        self.busy_calls = busy_calls
        self.closed = []
        self.created = 0
        outer = self

        class _Fn:
            restype = None
            argtypes = None

            def __init__(self, impl):
                self._impl = impl

            def __call__(self, *args):
                return self._impl(*args)

        def create(_attrs, _owner, _name):
            outer.created += 1
            busy = outer.created <= outer.busy_calls
            outer._ctypes.set_last_error(183 if busy else 0)
            return 1000 + outer.created

        self.CreateMutexW = _Fn(create)
        self.CloseHandle = _Fn(lambda handle: outer.closed.append(handle) or 1)


def _fake_windows(monkeypatch, busy_calls):
    import ctypes

    from desktop import single_instance

    last_error = {'value': 0}
    monkeypatch.setattr(ctypes, 'set_last_error', lambda value: last_error.update(value=value), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: last_error['value'], raising=False)
    kernel = _FakeKernel32(ctypes, busy_calls)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: kernel, raising=False)
    monkeypatch.setattr(single_instance.time, 'sleep', lambda _s: None)
    monkeypatch.setattr(single_instance, '_handles', {})
    return single_instance, kernel


def test_single_instance_waits_for_the_previous_owner_and_drops_stale_handles(monkeypatch):
    single_instance, kernel = _fake_windows(monkeypatch, busy_calls=2)
    assert single_instance.acquire('Global\\Test', wait_seconds=30) is True
    # Both "already exists" handles were closed; only the winning one is kept.
    assert kernel.closed == [1001, 1002]
    assert single_instance._handles == {'Global\\Test': 1003}


def test_single_instance_without_a_wait_reports_the_running_copy(monkeypatch):
    single_instance, kernel = _fake_windows(monkeypatch, busy_calls=99)
    assert single_instance.acquire('Global\\Test') is False
    assert kernel.closed == [1001]
    assert single_instance._handles == {}
