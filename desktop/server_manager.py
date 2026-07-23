"""Runs the Django POS server in-process via waitress, in a background thread.

Keeping the server in the same process as the GUI means one .exe, no child
python to ship, and the control panel can call Django services directly for the
self-tests. Start/stop is controlled by the big button in the UI.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger('desktop.server')

# A recovered hub must be retried before its 95-second device-presence lease can
# expire. The transport already performs bounded request retries; allowing the
# scheduler to add a 15-minute backoff made a short restart look like a dead till
# long after the hub was healthy again.
_SYNC_RECOVERY_DELAY_MAX_S = 60


def _setup_signature_and_schema_current():
    """Return the release/migration fingerprint and live DB migration health.

    The former shortcut trusted only desktop_state.json. If PostgreSQL was
    replaced or emptied independently, that file survived and migrations were
    skipped against a blank database. MigrationExecutor reuses one loader for
    both the fingerprint and a read-only migration plan; an empty plan is the
    authoritative low-overhead signal that the selected database is current.
    """
    import hashlib
    try:
        from desktop.version import __version__ as version
    except Exception:  # noqa: BLE001
        version = '0'

    migration_hash = 'nohash'
    schema_current = False
    try:
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        keys = sorted(
            f'{app}.{name}' for app, name in executor.loader.disk_migrations.keys()
        )
        migration_hash = hashlib.sha1(
            '\n'.join(keys).encode('utf-8'),
        ).hexdigest()[:12]
        targets = executor.loader.graph.leaf_nodes()
        schema_current = not bool(executor.migration_plan(targets))
    except Exception:  # noqa: BLE001
        # Unknown/unreadable schema is never safe to skip. migrate will provide
        # the actionable error through the normal setup path.
        logger.exception('could not verify applied database migrations')
    return f'{version}:{migration_hash}', schema_current


class ServerManager:
    def __init__(self):
        self._server = None
        self._thread = None
        self._django_ready = False
        self._last_error = ''
        # Bind to every interface so the whole LAN (other monoblocks /
        # cashier terminals) can reach the POS, not just this machine.
        self.host = '0.0.0.0'
        self.port = 8000
        self._django_lock = threading.RLock()
        # ``django.setup()`` only builds the model registry; it does not make an
        # upgraded database safe to query. The control-panel UI paints before
        # the backend and issues model-backed status calls immediately, so every
        # public Django boundary must also wait for migrations and required
        # bootstrap steps to complete.
        self._setup_lock = threading.RLock()
        self._setup_ready = False
        self._lifecycle_lock = threading.RLock()
        self._worker_lock = threading.RLock()
        self._desired_running = True
        self._sync_thread = None
        self._sync_stop_event = threading.Event()
        self._pull_thread = None
        self._pull_stop_event = threading.Event()
        self._hb_thread = None
        self._hb_stop_event = threading.Event()
        self._worker_state = {
            'heartbeat': self._new_worker_state(),
            'sync': self._new_worker_state(),
            'pull': self._new_worker_state(),
        }
        self._lan_ip_value = '127.0.0.1'
        # ``time.monotonic()`` may still be under 30 seconds just after Windows
        # boots. None makes the first status call probe unconditionally instead
        # of incorrectly returning loopback for that entire initial window.
        self._lan_ip_checked_at = None

    @staticmethod
    def _new_worker_state():
        return {
            'last_attempt_at': None,
            'last_success_at': None,
            'consecutive_failures': 0,
            'last_status': None,
            'last_error': '',
            'next_run_in_s': None,
        }

    @staticmethod
    def _utc_now():
        return datetime.now(timezone.utc).isoformat()

    def _record_worker(self, name, **values):
        with self._worker_lock:
            self._worker_state[name].update(values)

    # -- Automatic license heartbeat ----------------------------------------
    def _ensure_heartbeat_worker(self):
        """Phone home to the control center every LICENSE_HEARTBEAT_INTERVAL so
        the license/billing verdict (active/suspended/expired) stays fresh
        without the operator clicking. Self-gates: do_heartbeat() is a no-op
        when no control-center URL is configured (offline-activated installs)."""
        with self._worker_lock:
            if not self._desired_running:
                return
            if self._hb_thread is not None and self._hb_thread.is_alive():
                return
            self._hb_stop_event = threading.Event()
            self._hb_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(self._hb_stop_event,),
                name='license-heartbeat', daemon=True,
            )
            self._hb_thread.start()
            logger.info('heartbeat worker started')

    def _heartbeat_loop(self, stop_event=None):
        """Resilient heartbeat scheduler with bounded adaptive backoff.

        ``do_heartbeat`` reports network/HTTP failures as return statuses rather
        than exceptions. The previous loop ignored those results, so there was
        no observable failure counter or backoff. An Event makes shutdown
        immediate instead of sleeping one second at a time.
        """
        stop_event = stop_event or self._hb_stop_event
        delay = 5
        failures = 0
        while not stop_event.wait(delay):
            attempted = self._utc_now()
            self._record_worker(
                'heartbeat', last_attempt_at=attempted, next_run_in_s=None,
            )
            try:
                from django.conf import settings as dj
                interval = max(
                    30, int(getattr(dj, 'LICENSE_HEARTBEAT_INTERVAL', 300) or 300),
                )
                schedule = tuple(
                    min(3600, max(5, int(v))) for v in
                    (getattr(dj, 'LICENSE_BACKOFF_SCHEDULE_S', ()) or ())
                ) or (60, 300, 900)
                try:
                    from licensing.services.heartbeat import do_heartbeat
                    body, status = do_heartbeat()
                finally:
                    from django.db import close_old_connections
                    close_old_connections()

                if status in (200, 304):
                    failures = 0
                    delay = interval
                    self._record_worker(
                        'heartbeat', last_success_at=self._utc_now(),
                        consecutive_failures=0, last_status=status,
                        last_error='', next_run_in_s=delay,
                    )
                    logger.debug('heartbeat completed with status %s', status)
                else:
                    failures += 1
                    # A failure schedule is intentionally allowed to retry sooner
                    # than the normal heartbeat interval (e.g. 60s vs 300s).
                    # Taking max(interval, retry) suppressed exactly that recovery.
                    delay = schedule[min(failures - 1, len(schedule) - 1)]
                    error = str((body or {}).get('message') or f'HTTP {status}')[:300]
                    self._record_worker(
                        'heartbeat', consecutive_failures=failures,
                        last_status=status, last_error=error,
                        next_run_in_s=delay,
                    )
                    logger.warning(
                        'heartbeat failed (status=%s, failures=%s); retry in %ss: %s',
                        status, failures, delay, error,
                    )
            except Exception as exc:  # noqa: BLE001 — never kill the scheduler
                failures += 1
                delay = min(3600, max(30, 30 * (2 ** min(failures - 1, 6))))
                self._record_worker(
                    'heartbeat', consecutive_failures=failures,
                    last_status='exception', last_error=str(exc)[:300],
                    next_run_in_s=delay,
                )
                logger.exception(
                    'heartbeat iteration failed; retrying in %ss', delay,
                )

    # -- Automatic background sync ------------------------------------------
    def _ensure_sync_worker(self):
        """Start outbound sync without letting a slow upload starve pulls."""
        with self._worker_lock:
            if not self._desired_running:
                return
            if self._sync_thread is not None and self._sync_thread.is_alive():
                return
            self._sync_stop_event = threading.Event()
            self._sync_thread = threading.Thread(
                target=self._sync_loop,
                args=(self._sync_stop_event,),
                name='sync-worker', daemon=True,
            )
            self._sync_thread.start()
            logger.info('sync worker started')

    def _ensure_pull_worker(self):
        """Start the inbound sync/presence clock independently of uploads."""
        with self._worker_lock:
            if not self._desired_running:
                return
            if self._pull_thread is not None and self._pull_thread.is_alive():
                return
            self._pull_stop_event = threading.Event()
            self._pull_thread = threading.Thread(
                target=self._pull_loop,
                args=(self._pull_stop_event,),
                name='sync-pull-worker', daemon=True,
            )
            self._pull_thread.start()
            logger.info('sync pull worker started')

    @staticmethod
    def _sync_busy(result, leg):
        """Whether another caller is already making progress on this leg."""
        message = str((result or {}).get('message') or '').strip().lower()
        return message == f'{leg} already in progress'

    @staticmethod
    def _sync_retry_delay(retry, failures):
        return min(
            _SYNC_RECOVERY_DELAY_MAX_S,
            max(10, int(retry)) * (2 ** min(failures - 1, 4)),
        )

    def _sync_loop(self, stop_event=None):
        stop_event = stop_event or self._sync_stop_event
        delay = 2
        failures = 0
        while not stop_event.wait(delay):
            self._record_worker(
                'sync', last_attempt_at=self._utc_now(), next_run_in_s=None,
            )
            try:
                self._ensure_heartbeat_worker()
                from django.db import close_old_connections
                from base.services.sync.config import (
                    SyncConfig, get_sync_interval, is_local_mode,
                    get_cloud_url, get_sync_retry_interval,
                )
                from base.services.sync.service import SyncService
                from desktop import shift_close_sync
                interval = max(10, get_sync_interval())
                try:
                    if SyncConfig.is_enabled() and is_local_mode() and get_cloud_url():
                        close_tracker_error = ''
                        try:
                            # Rebuild/retain any exact close bundle whose generic
                            # per-model queue records were already accepted while
                            # the cloud was still waiting for sibling evidence.
                            shift_close_sync.prepare_for_push()
                        except Exception as exc:  # noqa: BLE001
                            close_tracker_error = str(exc)[:300]
                            logger.exception(
                                'could not prepare durable shift-close acknowledgement',
                            )
                        push = SyncService.push()
                        close_status = None
                        try:
                            # A successful model batch is not proof that the full
                            # immutable close bundle arrived. Only the dedicated
                            # cloud verifier may clear the desktop PENDING state.
                            close_status = shift_close_sync.after_push(push)
                        except Exception as exc:  # noqa: BLE001
                            close_tracker_error = str(exc)[:300]
                            logger.exception(
                                'could not verify cloud shift-close acknowledgement',
                            )
                        if push.get('success'):
                            if close_tracker_error:
                                failures += 1
                                delay = min(interval, 10)
                                self._record_worker(
                                    'sync', consecutive_failures=failures,
                                    last_status='close_tracker_error',
                                    last_error=(
                                        'Shift close acknowledgement could not be '
                                        f'verified: {close_tracker_error}'
                                    ),
                                    next_run_in_s=delay,
                                )
                            elif close_status and not close_status.get('clear'):
                                failures = 0
                                delay = min(interval, 10)
                                state = str(close_status.get('state') or 'PENDING').lower()
                                self._record_worker(
                                    'sync', consecutive_failures=0,
                                    last_status=f'close_{state}',
                                    last_error=str(close_status.get('message') or '')[:300],
                                    next_run_in_s=delay,
                                )
                            else:
                                failures = 0
                                delay = interval
                                self._record_worker(
                                    'sync', last_success_at=self._utc_now(),
                                    consecutive_failures=0, last_status='ok',
                                    last_error='', next_run_in_s=delay,
                                )
                        elif self._sync_busy(push, 'push'):
                            failures = 0
                            delay = interval
                            self._record_worker(
                                'sync', consecutive_failures=0,
                                last_status='busy', last_error='',
                                next_run_in_s=delay,
                            )
                        else:
                            failures += 1
                            delay = self._sync_retry_delay(
                                get_sync_retry_interval(), failures,
                            )
                            error = str(
                                push.get('message') or push.get('errors')
                                or 'sync failed'
                            )[:300]
                            self._record_worker(
                                'sync', consecutive_failures=failures,
                                last_status='failed', last_error=error,
                                next_run_in_s=delay,
                            )
                            logger.warning(
                                'background sync failed (%s consecutive); '
                                'retry in %ss: %s', failures, delay, error,
                            )
                    else:
                        failures = 0
                        delay = interval
                        self._record_worker(
                            'sync', consecutive_failures=0,
                            last_status='disabled', last_error='',
                            next_run_in_s=delay,
                        )
                finally:
                    close_old_connections()
            except Exception as exc:  # noqa: BLE001 — never kill the scheduler
                failures += 1
                delay = min(
                    _SYNC_RECOVERY_DELAY_MAX_S,
                    30 * (2 ** min(failures - 1, 5)),
                )
                self._record_worker(
                    'sync', consecutive_failures=failures,
                    last_status='exception', last_error=str(exc)[:300],
                    next_run_in_s=delay,
                )
                logger.exception('sync iteration failed; retrying in %ss', delay)

    def _pull_loop(self, stop_event=None):
        """Pull changes and refresh presence independently of upload backlog."""
        stop_event = stop_event or self._pull_stop_event
        delay = 2
        failures = 0
        while not stop_event.wait(delay):
            self._record_worker(
                'pull', last_attempt_at=self._utc_now(), next_run_in_s=None,
            )
            try:
                from django.db import close_old_connections
                from base.services.sync.config import (
                    SyncConfig, get_sync_interval, is_local_mode,
                    get_pull_enabled, get_cloud_url, get_sync_retry_interval,
                )
                from base.services.sync.service import SyncService
                # A pull is also the idle till's presence heartbeat. Keep its
                # normal cadence inside the cloud's 95-second presence lease,
                # even if an operator configures uploads less frequently.
                interval = min(
                    _SYNC_RECOVERY_DELAY_MAX_S,
                    max(10, get_sync_interval()),
                )
                try:
                    enabled = (
                        SyncConfig.is_enabled() and is_local_mode()
                        and get_cloud_url() and get_pull_enabled()
                    )
                    if enabled:
                        pull = SyncService.pull_from_cloud()
                        if pull.get('success'):
                            failures = 0
                            delay = interval
                            self._record_worker(
                                'pull', last_success_at=self._utc_now(),
                                consecutive_failures=0, last_status='ok',
                                last_error='', next_run_in_s=delay,
                            )
                        elif self._sync_busy(pull, 'pull'):
                            # A concurrent manual pull is already refreshing the
                            # feed/presence, so lock contention is not an outage.
                            failures = 0
                            delay = interval
                            self._record_worker(
                                'pull', consecutive_failures=0,
                                last_status='busy', last_error='',
                                next_run_in_s=delay,
                            )
                        else:
                            failures += 1
                            delay = self._sync_retry_delay(
                                get_sync_retry_interval(), failures,
                            )
                            error = str(
                                pull.get('message') or pull.get('errors')
                                or 'pull failed'
                            )[:300]
                            self._record_worker(
                                'pull', consecutive_failures=failures,
                                last_status='failed', last_error=error,
                                next_run_in_s=delay,
                            )
                            logger.warning(
                                'background pull failed (%s consecutive); '
                                'retry in %ss: %s', failures, delay, error,
                            )
                    else:
                        failures = 0
                        delay = interval
                        self._record_worker(
                            'pull', consecutive_failures=0,
                            last_status='disabled', last_error='',
                            next_run_in_s=delay,
                        )
                finally:
                    close_old_connections()
            except Exception as exc:  # noqa: BLE001 - never kill the scheduler
                failures += 1
                delay = min(
                    _SYNC_RECOVERY_DELAY_MAX_S,
                    30 * (2 ** min(failures - 1, 5)),
                )
                self._record_worker(
                    'pull', consecutive_failures=failures,
                    last_status='exception', last_error=str(exc)[:300],
                    next_run_in_s=delay,
                )
                logger.exception('pull iteration failed; retrying in %ss', delay)

    def ensure_background_workers(self):
        """Watchdog entrypoint used by the launcher supervisor."""
        if self.is_running() and self.wants_running():
            try:
                from desktop import shift_close_sync
                shift_close_sync.ensure_started()
            except Exception:  # noqa: BLE001 - never prevent the POS from serving
                logger.exception('could not start shift-close acknowledgement tracker')
            self._ensure_heartbeat_worker()
            self._ensure_sync_worker()
            self._ensure_pull_worker()

    # -- Django bootstrap (idempotent) --------------------------------------
    def _ensure_django_bootstrapped(self):
        """Load Django against verified PostgreSQL without claiming schema readiness."""
        if self._django_ready:
            return
        # The boot worker and a fast operator click can arrive here together.
        # Serialize env loading + django.setup so neither thread observes a
        # half-populated settings registry or creates competing secret files.
        with self._django_lock:
            if self._django_ready:
                return
            import os
            from desktop import config_store, pg_embedded
            config_store.apply_env_to_process()
            # UI status calls can arrive before the launcher's boot worker. The
            # database decision must therefore live inside this same serialized
            # Django bootstrap boundary: env -> verified PG -> django.setup.
            # Otherwise the first diagnostic call permanently configures Django
            # against fallback SQLite and the real orders appear missing.
            pg_embedded.start()
            self.port = int(os.environ.get('PORT', '8000') or 8000)

            import django
            django.setup()
            self._django_ready = True

    def ensure_django(self, log=lambda m: None):
        """Return only when Django and the installed schema are ready.

        A fast UI poll and the boot worker can arrive concurrently on an
        upgraded install. Exactly one performs the required setup while every
        other model-touching caller waits on the same lock. A failed setup does
        not publish readiness, so the boot watchdog can retry safely.
        """
        with self._setup_lock:
            if self._setup_ready:
                return
            self._setup_ready = False
            self._run_first_time_install(log=log)
            self._setup_ready = True

    @staticmethod
    def run_management_command(command, *args, log=None, **options):
        """Run a Django command safely from the windowed desktop process.

        PyInstaller's Windows GUI subsystem intentionally leaves
        ``sys.stdout`` and ``sys.stderr`` as ``None``. Django's
        ``BaseCommand`` otherwise wraps those missing streams and crashes as
        soon as a command writes progress output. Supplying real text streams
        at this boundary keeps every desktop-invoked command console-agnostic
        and gives setup output a durable home in the application log.
        """
        from django.core.management import call_command

        stdout = io.StringIO()
        stderr = io.StringIO()
        options['stdout'] = stdout
        options['stderr'] = stderr
        try:
            return call_command(command, *args, **options)
        finally:
            for stream_name, stream, logger_method in (
                ('stdout', stdout, logger.info),
                ('stderr', stderr, logger.warning),
            ):
                for line in stream.getvalue().splitlines():
                    if not line.strip():
                        continue
                    message = f'  [{command}] {line}'
                    logger_method(
                        'management command %s %s: %s',
                        command,
                        stream_name,
                        line,
                    )
                    if log is not None:
                        try:
                            log(message)
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                'management command output callback failed',
                            )

    def first_time_install(self, log=lambda m: None):
        """Force a live setup check, including after a database rebuild."""
        with self._setup_lock:
            self._setup_ready = False
            self._run_first_time_install(log=log)
            self._setup_ready = True

    def _run_first_time_install(self, log=lambda m: None):
        """Run migrations, bootstrap the admin, and collect static — the
        'install everything on first run' step. Gated by a setup signature
        (app version + a hash of the on-disk migration graph) persisted in
        desktop_state.json, so a warm launch with nothing new SKIPS the
        multi-second migrate / seed_templates / collectstatic entirely. The
        signature changes whenever a migration is added (any release), so a
        post-update launch always re-runs migrate — it can never be skipped
        when the schema actually changed. Safe to re-run."""
        self._ensure_django_bootstrapped()
        from desktop import config_store
        sig, schema_current = _setup_signature_and_schema_current()
        signature_matches = config_store.read_state().get('setup_sig') == sig
        if signature_matches and schema_current:
            log('Setup already current — skipping migrate/seed/collectstatic.')
            return
        if signature_matches:
            log('Saved setup signature matches, but database schema is stale/unknown; repairing.')
        log('Applying database migrations…')
        self.run_management_command(
            'migrate', '--noinput', verbosity=0, log=log,
        )
        log('Creating admin account (if missing)…')
        try:
            from desktop import config_store
            from base.models import User
            # On a fresh DB we choose the admin password ourselves and persist it,
            # so the panel can show it — the GUI exe has no console where
            # bootstrap_admin's banner would otherwise print it.
            if not User.objects.exists():
                email = 'admin@local'
                password = config_store.generate_password()
                self.run_management_command(
                    'bootstrap_admin', email=email, password=password,
                    verbosity=0, log=log,
                )
                config_store.write_admin_creds(email, password)
                log(f'  Admin created — email: {email}  (password shown in the panel)')
            else:
                self.run_management_command(
                    'bootstrap_admin', verbosity=0, log=log,
                )
        except Exception as exc:  # noqa: BLE001
            log(f'  bootstrap_admin failed: {exc}')
            # Required invariant: never persist setup_sig without a usable admin.
            raise
        log('Seeding notification templates…')
        try:
            # Idempotent (get_or_create) — without this the templates table is
            # empty and automatic Telegram notifications silently no-op.
            self.run_management_command(
                'seed_templates', verbosity=0, log=log,
            )
        except Exception as exc:  # noqa: BLE001
            log(f'  seed_templates failed: {exc}')
            # Automatic Telegram notifications depend on these rows. Retrying
            # next launch is safer than blessing a permanently half-set-up till.
            raise
        log('Collecting static files…')
        try:
            self.run_management_command(
                'collectstatic', '--noinput', verbosity=0, log=log,
            )
        except Exception as exc:  # noqa: BLE001
            log(f'  (collectstatic skipped: {exc})')
        log('Setup complete.')
        # Persist the signature so the next launch with nothing new skips all of
        # the above. Only reached after migrate succeeded (it's unguarded above),
        # so a failed migrate never writes the marker and is retried next launch.
        try:
            config_store.update_state({'setup_sig': sig})
        except Exception as exc:  # noqa: BLE001
            log(f'  (could not persist setup marker: {exc})')

    # -- Server lifecycle ----------------------------------------------------
    def is_running(self):
        return bool(
            self._thread is not None
            and self._thread.is_alive()
            and self._server is not None
            and getattr(self._server, 'started', False)
        )

    def wants_running(self):
        with self._lifecycle_lock:
            return self._desired_running

    def _run_server(self, server):
        try:
            server.run()
        except BaseException as exc:  # uvicorn raises SystemExit on bind errors
            self._last_error = str(exc) or exc.__class__.__name__
            logger.exception('uvicorn server thread exited with an error')
        finally:
            if self._desired_running and not getattr(server, 'should_exit', False):
                logger.error('POS server stopped unexpectedly; supervisor will restart it')

    def start(self, *, automatic=False):
        """Start once and return only after uvicorn has actually bound.

        ``automatic`` is used by the crash supervisor and never overrides an
        operator's explicit Stop. The old implementation returned success as
        soon as the thread was spawned; bind failures happened later on that
        thread and the UI falsely displayed Online.
        """
        with self._lifecycle_lock:
            if automatic and not self._desired_running:
                return {'running': False, 'message': 'Server intentionally stopped'}
            if not automatic:
                self._desired_running = True
            if self.is_running():
                self.ensure_background_workers()
                return {'running': True, 'message': 'Server already running'}
            if self._thread is not None and self._thread.is_alive():
                return {'running': False, 'message': 'Server is still starting or stopping'}
            try:
                self.ensure_django()
                import os
                import uvicorn

                cfg = uvicorn.Config(
                    'config.asgi:application', host=self.host, port=int(self.port),
                    log_level='info', lifespan='off', access_log=False,
                    # The windowed executable has no stderr for Uvicorn's
                    # terminal-aware formatter to inspect. AlphaPOS installs a
                    # rotating root FileHandler before starting the server, so
                    # leave logger configuration untouched and let
                    # ``uvicorn.*`` records propagate into that durable log.
                    log_config=None,
                )
                server = uvicorn.Server(cfg)
                server.install_signal_handlers = lambda: None
                thread = threading.Thread(
                    target=self._run_server, args=(server,),
                    name='uvicorn', daemon=True,
                )
                self._server = server
                self._thread = thread
                self._last_error = ''
                thread.start()

                try:
                    timeout = max(2.0, float(os.environ.get(
                        'DESKTOP_SERVER_START_TIMEOUT', '15',
                    )))
                except ValueError:
                    timeout = 15.0
                deadline = time.monotonic() + min(timeout, 60.0)
                while thread.is_alive() and not getattr(server, 'started', False):
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
                if not getattr(server, 'started', False):
                    server.should_exit = True
                    thread.join(timeout=1.0)
                    error = self._last_error or (
                        f'POS server did not bind {self.host}:{self.port} within '
                        f'{timeout:g} seconds'
                    )
                    self._last_error = error
                    logger.error('server start failed: %s', error)
                    return {'running': False, 'error': error}

                self.ensure_background_workers()
                logger.info(
                    'POS server bound on 0.0.0.0:%s — reachable on the LAN at %s',
                    self.port, self.url(),
                )
                return {
                    'running': True, 'url': self.url(), 'lan_url': self.url(),
                    'lan_ip': self.lan_ip(), 'message': 'Server started',
                }
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.exception('server start failed')
                return {'running': False, 'error': str(exc)}

    def stop(self, *, worker_timeout=3.0):
        with self._lifecycle_lock:
            self._desired_running = False
            self._hb_stop_event.set()
            self._sync_stop_event.set()
            self._pull_stop_event.set()
            # Give idle workers an immediate Event-driven exit and bound the
            # wait for an in-flight HTTP call. Destructive reset callers can
            # request a longer timeout; ordinary Stop stays responsive.
            deadline = time.monotonic() + max(0.0, float(worker_timeout))
            for worker in (self._sync_thread, self._pull_thread, self._hb_thread):
                if worker is not None and worker.is_alive():
                    worker.join(timeout=max(0.0, deadline - time.monotonic()))
            workers_quiescent = not any(
                worker is not None and worker.is_alive()
                for worker in (self._sync_thread, self._pull_thread, self._hb_thread)
            )
            if not workers_quiescent:
                logger.warning(
                    'background workers still finishing after %.1fs stop timeout',
                    worker_timeout,
                )
            server, thread = self._server, self._thread
            if server is not None:
                try:
                    server.should_exit = True
                except Exception:  # noqa: BLE001
                    logger.exception('server close failed')
            if thread is not None and thread.is_alive():
                thread.join(timeout=8.0)
            if thread is None or not thread.is_alive():
                self._server = None
                self._thread = None
            self._record_worker(
                'heartbeat', next_run_in_s=None, last_status='stopped',
            )
            self._record_worker('sync', next_run_in_s=None, last_status='stopped')
            self._record_worker('pull', next_run_in_s=None, last_status='stopped')
            return {
                'running': False, 'message': 'Server stopped',
                'workers_quiescent': workers_quiescent,
            }

    def lan_ip(self, *, force=False):
        """This machine's primary LAN IP — the address other devices use to
        reach the POS. Cached briefly because the panel polls status frequently;
        route discovery on every poll was unnecessary work on slow/offline PCs."""
        now = time.monotonic()
        if (not force and self._lan_ip_checked_at is not None
                and now - self._lan_ip_checked_at < 30):
            return self._lan_ip_value
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No packets are actually sent; this just selects the outbound
            # interface so getsockname() returns the real LAN IP.
            s.settimeout(0.25)
            s.connect(('8.8.8.8', 80))
            value = s.getsockname()[0]
        except Exception:  # noqa: BLE001
            # Restaurants often run a valid isolated LAN with no internet/default
            # route. Hostname adapter enumeration still exposes the till's private
            # address, which is far more useful than advertising loopback.
            import ipaddress
            candidates = []
            try:
                candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
                candidates.extend(
                    item[4][0] for item in socket.getaddrinfo(
                        socket.gethostname(), None, socket.AF_INET,
                    )
                )
            except OSError:
                pass
            usable = []
            for candidate in dict.fromkeys(candidates):
                try:
                    address = ipaddress.ip_address(candidate)
                except ValueError:
                    continue
                if address.version == 4 and not address.is_loopback:
                    usable.append(address)
            private = next((address for address in usable if address.is_private), None)
            value = str(private or (usable[0] if usable else '127.0.0.1'))
        finally:
            s.close()
        self._lan_ip_value = value
        self._lan_ip_checked_at = now
        return value

    def url(self):
        # The address OTHER devices use — the LAN IP, not the 0.0.0.0 bind addr.
        return f'http://{self.lan_ip()}:{self.port}'

    def status(self):
        with self._worker_lock:
            threads = {
                'heartbeat': self._hb_thread,
                'sync': self._sync_thread,
                'pull': self._pull_thread,
            }
            workers = {
                name: {
                    **state,
                    'alive': bool(
                        threads[name] and threads[name].is_alive()
                    ),
                }
                for name, state in self._worker_state.items()
            }
        if self.is_running():
            phase = 'running'
        elif self._thread is not None and self._thread.is_alive():
            phase = 'starting' if self._desired_running else 'stopping'
        else:
            phase = 'stopped'
        try:
            from desktop import config_store
            environment = config_store.env_status()
        except Exception as exc:  # noqa: BLE001
            environment = {'loaded': False, 'error': str(exc)}
        try:
            from desktop import pg_embedded
            database = pg_embedded.migration_status()
        except Exception as exc:  # noqa: BLE001
            database = {'warning': '', 'error': str(exc)}
        return {
            'running': self.is_running(),
            'phase': phase,
            'desired_running': self._desired_running,
            'url': self.url(),
            'lan_ip': self.lan_ip(),
            'port': self.port,
            'django_ready': self._django_ready,
            'last_error': self._last_error,
            'workers': workers,
            'environment': environment,
            'database': database,
        }
