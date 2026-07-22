"""Entry point for the Alpha POS desktop control panel.

    python -m desktop.app          # dev
    (or the packaged AlphaPOS.exe)

Starts the local control server, then shows the panel in a NATIVE window via
pywebview (WebView2 — an embedded rendering control, NOT the Edge browser: no
msedge.exe, no browser chrome). If the native window can't start, it falls back
to a chromeless Edge "--app" window, then the default browser, so the panel
always appears. Closing the window stops the POS server and exits.
"""
from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from desktop import control_server

logger = logging.getLogger('desktop.app')

# Windowless GUI build: spawn children without allocating a console window.
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _configure_boot_logging():
    """Persist failures that happen before Django configures normal logging.

    The packaged executable has no console, so an unreadable .env or embedded
    Postgres failure during the first seconds previously vanished completely.
    Django later takes over with app.log/error.log; this small rotating boot log
    is specifically for the path leading up to django.setup().
    """
    root = logging.getLogger()
    if any(getattr(handler, '_alphapos_boot', False) for handler in root.handlers):
        return
    try:
        from logging.handlers import RotatingFileHandler
        from desktop import config_store
        # On the first boot after Factory Reset this file would lock the logs
        # directory before consume_reset_pending can erase it on Windows.
        if config_store.RESET_FLAG.exists():
            return
        log_dir = config_store.DATA_DIR / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / 'desktop_boot.log', maxBytes=2 * 1024 * 1024,
            backupCount=2, encoding='utf-8',
        )
        handler._alphapos_boot = True
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s [%(process)d] %(message)s',
        ))
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        if root.level > logging.INFO:
            root.setLevel(logging.INFO)
    except Exception:  # noqa: BLE001 — logging must never block first paint
        pass
_UPDATE_SHUTDOWN = threading.Event()
_BACKEND_READY = threading.Event()
_EDGE_PROC = None


def _find_edge() -> str | None:
    candidates = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _profile_dir() -> str:
    # Share config_store's canonical fallback so Startup/manual launches reuse
    # the same browser cache even when LOCALAPPDATA is absent.
    from desktop import config_store
    p = config_store.DATA_DIR / 'edge-profile'
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _selftest():
    """Validate a frozen build loads all modules + the pipeline works, without a
    display. Run: AlphaPOS.exe --selftest"""
    import json
    from desktop.bridge import Api
    api = Api()
    original_fiscal_mode = None
    try:
        state = api.get_state()
        print('get_state :', json.dumps(state)[:80])
        if not state.get('ok'):
            raise RuntimeError(state.get('error') or 'get_state failed')

        setup = api.run_setup()
        print('setup     :', setup.get('ok'))
        if not setup.get('ok'):
            raise RuntimeError(setup.get('error') or 'setup/migrations failed')

        started = api.start_server()
        print('start     :', started.get('running'))
        if not started.get('ok') or not started.get('running'):
            raise RuntimeError(started.get('error') or 'server failed to bind')

        connection = api.test_server_connection()
        print('conn      :', connection.get('status'))
        if not connection.get('ok') or connection.get('status') != 200:
            raise RuntimeError(connection.get('error') or 'health check failed')

        fiscal_status = api.fiscal_status()
        if not fiscal_status.get('ok'):
            raise RuntimeError(fiscal_status.get('error') or 'fiscal status failed')
        original_fiscal_mode = (
            ((fiscal_status.get('fiscal') or {}).get('config') or {}).get('mode')
        )
        fiscal_mode = api.fiscal_set_mode('mock')
        if not fiscal_mode.get('ok'):
            raise RuntimeError(fiscal_mode.get('error') or 'mock fiscal setup failed')
        mock_sync = api.send_mock_sync()
        print('mock sync :', mock_sync.get('read_back'))
        if not mock_sync.get('ok') or not mock_sync.get('read_back'):
            raise RuntimeError(mock_sync.get('error') or 'mock sync round-trip failed')

        fiscal = api.fiscal_test()
        print('fiscal    :', fiscal.get('fiscal_sign'))
        if not fiscal.get('ok') or not fiscal.get('fiscal_sign'):
            raise RuntimeError(fiscal.get('error') or 'mock fiscalization failed')

        try:
            import webview  # noqa: F401 — confirms the native-GUI backend bundled
            print('webview   : importable (native window available)')
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f'native GUI backend missing: {exc}') from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception('desktop selftest failed')
        print('SELFTEST FAILED:', exc)
        return 1
    finally:
        if original_fiscal_mode and original_fiscal_mode != 'mock':
            api.fiscal_set_mode(original_fiscal_mode)
        api.stop_server()
    print('SELFTEST OK')
    return 0


def _run_pywebview(url: str) -> bool:
    """Native window via pywebview/WebView2. Returns True if it ran (and the
    window has since closed), False if the backend is unavailable so the caller
    can fall back. Blocks until the window is closed."""
    try:
        import webview
    except Exception:  # noqa: BLE001 — not bundled / import error
        logger.info('pywebview not available; falling back')
        return False
    try:
        webview.create_window('Alpha POS', url, width=1060, height=760,
                              min_size=(900, 640))
        # Blocks until the window closes. Raises if WebView2 can't initialize.
        webview.start()
        return True
    except Exception:  # noqa: BLE001 — WebView2 runtime missing / init failed
        logger.exception('pywebview window failed; falling back to Edge/browser')
        return False


def _run_edge(url: str) -> bool:
    """Chromeless Edge "--app" window. Returns True if launched (and has since
    closed), False if Edge isn't present."""
    edge = _find_edge()
    if not edge:
        return False
    global _EDGE_PROC
    proc = subprocess.Popen([
        edge, f'--app={url}', f'--user-data-dir={_profile_dir()}',
        '--no-first-run', '--no-default-browser-check', '--window-size=1040,740',
    ], creationflags=_NO_WINDOW)
    _EDGE_PROC = proc
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if _EDGE_PROC is proc:
            _EDGE_PROC = None
    return True


def _close_edge_fallback():
    """Close the Edge --app child before an updater relaunch reuses its profile."""
    global _EDGE_PROC
    proc = _EDGE_PROC
    _EDGE_PROC = None
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            logger.warning('Edge fallback did not exit during update shutdown')
    except Exception:  # noqa: BLE001
        logger.exception('could not close Edge fallback during update shutdown')


def _autostart_backend():
    """Bring the POS server up automatically on launch and keep it up.

    Runs in the background so the panel appears immediately. Does the (idempotent)
    first-run install, starts the server, and supervises it forever — retrying
    with backoff if a start fails and restarting it if it dies. This is what
    makes every boot/login come up serving with no button press.
    """
    api = control_server._API
    setup_ok = False
    audit_started = False
    backoff = 3
    while not _UPDATE_SHUTDOWN.is_set():
        # Never bind the POS against a schema whose migration failed. Retry the
        # idempotent setup with backoff; a later transient DB recovery can still
        # bring the app online without an operator restart.
        if not setup_ok:
            try:
                setup_result = api.run_setup()  # migrate + bootstrap admin + collectstatic
                # Bridge methods return structured errors through @_safe rather
                # than raising. Treat that exactly like an exception; otherwise
                # a failed migration would still be marked setup_ok and bind.
                if not setup_result.get('ok'):
                    raise RuntimeError(
                        setup_result.get('error') or 'desktop setup failed'
                    )
                setup_ok = True
                backoff = 3
            except Exception:  # noqa: BLE001
                logger.exception('autostart: first-run setup failed; backend remains offline')
                _UPDATE_SHUTDOWN.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
        # Models and audit tables are safe to query only after migrations have
        # completed. Keep this diagnostic non-fatal and retry on the next
        # watchdog loop if startup races a transient database problem.
        if setup_ok and not audit_started:
            try:
                from desktop import order_audit
                order_audit.start_background_collector()
                audit_started = True
            except Exception:  # noqa: BLE001 - diagnostics must never block POS
                logger.exception('autostart: local order audit collector failed to start')
        try:
            if api.server.wants_running() and not api.server.is_running():
                # Crash recovery must not override an operator's explicit Stop.
                res = api.server.start(automatic=True)
                if res.get('running'):
                    logger.info('autostart: POS server up — LAN %s', api.server.url())
                    if setup_ok:
                        _BACKEND_READY.set()
                    backoff = 3
                else:
                    logger.error('autostart: start failed: %s', res.get('error'))
                    _UPDATE_SHUTDOWN.wait(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
            elif api.server.is_running():
                if setup_ok:
                    _BACKEND_READY.set()
                # Independent watchdog: if both daemons ever exit, the server
                # supervisor still notices and resurrects them.
                api.server.ensure_background_workers()
        except Exception:  # noqa: BLE001 — never let the supervisor die
            logger.exception('autostart: start raised')
            _UPDATE_SHUTDOWN.wait(backoff)
            backoff = min(backoff * 2, 60)
            continue
        # Wake immediately for an update so the watchdog cannot restart uvicorn
        # while the launcher is releasing its files.
        _UPDATE_SHUTDOWN.wait(5)


def _confirm_update_start_when_ready(*, ready_event=None, shutdown_event=None,
                                     updater_module=None):
    """Clear the update's pending marker only after a real backend bind.

    This runs independently from metadata refresh. If migrations, config, the
    database, or uvicorn never become healthy, the marker deliberately remains
    for the updater's recovery policy instead of blessing a broken release just
    because its control-panel window painted.
    """
    ready_event = ready_event or _BACKEND_READY
    shutdown_event = shutdown_event or _UPDATE_SHUTDOWN
    while not shutdown_event.is_set():
        if ready_event.wait(0.5):
            if updater_module is None:
                from desktop import updater as updater_module
            updater_module.mark_started_ok()
            logger.info('update launch confirmed after POS backend became ready')
            return True
    return False


def _graceful_update_shutdown(httpd):
    """Release app-owned resources before the external helper swaps files."""
    if _UPDATE_SHUTDOWN.is_set():
        return
    _UPDATE_SHUTDOWN.set()

    def stop_everything():
        # Bound shutdown too: the helper has its own 45-second parent wait, and
        # neither side is allowed to retry a locked application forever.
        force_exit = threading.Timer(20.0, lambda: os._exit(0))
        force_exit.daemon = True
        force_exit.start()
        try:
            from desktop import order_audit, support_tunnel
            support_tunnel.stop(timeout=5)
            order_audit.stop_background_collector(timeout=8)
        except Exception:  # noqa: BLE001
            logger.exception('update shutdown: evidence/support workers stop failed')
        try:
            control_server._API.stop_server()
        except Exception:  # noqa: BLE001
            logger.exception('update shutdown: POS server stop failed')
        try:
            from django.db import connections
            connections.close_all()
        except Exception:  # noqa: BLE001
            logger.debug('update shutdown: Django connection close failed', exc_info=True)
        try:
            from desktop import pg_embedded
            pg_embedded.stop()
        except Exception:  # noqa: BLE001
            logger.exception('update shutdown: embedded Postgres stop failed')
        _close_edge_fallback()
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:  # noqa: BLE001
            logger.debug('update shutdown: panel server close failed', exc_info=True)
        logging.shutdown()
        os._exit(0)

    threading.Thread(
        target=stop_everything,
        name='update-shutdown',
        daemon=True,
    ).start()


def _boot_worker(*, shutdown_event=None):
    """Bring the heavy backend up BEHIND the already-painted panel: finish any
    armed factory reset, start embedded Postgres, load config env, supervise the
    POS server, then run a DEFERRED self-update check. None of this is on the
    first-paint path, so the window appears instantly and the panel's existing
    status poller shows 'starting database / server…' until it's ready."""
    shutdown_event = shutdown_event or _UPDATE_SHUTDOWN
    # One serialized boundary owns env/reset -> verified PostgreSQL -> Django.
    # Early UI diagnostics use the same method, so they can never win a race and
    # permanently configure settings against fallback SQLite. A transient .env
    # sharing race or PostgreSQL startup failure must not strand the till offline
    # for the rest of the day: retry this idempotent boundary with bounded
    # backoff, while keeping the already-painted diagnostics panel responsive.
    backoff = 3
    while not shutdown_event.is_set():
        try:
            from desktop import pg_embedded, support_tunnel
            control_server._API.server.ensure_django()
            break
        except Exception:  # noqa: BLE001
            logger.exception(
                'boot: database/Django bootstrap failed; retrying in %ss',
                backoff,
            )
            if shutdown_event.wait(backoff):
                return
            backoff = min(backoff * 2, 60)
    else:
        return

    atexit.register(pg_embedded.stop)
    try:
        support_tunnel.start()
        atexit.register(support_tunnel.stop)
    except Exception:  # noqa: BLE001
        # Support is optional and owns its own reconnect supervisor. It must
        # never prevent checkout from starting after the database is healthy.
        logger.exception('boot: support tunnel worker could not start')

    # Start + supervise the POS server (its own infinite watchdog loop) on its own
    # thread so this worker can move on to the deferred update check.
    threading.Thread(target=_autostart_backend, name='autostart', daemon=True).start()

    # Confirm an applied update only after the autostart thread reports a real
    # uvicorn bind. Metadata refresh is independent and may happen meanwhile.
    if '--no-update' not in sys.argv:
        try:
            from desktop import updater
            threading.Thread(
                target=_confirm_update_start_when_ready,
                kwargs={'updater_module': updater},
                name='update-start-confirmer', daemon=True,
            ).start()
            updater.check_only()
        except Exception:  # noqa: BLE001
            logger.exception('boot: self-update check failed; continuing')


def main():
    _configure_boot_logging()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    # 1) SINGLE-INSTANCE LOCK FIRST — before any embedded-Postgres / data-dir work.
    #    A second launch must never touch pgdata or open a second window; it
    #    focuses the running panel and exits (no second uvicorn/PG/window race).
    from desktop import single_instance
    url = f'http://{control_server.CONTROL_HOST}:{control_server.CONTROL_PORT}/'
    if not single_instance.acquire():
        # If the first instance had to fall back from 8765 because another app
        # owns it, blindly opening the preferred URL would display that unrelated
        # (potentially hostile) service. Focus only after the distinctive local
        # health marker proves this exact endpoint is Alpha POS. During the tiny
        # first-process startup race it is safer to exit and leave its opening
        # window alone than to browse an unverified loopback service.
        if control_server._our_panel_at(
            control_server.CONTROL_HOST, control_server.CONTROL_PORT,
        ):
            logger.info('another AlphaPOS instance is already running — focusing it')
            if not _run_pywebview(url) and not _run_edge(url):
                webbrowser.open(url)
        else:
            logger.info(
                'another AlphaPOS instance owns the mutex; preferred panel '
                'endpoint is not verified, so no window was opened',
            )
        return

    # --selftest brings the backend up synchronously (no window).
    if '--selftest' in sys.argv:
        try:
            from desktop import config_store, pg_embedded
            config_store.apply_env_to_process()
            pg_embedded.start()
            atexit.register(pg_embedded.stop)
        except Exception:  # noqa: BLE001
            logger.exception('selftest backend bootstrap failed')
            print('SELFTEST FAILED: backend bootstrap failed')
            return 1
        return _selftest()

    # 2) Bind the lightweight control-panel server and PAINT THE WINDOW IMMEDIATELY.
    #    The heavy backend (embedded Postgres + the POS uvicorn server) boots on a
    #    worker behind it; serve() auto-falls-back to a free port if 8765 is squatted.
    try:
        httpd = control_server.serve()
    except control_server.AlreadyRunning:
        # Port held though our mutex said we're sole (a stale owner): focus + exit.
        if not _run_pywebview(url) and not _run_edge(url):
            webbrowser.open(url)
        return

    # serve() may have bound a free fallback port — rebuild the URL from it.
    url = f'http://{control_server.CONTROL_HOST}:{control_server.CONTROL_PORT}/'
    threading.Thread(target=httpd.serve_forever, name='control', daemon=True).start()

    # The update engine asks the launcher to close uvicorn, Django, Postgres and
    # the panel socket. Only then does its out-of-process helper replace files.
    from desktop import updater
    updater.set_shutdown_callback(lambda: _graceful_update_shutdown(httpd))

    # 3) Boot the backend (env/reset → PG → POS server → update check) off paint path.
    threading.Thread(target=_boot_worker, name='boot', daemon=True).start()

    # 4) FIRST PAINT — nothing slow upstream. Prefer the native window; fall back so
    #    the panel ALWAYS appears.
    forced_browser = '--browser' in sys.argv
    shown = False
    if not forced_browser:
        shown = _run_pywebview(url) or _run_edge(url)
    if not shown:
        webbrowser.open(url)
        print(f'Opened {url} in the default browser. Close this window to exit.')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    # Window closed → stop the POS server + embedded Postgres and exit.
    try:
        from desktop import order_audit, support_tunnel
        support_tunnel.stop()
        order_audit.stop_background_collector(timeout=8)
    except Exception:  # noqa: BLE001
        pass
    try:
        control_server._API.stop_server()
    except Exception:  # noqa: BLE001
        pass
    try:
        from desktop import pg_embedded
        pg_embedded.stop()
    except Exception:  # noqa: BLE001
        pass
    httpd.shutdown()
    sys.exit(0)


if __name__ == '__main__':
    raise SystemExit(main() or 0)
