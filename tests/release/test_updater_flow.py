"""Windows signed-update handoff tests."""
from __future__ import annotations

import os
import subprocess
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from desktop import updater


@pytest.fixture(autouse=True)
def reset_updater_runtime(monkeypatch):
    updater._set_runtime(
        active=False,
        phase="idle",
        progress=0,
        message="",
        bytes_downloaded=0,
        bytes_total=0,
        target_version=None,
        retryable=False,
    )
    monkeypatch.setattr(updater, "_SHUTDOWN_CALLBACK", None)
    yield
    updater._set_runtime(active=False, phase="idle")


def test_start_update_returns_immediately_and_rejects_duplicate(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def worker():
        entered.set()
        release.wait(2)

    monkeypatch.setattr(updater, "_install_worker", worker)
    first = updater.start_update()
    assert first["started"] is True
    assert entered.wait(1)

    second = updater.start_update()
    assert second == {
        "started": False,
        "busy": True,
        "message": "An update is already in progress.",
    }
    release.set()
    updater._UPDATE_THREAD.join(2)


def test_verified_download_launches_helper_then_requests_graceful_stop(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    helper_calls = []
    stopped = threading.Event()

    class Client:
        def check_for_updates(self):
            return SimpleNamespace(version="2.4.0")

        def download_and_apply_update(self, *, install: callable, progress_hook, **_kwargs):
            progress_hook(bytes_downloaded=50, bytes_expected=100)
            install(src_dir=stage, dst_dir=install_dir)

    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_enabled", lambda: (True, "ok"))
    monkeypatch.setattr(updater, "_new_stage_dir", lambda: stage)
    monkeypatch.setattr(updater, "_make_client", lambda **_kwargs: Client())
    monkeypatch.setattr(
        updater,
        "_launch_swap_helper",
        lambda src, dst, version: helper_calls.append((src, dst, version)),
    )
    monkeypatch.setattr(updater, "_SHUTDOWN_CALLBACK", stopped.set)
    updater._set_runtime(active=True)

    updater._install_worker()

    assert helper_calls == [(stage, install_dir, "2.4.0")]
    assert stopped.is_set()
    assert (data / updater._PENDING_MARKER).read_text(encoding="utf-8") == "2.4.0"
    status = updater._runtime_snapshot()
    assert status["active"] is True
    assert status["phase"] == "restarting"
    assert status["bytes_downloaded"] == 50
    assert status["bytes_total"] == 100


def test_helper_launch_failure_keeps_current_install_and_cleans_stage(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    class Client:
        def check_for_updates(self):
            return SimpleNamespace(version="2.4.0")

        def download_and_apply_update(self, *, install: callable, **_kwargs):
            install(src_dir=stage, dst_dir=install_dir)

    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_enabled", lambda: (True, "ok"))
    monkeypatch.setattr(updater, "_new_stage_dir", lambda: stage)
    monkeypatch.setattr(updater, "_make_client", lambda **_kwargs: Client())
    monkeypatch.setattr(
        updater,
        "_launch_swap_helper",
        mock.Mock(side_effect=OSError("helper blocked")),
    )
    monkeypatch.setattr(updater, "_SHUTDOWN_CALLBACK", mock.Mock())
    updater._set_runtime(active=True)

    updater._install_worker()

    assert install_dir.is_dir()
    assert not stage.exists()
    assert not (data / updater._PENDING_MARKER).exists()
    status = updater._runtime_snapshot()
    assert status["active"] is False
    assert status["phase"] == "error"
    assert status["retryable"] is True
    assert "helper blocked" in status["message"]


def test_pending_marker_is_atomically_published_and_verified(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    replacements = []
    real_replace = updater.os.replace

    def recording_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater.os, "replace", recording_replace)

    updater._write_pending("2.4.0")

    marker = data / updater._PENDING_MARKER
    assert marker.read_text(encoding="utf-8") == "2.4.0"
    assert replacements and replacements[-1][1] == marker
    assert replacements[-1][0].parent == marker.parent
    assert not list(data.glob("*.tmp"))


def test_bridge_update_url_always_tracks_canonical_config(monkeypatch):
    from desktop import config_store
    from desktop.bridge import Api

    api = object.__new__(Api)
    monkeypatch.setenv(updater.UPDATE_URL_ENV, "https://stale-parent.invalid")
    monkeypatch.setattr(
        config_store,
        "read_config",
        lambda: {updater.UPDATE_URL_ENV: "https://updates.example.test/repo"},
    )

    api._ensure_update_env()

    assert os.environ[updater.UPDATE_URL_ENV] == "https://updates.example.test/repo"

    monkeypatch.setattr(
        config_store, "read_config", lambda: {updater.UPDATE_URL_ENV: ""}
    )
    api._ensure_update_env()
    assert updater.UPDATE_URL_ENV not in os.environ


def test_swap_helper_process_has_no_console(tmp_path, monkeypatch):
    helper = tmp_path / "update_helper.ps1"
    helper.write_text("# helper", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    popen = mock.Mock(return_value=SimpleNamespace(pid=42))
    ready_wait = mock.Mock()
    monkeypatch.setattr(updater, "_bundled_helper", lambda: helper)
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_powershell_executable", lambda: "powershell.exe")
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    monkeypatch.setattr(updater, "_wait_helper_ready", ready_wait)

    updater._launch_swap_helper(tmp_path / "stage", tmp_path / "app", "2.4.0")

    command = popen.call_args.args[0]
    kwargs = popen.call_args.kwargs
    assert command[0] == "powershell.exe"
    assert command[command.index("-WindowStyle") + 1] == "Hidden"
    assert "-STA" in command
    assert "-ReadyPath" in command
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert not kwargs["creationflags"] & getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    assert kwargs["close_fds"] is True
    ready_path = Path(command[command.index("-ReadyPath") + 1])
    ready_wait.assert_called_once_with(popen.return_value, ready_path)


def test_helper_ready_signal_is_required_before_live_app_shutdown(tmp_path):
    ready = tmp_path / "helper.ready"
    ready.write_text("ready", encoding="ascii")
    process = mock.Mock()
    process.poll.return_value = None

    updater._wait_helper_ready(process, ready)

    assert not ready.exists()
    process.poll.assert_called_once_with()


def test_helper_early_exit_and_timeout_fail_without_closing_live_app(
    tmp_path, monkeypatch
):
    exited = mock.Mock()
    exited.poll.return_value = 9
    with pytest.raises(RuntimeError, match="exited before it was ready"):
        updater._wait_helper_ready(exited, tmp_path / "missing.ready")

    waiting = mock.Mock()
    waiting.poll.return_value = None
    monkeypatch.setattr(updater, "_HELPER_READY_TIMEOUT_SECONDS", -1)
    with pytest.raises(RuntimeError, match="left running"):
        updater._wait_helper_ready(waiting, tmp_path / "missing.ready")


def test_mismatched_pending_marker_preserves_rollback_contract(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / updater._PENDING_MARKER).write_text("99.0.0", encoding="utf-8")
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    cleanup = mock.Mock()
    monkeypatch.setattr(updater, "_cleanup_previous_install", cleanup)

    updater.mark_started_ok()

    state = updater._load_state()
    assert state.get("history") in (None, [])
    assert "99.0.0" in state["last_check_error"]
    assert updater.__version__ in state["last_check_error"]
    assert "kept for safe recovery" in state["last_check_error"]
    assert (data / updater._PENDING_MARKER).exists()
    cleanup.assert_not_called()


def test_matching_pending_marker_confirms_and_schedules_cleanup(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    marker = data / updater._PENDING_MARKER
    marker.write_text(updater.__version__, encoding="utf-8")
    cleaned = threading.Event()
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_cleanup_previous_install", cleaned.set)
    monkeypatch.setattr(updater, "_ROLLBACK_SETTLE_SECONDS", 0)

    updater.mark_started_ok()

    assert cleaned.wait(1)
    assert not marker.exists()
    state = updater._load_state()
    assert state["last_update_version"] == updater.__version__
    assert state["history"][-1]["version"] == updater.__version__


def test_marker_delete_failure_never_discards_rollback(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    marker = data / updater._PENDING_MARKER
    marker.write_text(updater.__version__, encoding="utf-8")
    cleanup = mock.Mock()
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_clear_pending", lambda: False)
    monkeypatch.setattr(updater, "_cleanup_previous_install", cleanup)

    updater.mark_started_ok()

    state = updater._load_state()
    assert marker.exists()
    assert state["last_check_ok"] is False
    assert "could not be cleared" in state["last_check_error"]
    assert state.get("last_update_version") is None
    cleanup.assert_not_called()


def test_rollback_cleanup_waits_past_helper_forced_stop_window(monkeypatch):
    slept = []
    cleanup = mock.Mock()
    monkeypatch.setattr(updater.time, "sleep", slept.append)
    monkeypatch.setattr(updater, "_cleanup_previous_install", cleanup)

    updater._cleanup_after_helper_settles()

    assert slept == [updater._ROLLBACK_SETTLE_SECONDS]
    assert updater._ROLLBACK_SETTLE_SECONDS >= 20
    cleanup.assert_called_once_with()


def test_next_healthy_launch_prunes_confirmed_backup_if_prior_app_closed_early(
    tmp_path, monkeypatch
):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    updater._save_state({"last_update_version": updater.__version__})
    cleaned = threading.Event()
    monkeypatch.setattr(updater, "_cleanup_previous_install", cleaned.set)

    updater.mark_started_ok()

    assert cleaned.wait(1)


def test_tufup_system_exit_is_converted_to_retryable_update_error():
    class Client:
        def check_for_updates(self):
            raise SystemExit()

    with pytest.raises(RuntimeError, match="could not be downloaded or verified"):
        updater._check_for_updates(Client())


def test_install_refresh_system_exit_cleans_stage_and_releases_modal(
    tmp_path, monkeypatch
):
    data = tmp_path / "data"
    data.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()

    class Client:
        def check_for_updates(self):
            raise SystemExit()

    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_enabled", lambda: (True, "ok"))
    monkeypatch.setattr(updater, "_new_stage_dir", lambda: stage)
    monkeypatch.setattr(updater, "_make_client", lambda **_kwargs: Client())
    monkeypatch.setattr(updater, "_SHUTDOWN_CALLBACK", mock.Mock())
    updater._set_runtime(active=True)

    updater._install_worker()

    status = updater._runtime_snapshot()
    assert status["active"] is False
    assert status["phase"] == "error"
    assert status["retryable"] is True
    assert "could not be downloaded or verified" in status["message"]
    assert not stage.exists()
    assert not (data / updater._PENDING_MARKER).exists()


def test_download_system_exit_cleans_stage_and_releases_modal(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()

    class Client:
        @staticmethod
        def check_for_updates():
            return SimpleNamespace(version="2.4.0")

        @staticmethod
        def download_and_apply_update(**_kwargs):
            raise SystemExit('target verification aborted')

    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_enabled", lambda: (True, "ok"))
    monkeypatch.setattr(updater, "_new_stage_dir", lambda: stage)
    monkeypatch.setattr(updater, "_make_client", lambda **_kwargs: Client())
    monkeypatch.setattr(updater, "_SHUTDOWN_CALLBACK", mock.Mock())
    updater._set_runtime(active=True)

    updater._install_worker()

    status = updater._runtime_snapshot()
    assert status["active"] is False
    assert status["phase"] == "error"
    assert status["retryable"] is True
    assert "target verification aborted" in status["message"]
    assert not stage.exists()
    assert not (data / updater._PENDING_MARKER).exists()


def test_thread_start_failure_does_not_leave_update_modal_busy(monkeypatch):
    class BrokenThread:
        @staticmethod
        def start():
            raise RuntimeError('thread runtime unavailable')

    monkeypatch.setattr(updater.threading, 'Thread', lambda **_kwargs: BrokenThread())

    result = updater.start_update()

    assert result['started'] is False
    assert 'thread runtime unavailable' in result['error']
    status = updater._runtime_snapshot()
    assert status['active'] is False
    assert status['phase'] == 'error'
    assert status['retryable'] is True


@pytest.mark.parametrize(
    "failure",
    [
        "network failed while downloading signed metadata",
        "unsigned metadata failed signature verification",
    ],
)
def test_metadata_refresh_failure_is_never_reported_as_up_to_date(
    failure, tmp_path, monkeypatch
):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_enabled", lambda: (True, "ok"))
    monkeypatch.setattr(updater, "_make_client", lambda **_kwargs: object())
    monkeypatch.setattr(
        updater, "_check_for_updates", mock.Mock(side_effect=RuntimeError(failure))
    )

    result = updater.check_only()

    assert result["enabled"] is True
    assert result["available"] is None
    assert result["error"] == failure
    state = updater._load_state()
    assert state["last_check_ok"] is False
    assert state["last_check_error"] == failure


def test_tuf_client_requires_fresh_verified_metadata(tmp_path, monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    root = tmp_path / "root.json"
    root.write_text("{}", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv(updater.UPDATE_URL_ENV, "https://updates.example.test")
    monkeypatch.setattr(updater, "_data_dir", lambda: data)
    monkeypatch.setattr(updater, "_bundled_root", lambda: root)
    monkeypatch.setattr("tufup.client.Client", Client)

    updater._make_client()

    assert captured["refresh_required"] is True


def test_helper_contract_is_bounded_atomic_and_rollback_capable():
    script = Path(updater.__file__).with_name("update_helper.ps1").read_text(encoding="utf-8")
    lowered = script.lower()
    assert "createnowindow = $true" in lowered
    assert "robocopy" not in lowered
    assert "[validaterange(1, 30)][int]$maxswapattempts = 12" in lowered
    assert "[validaterange(1, 120)][int]$waittimeoutseconds = 45" in lowered
    assert "move-bounded $destination $backup" in lowered
    assert "move-bounded $source $destination" in lowered
    assert "restore-previousinstall" in lowered
    assert "testfailafterbackup" in lowered
    assert "[validaterange(1, 600)][int]$healthtimeoutseconds = 120" in lowered
    assert "$script:phase = 'verify-health'" in lowered
    assert "test-path -literalpath $markerpath" in lowered
    assert "rollback-unhealthyversion" in lowered
    assert "taskkill.exe" in lowered
    assert "pending update marker does not match version" in lowered
    assert "$script:successcloser.stop()" in lowered
    assert "$this.stop()" not in lowered
    assert "set-content -literalpath $readypath" in lowered
    assert "$window.add_contentrendered" in lowered
    rendered = lowered.split("$window.add_contentrendered", 1)[1]
    assert rendered.index("pending update marker does not match") < rendered.index(
        "set-content -literalpath $readypath"
    )


def test_onedir_build_bundles_helper_but_portable_remains_non_updating():
    root = Path(updater.__file__).resolve().parent.parent
    onedir = (root / "AlphaPOS.spec").read_text(encoding="utf-8")
    onefile = (root / "AlphaPOS-onefile.spec").read_text(encoding="utf-8")
    expected = "('desktop/update_helper.ps1', 'desktop')"
    assert expected in onedir
    assert expected not in onefile


def _headless_helper_command(tmp_path, source, destination, *extra):
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    marker = tmp_path / "pending.flag"
    marker.write_text("2.4.0", encoding="utf-8")
    return [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(Path(updater.__file__).with_name("update_helper.ps1")),
        "-ParentPid",
        "2147483646",
        "-Source",
        str(source),
        "-Destination",
        str(destination),
        "-Version",
        "2.4.0",
        "-MarkerPath",
        str(marker),
        "-LogPath",
        str(tmp_path / "helper.log"),
        "-Headless",
        "-SkipRelaunch",
        *extra,
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper contract")
def test_headless_helper_atomically_swaps_and_preserves_uninstaller(tmp_path):
    current = tmp_path / "AlphaPOS"
    staged = tmp_path / ".AlphaPOS.update-test"
    current.mkdir()
    staged.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    (current / "unins000.dat").write_text("installer", encoding="utf-8")
    (staged / "new.txt").write_text("new", encoding="utf-8")

    result = subprocess.run(
        _headless_helper_command(tmp_path, staged, current),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (current / "new.txt").read_text(encoding="utf-8") == "new"
    assert (current / "unins000.dat").read_text(encoding="utf-8") == "installer"
    assert (tmp_path / ".AlphaPOS.previous" / "old.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper contract")
def test_headless_helper_refuses_mismatched_pending_marker(tmp_path):
    current = tmp_path / "AlphaPOS"
    staged = tmp_path / ".AlphaPOS.update-test"
    current.mkdir()
    staged.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    (staged / "new.txt").write_text("new", encoding="utf-8")
    command = _headless_helper_command(tmp_path, staged, current)
    (tmp_path / "pending.flag").write_text("3.0.0", encoding="utf-8")

    result = subprocess.run(command, capture_output=True, text=True, timeout=15)

    assert result.returncode == 1
    assert (current / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (current / "new.txt").exists()
    assert staged.is_dir()
    assert not (tmp_path / "pending.flag").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper contract")
def test_headless_helper_rolls_back_even_after_new_version_activation(tmp_path):
    current = tmp_path / "AlphaPOS"
    staged = tmp_path / ".AlphaPOS.update-test"
    current.mkdir()
    staged.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    (staged / "new.txt").write_text("new", encoding="utf-8")

    result = subprocess.run(
        _headless_helper_command(
            tmp_path, staged, current, "-TestFailAfterActivation"
        ),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 1
    assert (current / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (current / "new.txt").exists()
    assert not (tmp_path / "pending.flag").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper contract")
def test_headless_helper_waits_for_matching_health_confirmation(tmp_path):
    current = tmp_path / "AlphaPOS"
    staged = tmp_path / ".AlphaPOS.update-test"
    current.mkdir()
    staged.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    (staged / "new.txt").write_text("new", encoding="utf-8")

    result = subprocess.run(
        _headless_helper_command(
            tmp_path,
            staged,
            current,
            "-TestHealthConfirmation",
            "-TestConfirmHealth",
            "-HealthTimeoutSeconds",
            "1",
        ),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (current / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (tmp_path / "pending.flag").exists()
    assert (tmp_path / ".AlphaPOS.previous" / "old.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows helper contract")
def test_headless_helper_health_timeout_rolls_back_and_clears_marker(tmp_path):
    current = tmp_path / "AlphaPOS"
    staged = tmp_path / ".AlphaPOS.update-test"
    current.mkdir()
    staged.mkdir()
    (current / "old.txt").write_text("old", encoding="utf-8")
    (staged / "new.txt").write_text("new", encoding="utf-8")

    result = subprocess.run(
        _headless_helper_command(
            tmp_path,
            staged,
            current,
            "-TestHealthConfirmation",
            "-HealthTimeoutSeconds",
            "1",
        ),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 1
    assert (current / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (current / "new.txt").exists()
    assert not (tmp_path / "pending.flag").exists()
    log = (tmp_path / "helper.log").read_text(encoding="utf-8-sig")
    assert "did not confirm backend health" in log


def test_startup_checks_but_does_not_surprise_install():
    app_source = Path(updater.__file__).with_name("app.py").read_text(encoding="utf-8")
    boot_worker = app_source.split("def _boot_worker", 1)[1].split("def main", 1)[0]
    assert "updater.check_only()" in boot_worker
    assert "updater.check_and_apply()" not in boot_worker
