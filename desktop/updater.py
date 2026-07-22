"""Signed, non-disruptive self-updates for the packaged Windows app.

The update has two deliberately separate phases:

* AlphaPOS downloads and verifies the TUF target while it is still running.  A
  small modal in the control panel reads the live progress exposed here.
* A PowerShell/WPF helper, copied outside the install directory, waits for a
  graceful AlphaPOS shutdown, atomically swaps the staged directory, and
  relaunches the app.  It has bounded waits/retries and never opens a console.

This avoids tufup's default Windows installer.  That installer starts a visible
``cmd.exe`` and runs robocopy without ``/R``; robocopy's Windows default is one
million retries, so files held by the running app looked like an endless loop.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from desktop.version import APP_NAME, __version__

logger = logging.getLogger("desktop.updater")

UPDATE_URL_ENV = "ALPHA_POS_UPDATE_URL"
_PENDING_MARKER = "update_pending.flag"
_STATE_FILE = "update_state.json"
_HELPER_NAME = "update_helper.ps1"
_ROLLBACK_SETTLE_SECONDS = 30
_HELPER_READY_TIMEOUT_SECONDS = 8

_STATE_LOCK = threading.RLock()
_OPERATION_LOCK = threading.Lock()
_RUNTIME_LOCK = threading.RLock()
_SHUTDOWN_CALLBACK: Callable[[], None] | None = None
_UPDATE_THREAD: threading.Thread | None = None
_RUNTIME = {
    "active": False,
    "phase": "idle",
    "progress": 0,
    "message": "",
    "bytes_downloaded": 0,
    "bytes_total": 0,
    "target_version": None,
    "retryable": False,
}


def _data_dir() -> Path:
    # One canonical path for config, database, update metadata and markers.
    # In particular, config_store handles Startup-folder environments where
    # LOCALAPPDATA is missing; duplicating that fallback here previously split
    # manual and auto-start launches across two different AlphaPOS directories.
    from desktop import config_store

    directory = config_store.DATA_DIR / "update"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_state() -> dict:
    with _STATE_LOCK:
        try:
            value = json.loads((_data_dir() / _STATE_FILE).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:  # noqa: BLE001 - missing/corrupt state is recoverable
            return {}


def _save_state(state: dict) -> None:
    """Persist state atomically so a power loss cannot leave half-written JSON."""
    with _STATE_LOCK:
        target = _data_dir() / _STATE_FILE
        temporary = target.with_suffix(f".{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
            os.replace(temporary, target)
        except Exception:  # noqa: BLE001 - telemetry must never block the app
            logger.debug("could not persist update state", exc_info=True)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _set_runtime(**changes) -> None:
    with _RUNTIME_LOCK:
        _RUNTIME.update(changes)


def _runtime_snapshot() -> dict:
    with _RUNTIME_LOCK:
        return dict(_RUNTIME)


def set_shutdown_callback(callback: Callable[[], None] | None) -> None:
    """Register the launcher's graceful-stop callback.

    The callback must return promptly; the launcher implementation starts its
    cleanup on a separate thread.  Keeping this dependency injected makes the
    update engine independently testable and prevents it from importing GUI or
    server modules.
    """
    global _SHUTDOWN_CALLBACK
    _SHUTDOWN_CALLBACK = callback


def _bundled_root() -> Path | None:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "tuf_root" / "root.json")
    candidates.append(Path(sys.executable).resolve().parent / "tuf_root" / "root.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _bundled_helper() -> Path | None:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "desktop" / _HELPER_NAME)
    candidates.extend(
        [
            Path(sys.executable).resolve().parent / "desktop" / _HELPER_NAME,
            Path(__file__).resolve().with_name(_HELPER_NAME),
        ]
    )
    return next((path for path in candidates if path.is_file()), None)


def _enabled() -> tuple[bool, str]:
    if not getattr(sys, "frozen", False):
        return False, "not a frozen build (dev run)"
    if sys.platform != "win32":
        return False, "smooth self-update currently supports Windows installs"
    if not os.environ.get(UPDATE_URL_ENV):
        return False, f"{UPDATE_URL_ENV} not set"
    try:
        import tufup.client  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"tufup not available: {exc}"
    if _bundled_root() is None:
        return False, "no bundled trusted root.json"
    if _bundled_helper() is None:
        return False, "no bundled update helper"
    return True, "ok"


def _new_stage_dir() -> Path:
    """Create staging beside the install so the final rename is same-volume."""
    install = Path(sys.executable).resolve().parent
    # A power loss during a previous download may leave an unreferenced staging
    # directory. There can be only one operation per process, so exact-prefix
    # siblings are safe to prune before creating this run's unique stage.
    for stale in install.parent.glob(f".{install.name}.update-*"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
    stage = install.parent / f".{install.name}.update-{uuid.uuid4().hex}"
    stage.mkdir(parents=True, exist_ok=False)
    return stage


def _make_client(*, extract_dir: Path | None = None):
    from tufup.client import Client

    base_url = os.environ[UPDATE_URL_ENV].rstrip("/")
    data = _data_dir()
    metadata_dir = data / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    root_dst = metadata_dir / "root.json"
    if not root_dst.exists():
        shutil.copy2(_bundled_root(), root_dst)

    targets_dir = data / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)
    install_dir = Path(sys.executable).resolve().parent

    return Client(
        app_name=APP_NAME,
        app_install_dir=install_dir,
        current_version=__version__,
        metadata_dir=metadata_dir,
        metadata_base_url=f"{base_url}/metadata/",
        target_dir=targets_dir,
        target_base_url=f"{base_url}/targets/",
        extract_dir=extract_dir,
        # A failed metadata refresh must never be indistinguishable from "no
        # update".  tufup otherwise catches network/signature failures and
        # returns None, which made the UI confidently claim it was current.
        # tufup signals a required-refresh failure with SystemExit; the wrapper
        # below converts that library control flow into a normal app error.
        refresh_required=True,
    )


def _check_for_updates(client):
    """Return the newest signed target, making refresh failures explicit.

    tufup 0.10 calls ``sys.exit()`` when ``refresh_required`` is true and TUF
    metadata cannot be downloaded or verified.  Letting that escape a desktop
    worker leaves the progress modal active forever; letting refresh be optional
    reports the same failure as "up to date".  Convert only that documented
    SystemExit boundary and leave ordinary exceptions to the caller.
    """
    try:
        return client.check_for_updates()
    except SystemExit as exc:
        detail = str(exc).strip()
        message = (
            "Signed update metadata could not be downloaded or verified. "
            "Check the connection and update server, then try again."
        )
        if detail:
            message = f"{message} ({detail})"
        raise RuntimeError(message) from exc


def _clear_pending() -> bool:
    """Remove the helper handshake marker with a short bounded retry."""
    try:
        marker = _data_dir() / _PENDING_MARKER
    except Exception:  # noqa: BLE001
        logger.warning("could not locate pending update marker", exc_info=True)
        return False
    for attempt in range(3):
        try:
            marker.unlink(missing_ok=True)
            if not marker.exists():
                return True
        except Exception:  # noqa: BLE001 - failure is reported by the caller
            if attempt == 2:
                logger.warning("could not clear pending update marker", exc_info=True)
        time.sleep(0.05)
    return False


def _cleanup_previous_install() -> None:
    """Delete the rollback directory only after the new app booted correctly."""
    install = Path(sys.executable).resolve().parent
    previous = install.parent / f".{install.name}.previous"
    if previous.exists():
        try:
            shutil.rmtree(previous)
        except Exception:  # noqa: BLE001 - retry on the next healthy launch
            logger.warning("could not remove previous update backup: %s", previous)
    # Helpers live outside the app directory and can safely be pruned here.
    for helper in _data_dir().glob("update-helper-*.ps1"):
        try:
            helper.unlink()
        except OSError:
            pass
    for ready in _data_dir().glob("update-helper-*.ready"):
        try:
            ready.unlink()
        except OSError:
            pass


def _cleanup_after_helper_settles() -> None:
    """Keep rollback files through the helper's final health decision.

    The app deletes the pending marker to report a healthy backend.  At the
    exact timeout boundary the helper may already have observed the old marker
    and begun stopping this process for rollback.  Removing ``.previous`` in
    that narrow window would destroy its recovery source.  The helper's forced
    stop path is bounded below this grace period; on an ordinary healthy launch
    it sees the cleared marker and exits long before cleanup begins.
    """
    time.sleep(_ROLLBACK_SETTLE_SECONDS)
    _cleanup_previous_install()


def mark_started_ok() -> None:
    """Confirm an update only when the marker matches the running version."""
    marker = _data_dir() / _PENDING_MARKER
    if not marker.exists():
        # A user may close the healthy new app during the cleanup grace period.
        # On its next healthy launch, finish pruning the already-confirmed
        # rollback directory instead of leaving a full bundle indefinitely.
        state = _load_state()
        if state.get("last_update_version") == __version__:
            threading.Thread(
                target=_cleanup_previous_install,
                name="update-stale-cleanup",
                daemon=True,
            ).start()
        return
    try:
        applied = marker.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        applied = ""

    state = _load_state()
    if applied and applied == __version__:
        # Marker deletion is the helper's health-confirmation signal. Do not
        # record success or discard rollback files unless that signal really
        # reached disk; the helper will safely roll back on its bounded timeout.
        if not _clear_pending():
            state["last_check_ok"] = False
            state["last_check_error"] = (
                "The new backend became ready, but its update confirmation "
                "marker could not be cleared; rollback protection was kept."
            )
            _save_state(state)
            return
        state["last_update_at"] = _now_iso()
        state["last_update_version"] = applied
        history = state.get("history") or []
        if not history or history[-1].get("version") != applied:
            history.append({"version": applied, "at": state["last_update_at"]})
        state["history"] = history[-20:]
        state["last_available"] = None
        state["last_check_error"] = ""
        logger.info("update %s started cleanly", applied)
        _save_state(state)
        threading.Thread(
            target=_cleanup_after_helper_settles,
            name="update-cleanup",
            daemon=True,
        ).start()
    else:
        state["last_check_ok"] = False
        state["last_check_error"] = (
            f"Update expected {applied or 'an unknown version'}, but "
            f"{__version__} started; the pending marker and rollback install "
            "were kept for safe recovery."
        )
        logger.error(state["last_check_error"])
        # A stale/old process can be opened manually in the short handoff
        # window.  It must not clear the marker or delete .previous while the
        # helper/new process may still need it.  A matching healthy build will
        # confirm and clean it on its own startup.
        _save_state(state)


def get_status_info() -> dict:
    enabled, why = _enabled()
    state = _load_state()
    return {
        "version": __version__,
        "app_name": APP_NAME,
        "enabled": enabled,
        "reason": why,
        "frozen": bool(getattr(sys, "frozen", False)),
        "update_url": os.environ.get(UPDATE_URL_ENV, ""),
        "pending": (_data_dir() / _PENDING_MARKER).exists(),
        "last_check_at": state.get("last_check_at"),
        "last_check_ok": state.get("last_check_ok"),
        "last_check_error": state.get("last_check_error"),
        "last_update_at": state.get("last_update_at"),
        "last_update_version": state.get("last_update_version"),
        "available": state.get("last_available"),
        "history": state.get("history") or [],
        **_runtime_snapshot(),
    }


def check_only() -> dict:
    """Refresh signed metadata without installing or interrupting the till."""
    current = __version__
    if not _OPERATION_LOCK.acquire(blocking=False):
        return {
            "current": current,
            "available": _load_state().get("last_available"),
            "enabled": True,
            "busy": True,
        }

    state = _load_state()
    state["last_check_at"] = _now_iso()
    _set_runtime(phase="checking", message="Checking for a signed update…")
    try:
        enabled, why = _enabled()
        if not enabled:
            state["last_check_ok"] = False
            state["last_check_error"] = why
            state["last_available"] = None
            _save_state(state)
            return {
                "current": current,
                "available": None,
                "enabled": False,
                "reason": why,
            }
        try:
            new_update = _check_for_updates(_make_client())
            available = str(new_update.version) if new_update else None
            state["last_check_ok"] = True
            state["last_check_error"] = ""
            state["last_available"] = available
            _save_state(state)
            return {"current": current, "available": available, "enabled": True}
        except Exception as exc:  # noqa: BLE001
            logger.exception("update check failed")
            state["last_check_ok"] = False
            state["last_check_error"] = str(exc)
            _save_state(state)
            return {
                "current": current,
                "available": None,
                "enabled": True,
                "error": str(exc),
            }
    finally:
        _set_runtime(phase="idle", message="")
        _OPERATION_LOCK.release()


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("powershell.exe") or "powershell.exe"


def _wait_helper_ready(process: subprocess.Popen, ready_path: Path) -> None:
    """Require proof that the WPF helper rendered before closing the live POS."""
    deadline = time.monotonic() + _HELPER_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if ready_path.is_file():
            # Catch an immediate dispatcher/WPF crash after the render event;
            # only a still-live helper is allowed to trigger POS shutdown.
            time.sleep(0.1)
            returncode = process.poll()
            if returncode is not None:
                raise RuntimeError(
                    f"The update window exited during startup (code {returncode})."
                )
            try:
                ready_path.unlink()
            except OSError:
                pass
            return
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(
                f"The update window exited before it was ready (code {returncode})."
            )
        time.sleep(0.05)
    raise RuntimeError(
        "The update window did not become ready in time; Alpha POS was left running."
    )


def _stop_unready_helper(process: subprocess.Popen) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
    except Exception:  # noqa: BLE001 - preserve the original readiness error
        logger.debug("could not stop unready update helper", exc_info=True)


def _launch_swap_helper(src_dir: Path, dst_dir: Path, version: str) -> subprocess.Popen:
    """Launch the visible WPF helper without allocating a console window."""
    helper_source = _bundled_helper()
    if helper_source is None:
        raise RuntimeError("The update helper is missing from this build.")

    data = _data_dir()
    helper_copy = data / f"update-helper-{uuid.uuid4().hex}.ps1"
    shutil.copy2(helper_source, helper_copy)
    ready_path = data / f"update-helper-{uuid.uuid4().hex}.ready"
    log_path = data / "update-helper.log"
    marker_path = data / _PENDING_MARKER
    command = [
        _powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-STA",
        "-File",
        str(helper_copy),
        "-ParentPid",
        str(os.getpid()),
        "-Source",
        str(src_dir),
        "-Destination",
        str(dst_dir),
        "-Version",
        version,
        "-MarkerPath",
        str(marker_path),
        "-LogPath",
        str(log_path),
        "-ReadyPath",
        str(ready_path),
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logger.info("starting windowless update helper for %s", version)
    process = subprocess.Popen(
        command,
        cwd=str(data),
        creationflags=flags,
        close_fds=True,
    )
    try:
        _wait_helper_ready(process, ready_path)
    except Exception:
        _stop_unready_helper(process)
        ready_path.unlink(missing_ok=True)
        try:
            helper_copy.unlink()
        except OSError:
            pass
        raise
    return process


def _write_pending(version: str) -> None:
    marker = _data_dir() / _PENDING_MARKER
    temporary = marker.with_name(f".{marker.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(version, encoding="utf-8")
        last_error: OSError | None = None
        for attempt in range(3):
            try:
                os.replace(temporary, marker)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.05)
        if last_error is not None:
            raise last_error
        if marker.read_text(encoding="utf-8").strip() != version:
            raise RuntimeError("Pending update marker could not be verified on disk.")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _download_progress(*, bytes_downloaded: int, bytes_expected: int) -> None:
    total = max(int(bytes_expected or 0), 0)
    downloaded = max(int(bytes_downloaded or 0), 0)
    percent = min(86, int(downloaded * 86 / total)) if total else 0
    _set_runtime(
        phase="downloading",
        progress=percent,
        message="Downloading the signed update…",
        bytes_downloaded=downloaded,
        bytes_total=total,
    )


def _install_worker() -> None:
    stage: Path | None = None
    helper_started = False
    with _OPERATION_LOCK:
        state = _load_state()
        state["last_check_at"] = _now_iso()
        try:
            enabled, why = _enabled()
            if not enabled:
                raise RuntimeError(why)
            if _SHUTDOWN_CALLBACK is None:
                raise RuntimeError("The launcher is not ready to restart safely.")

            _set_runtime(phase="checking", progress=3, message="Checking signatures…")
            stage = _new_stage_dir()
            client = _make_client(extract_dir=stage)
            new_update = _check_for_updates(client)
            if not new_update:
                state["last_check_ok"] = True
                state["last_check_error"] = ""
                state["last_available"] = None
                _save_state(state)
                _set_runtime(
                    active=False,
                    phase="complete",
                    progress=100,
                    message="Alpha POS is already up to date.",
                    retryable=False,
                )
                return

            version = str(new_update.version)
            state["last_check_ok"] = True
            state["last_check_error"] = ""
            state["last_available"] = version
            _save_state(state)
            _set_runtime(
                target_version=version,
                phase="downloading",
                progress=4,
                message="Downloading the signed update…",
            )

            def install(*, src_dir, dst_dir, **_kwargs):
                nonlocal helper_started
                _set_runtime(
                    phase="installing",
                    progress=94,
                    message="Update verified. Preparing a safe restart…",
                )
                _write_pending(version)
                try:
                    _launch_swap_helper(Path(src_dir), Path(dst_dir), version)
                except Exception:
                    _clear_pending()
                    raise
                helper_started = True
                _set_runtime(
                    active=True,
                    phase="restarting",
                    progress=98,
                    message="Restarting Alpha POS…",
                )
                _SHUTDOWN_CALLBACK()

            client.download_and_apply_update(
                skip_confirmation=True,
                install=install,
                progress_hook=_download_progress,
            )
            if not helper_started:
                raise RuntimeError("The signed update could not be staged for installation.")
        except (Exception, SystemExit) as exc:  # current version must remain usable
            logger.exception("self-update failed; current install was left intact")
            detail = str(exc).strip() or (
                "The signed update process stopped unexpectedly. "
                "The current version was left intact; try again."
            )
            state["last_check_ok"] = False
            state["last_check_error"] = detail
            _save_state(state)
            _clear_pending()
            _set_runtime(
                active=False,
                phase="error",
                message=detail,
                retryable=True,
            )
        finally:
            if stage is not None and stage.exists() and not helper_started:
                shutil.rmtree(stage, ignore_errors=True)


def start_update() -> dict:
    """Start one background update and return immediately to the UI."""
    global _UPDATE_THREAD
    with _RUNTIME_LOCK:
        if _RUNTIME["active"]:
            return {
                "started": False,
                "busy": True,
                "message": "An update is already in progress.",
            }
        _RUNTIME.update(
            active=True,
            phase="checking",
            progress=1,
            message="Checking for a signed update…",
            bytes_downloaded=0,
            bytes_total=0,
            target_version=None,
            retryable=False,
        )
        thread = threading.Thread(
            target=_install_worker,
            name="signed-update",
            daemon=True,
        )
        _UPDATE_THREAD = thread
        try:
            thread.start()
        except Exception as exc:  # noqa: BLE001 - do not strand the modal busy
            _UPDATE_THREAD = None
            detail = str(exc).strip() or "The update worker could not start."
            _RUNTIME.update(
                active=False,
                phase="error",
                message=detail,
                retryable=True,
            )
            logger.exception("could not start signed-update worker")
            return {"started": False, "message": detail, "error": detail}
    return {"started": True, "message": "Update started."}


def check_and_apply() -> bool:
    """Compatibility wrapper; update work is intentionally asynchronous now."""
    return bool(start_update().get("started"))
