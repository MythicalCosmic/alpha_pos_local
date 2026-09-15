"""Bounded, ordered backend shutdown.

Order matters for updates: nothing may still run from the install directory when
the process exits. The POS server and optional workers stop first (in
parallel), database connections close, and embedded Postgres always gets the
last and largest share of the budget. The previous update path armed a 20 s
``os._exit`` before Postgres had stopped, which orphaned ``postgres.exe`` and
locked the install folder.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger('desktop.shutdown')

# Seconds reserved for ``pg_ctl stop`` out of the total budget.
POSTGRES_RESERVE_SECONDS = 12.0


def _run_bounded(name, target, timeout):
    """Run ``target`` on a daemon thread; return (finished, error)."""
    outcome = {'error': None}

    def run():
        try:
            target()
        except Exception as exc:  # noqa: BLE001 - shutdown continues regardless
            outcome['error'] = exc
            logger.exception('shutdown step %s failed', name)

    thread = threading.Thread(target=run, name=f'shutdown-{name}', daemon=True)
    thread.start()
    thread.join(timeout=max(0.0, timeout))
    finished = not thread.is_alive()
    if not finished:
        logger.warning('shutdown step %s still running after %.1fs', name, timeout)
    return finished, outcome['error']


def stop_backend(*, budget=25.0, context='shutdown', steps=None, clock=time.monotonic):
    """Stop the backend within ``budget`` seconds and report what finished.

    ``steps`` lets tests replace the real actions; each is a zero-argument
    callable keyed by ``optional_workers``, ``pos_server``, ``db_connections``
    and ``postgres``.
    """
    steps = steps or _default_steps(context)
    started = clock()
    deadline = started + float(budget)
    # A small budget must still leave the earlier steps real time to finish.
    reserve = min(POSTGRES_RESERVE_SECONDS, float(budget) / 2)

    def remaining(reserve=0.0):
        return max(0.0, deadline - clock() - reserve)

    report = {}

    # Optional workers (support tunnel, audit, Telegram) stop alongside the POS
    # server instead of before it, so their slow network joins cannot eat the
    # time Postgres needs.
    workers = threading.Thread(
        target=lambda: report.__setitem__(
            'optional_workers',
            _run_bounded('optional-workers', steps['optional_workers'], remaining(reserve)),
        ),
        name='shutdown-workers-wait',
        daemon=True,
    )
    workers.start()
    report['pos_server'] = _run_bounded('pos-server', steps['pos_server'], remaining(reserve))
    workers.join(timeout=remaining(reserve))
    report.setdefault('optional_workers', (False, None))

    report['db_connections'] = _run_bounded('db-connections', steps['db_connections'], min(2.0, remaining()))
    report['postgres'] = _run_bounded('postgres', steps['postgres'], remaining())

    result = {
        name: {'finished': finished, 'error': str(error) if error else ''}
        for name, (finished, error) in report.items()
    }
    result['elapsed_s'] = round(clock() - started, 2)
    result['postgres_stopped'] = result['postgres']['finished'] and not result['postgres']['error']
    logger.info('%s finished in %.2fs (postgres stopped: %s)', context, result['elapsed_s'], result['postgres_stopped'])
    return result


def _default_steps(context):
    def optional_workers():
        from desktop import app
        app._stop_optional_workers(context=context, support_timeout=5, process_shutdown=True)

    def pos_server():
        from desktop import control_server
        control_server._API.stop_server()

    def db_connections():
        from django.db import connections
        connections.close_all()

    def postgres():
        from desktop import pg_embedded
        pg_embedded.stop()

    return {
        'optional_workers': optional_workers,
        'pos_server': pos_server,
        'db_connections': db_connections,
        'postgres': postgres,
    }
