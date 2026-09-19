"""Windowless POS backend started by the Alpha POS desktop shell.

    AlphaPOSBackend.exe --parent-pid <shell pid> --ready-file <path>

The shell passes the control-panel token in ``ALPHAPOS_CONTROL_TOKEN``. This
process binds the control server on a free loopback port, publishes the port in
the ready file, boots embedded Postgres + Django + the POS server behind it, and
stops everything within a bounded budget when asked (or when the shell exits).
It never opens a window and never runs the self-updater: the shell owns both.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

logger = logging.getLogger('desktop.backend')

SHUTDOWN_BUDGET_SECONDS = 25.0
# Hard stop if a shutdown step wedges; the shell kills the job at 35 s anyway.
SHUTDOWN_HARD_EXIT_SECONDS = 32.0
# The shell maps this to "Alpha POS is already running" instead of a crash.
EXIT_ALREADY_RUNNING = 2


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='AlphaPOSBackend', add_help=True)
    parser.add_argument('--parent-pid', type=int, default=None)
    parser.add_argument('--ready-file', default=None)
    parser.add_argument('--selftest', action='store_true')
    return parser.parse_args(argv)


def _track_boot_phase(stop_event, *, interval=0.5):
    """Mirror supervisor progress into the lifecycle phase the shell polls."""
    from desktop import app, control_server, lifecycle

    server = control_server._API.server
    while not stop_event.is_set():
        if app._BACKEND_READY.is_set() and server.is_running():
            lifecycle.STATE.set('serving')
        elif getattr(server, '_setup_ready', False):
            lifecycle.STATE.set('migrating', 'starting POS server')
        elif getattr(server, '_setup_error', ''):
            # Setup keeps failing; the supervisor is still retrying.
            lifecycle.STATE.set('error', server._setup_error)
        elif getattr(server, '_django_ready', False):
            lifecycle.STATE.set('migrating')
        elif lifecycle.STATE.snapshot()['phase'] != 'serving':
            lifecycle.STATE.set('database')
        stop_event.wait(interval)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    from desktop import app
    app._configure_boot_logging()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    if args.selftest:
        return app.main_selftest(require_webview=False)

    from desktop import single_instance
    # A quick relaunch can overlap the previous backend, which has up to
    # SHUTDOWN_HARD_EXIT_SECONDS to stop its database. Wait for it instead of
    # failing the new window with "backend exited (code 2)".
    if not single_instance.acquire(
        single_instance.BACKEND_MUTEX_NAME,
        wait_seconds=SHUTDOWN_HARD_EXIT_SECONDS + 8,
    ):
        logger.error('another Alpha POS backend still owns the data directory; exiting')
        return EXIT_ALREADY_RUNNING

    from desktop import control_server, lifecycle, shutdown
    from desktop.version import __version__

    httpd = control_server.serve(preferred_port=0)
    threading.Thread(target=httpd.serve_forever, name='control', daemon=True).start()
    if args.ready_file:
        lifecycle.write_ready_file(args.ready_file, port=control_server.CONTROL_PORT, version=__version__)
    logger.info('backend control server on 127.0.0.1:%s (pid %s)', control_server.CONTROL_PORT, os.getpid())

    stopped = threading.Event()
    phase_stop = threading.Event()

    def stop_everything():
        hard_exit = threading.Timer(SHUTDOWN_HARD_EXIT_SECONDS, lambda: os._exit(3))
        hard_exit.daemon = True
        hard_exit.start()
        app._UPDATE_SHUTDOWN.set()
        phase_stop.set()
        shutdown.stop_backend(budget=SHUTDOWN_BUDGET_SECONDS, context='backend shutdown')
        stopped.set()

    lifecycle.STATE.set_shutdown_handler(stop_everything)
    if args.parent_pid:
        lifecycle.watch_parent(args.parent_pid, lifecycle.STATE.request_shutdown)

    threading.Thread(target=_track_boot_phase, args=(phase_stop,), name='phase', daemon=True).start()
    threading.Thread(
        target=app._boot_worker,
        kwargs={'check_updates': False},
        name='boot',
        daemon=True,
    ).start()

    try:
        while not stopped.wait(0.5):
            pass
    except KeyboardInterrupt:
        lifecycle.STATE.request_shutdown()
        stopped.wait(SHUTDOWN_HARD_EXIT_SECONDS)

    try:
        httpd.shutdown()
        httpd.server_close()
    except Exception:  # noqa: BLE001
        logger.debug('backend: control server close failed', exc_info=True)
    logging.shutdown()
    # Give the shell a moment to read the final /lifecycle phase if it is polling.
    time.sleep(0.1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main() or 0)
