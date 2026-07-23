"""The js_api bridge exposed to the GUI. Every method returns a JSON-friendly
dict and never raises (the UI shows {ok: false, error} instead of crashing the
window). Django services are imported lazily — after ensure_django()."""
from __future__ import annotations

import logging
import uuid as uuid_mod

from desktop import config_store
from desktop.server_manager import ServerManager

logger = logging.getLogger('desktop.bridge')


def _safe(fn):
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except Exception as exc:  # noqa: BLE001
            logger.exception('bridge %s failed', fn.__name__)
            return {'ok': False, 'error': str(exc)}
    wrapper.__name__ = fn.__name__
    return wrapper


def _sync_response(result, *, operation):
    """Translate a SyncService result into the bridge's public contract.

    SyncService reports operational failures inside its result dictionary.  A
    successful Python call therefore does not necessarily mean that anything
    reached the peer.  Keep that distinction at the bridge boundary so the UI
    never displays a false success toast.
    """
    result = result if isinstance(result, dict) else {}
    ok = result.get('success') is True and not result.get('errors')
    response = {'ok': ok, 'result': result}
    if not ok:
        detail = result.get('error') or result.get('message')
        if not detail and result.get('errors'):
            detail = '; '.join(str(item) for item in result['errors'])
        response['error'] = detail or f'{operation} failed'
    return response


def _attach_shift_close_status(response, close_status):
    """Never report a manual sync as finished while a close is unresolved."""
    close_status = close_status if isinstance(close_status, dict) else {
        'state': 'CONFLICT', 'clear': False, 'pending_count': 0,
        'conflict_count': 1,
        'message': 'Shift close acknowledgement status is unavailable.',
    }
    response['shift_close'] = close_status
    if not close_status.get('clear'):
        response['ok'] = False
        prefix = (
            'Shift close conflict'
            if close_status.get('conflict_count')
            else 'Shift close still awaiting cloud acknowledgement'
        )
        detail = str(close_status.get('message') or '').strip()
        response.setdefault('error', f'{prefix}: {detail}' if detail else prefix)
    return response


def _shift_close_tracker_failure(module, exc):
    """Return a visible fail-closed status without suppressing the real push."""
    try:
        status = module.get_status()
    except Exception:  # noqa: BLE001
        status = {}
    status = dict(status or {})
    status.update({
        'state': 'CONFLICT',
        'clear': False,
        'conflict_count': max(1, int(status.get('conflict_count') or 0)),
        'message': f'Shift close acknowledgement tracker failed: {str(exc)[:300]}',
    })
    return status


class Api:
    def __init__(self):
        self.server = ServerManager()

    # -- first run / config --------------------------------------------------
    @_safe
    def get_state(self):
        return {'ok': True, 'tos_accepted': config_store.tos_accepted(),
                'server': self.server.status()}

    @_safe
    def accept_tos(self):
        config_store.accept_tos()
        return {'ok': True}

    @_safe
    def get_ui_prefs(self):
        """Panel look preferences (theme direction, accent, language) persisted
        across launches in desktop_state.json."""
        return {'ok': True, 'prefs': (config_store.read_state().get('ui') or {})}

    @_safe
    def set_ui_prefs(self, prefs=None):
        def merge(state):
            state['ui'] = {**(state.get('ui') or {}), **(prefs or {})}
            return state
        state = config_store.update_state(merge)
        return {'ok': True, 'prefs': state['ui']}

    @_safe
    def get_config(self):
        cfg = config_store.read_config()
        # Mask secrets for display (operator can overwrite; blank = unchanged).
        masked = dict(cfg)
        for k in config_store.SECRET_KEYS:
            if masked.get(k):
                masked[k] = '••••••••'
        return {'ok': True, 'config': masked, 'secret_keys': sorted(config_store.SECRET_KEYS)}

    @_safe
    def save_config(self, values):
        # Don't overwrite a secret with the mask placeholder.
        current = config_store.read_config()
        clean = {}
        for k, v in (values or {}).items():
            if k in config_store.SECRET_KEYS and v in ('••••••••', None, ''):
                clean[k] = current.get(k, '')
            else:
                clean[k] = v
        config_store.write_config(clean)
        if any(str(key).startswith('SUPPORT_TUNNEL_') for key in clean):
            try:
                from desktop import support_tunnel
                support_tunnel.restart()
            except Exception:  # noqa: BLE001
                logger.exception('live support tunnel config apply failed')
        try:
            self.server.ensure_django()
            # Fiscal mode is a live cache toggle — applies without a restart.
            from fiscalization.config import FiscalConfig
            mode = clean.get('FISCALIZATION_MODE')
            if mode:
                FiscalConfig.set_mode(mode)
            # Telegram token + chat ids go into the DB-backed NotificationSettings
            # (the canonical source TelegramAPI reads) so messages deliver
            # immediately — no restart, unlike the .env-only settings.
            token = clean.get('TELEGRAM_BOT_TOKEN')
            chat_raw = clean.get('TELEGRAM_CHAT_IDS')
            if (token and token != '••••••••') or chat_raw is not None:
                from notifications.models import NotificationSettings
                ns = NotificationSettings.load()
                if token and token != '••••••••':
                    ns.bot_token = token.strip()
                if chat_raw is not None:
                    ns.chat_ids = [c.strip() for c in str(chat_raw)
                                   .replace(' ', ',').split(',') if c.strip()]
                ns.save()
            # Sync settings are read from `settings` at call time, so apply them
            # to the live settings object — no app restart needed to test sync.
            from django.conf import settings as _dj
            for key in ('CLOUD_SYNC_URL', 'CLOUD_SYNC_TOKEN', 'BRANCH_ID',
                        'DEPLOYMENT_MODE', 'LICENSE_CONTROL_CENTER_URL'):
                if key in clean and clean[key] is not None:
                    setattr(_dj, key, clean[key])
            if 'SYNC_ENABLED' in clean:
                from base.services.sync.config import SyncConfig
                en = str(clean['SYNC_ENABLED']).lower() in ('true', '1', 'yes')
                _dj.SYNC_ENABLED = en
                SyncConfig.enable() if en else SyncConfig.disable()
        except Exception:  # noqa: BLE001
            logger.exception('live config apply failed')
        return {'ok': True, 'restart_required': self.server.is_running()}

    # -- config export / import (backup + clone an install) -----------------
    @_safe
    def export_config(self):
        """Download the current configuration as a JSON blob the operator can
        re-import on another PC. Secrets are masked (never exported in clear);
        they must be re-entered on the target."""
        cfg = config_store.read_config()
        masked = dict(cfg)
        for k in config_store.SECRET_KEYS:
            if masked.get(k):
                masked[k] = '••••••••'
        branch = (cfg.get('BRANCH_ID') or 'branch').strip() or 'branch'
        return {'ok': True, 'config': masked,
                'filename': f'alpha-pos-config-{branch}.json'}

    @_safe
    def import_config(self, data=None):
        """Apply a previously-exported config JSON. Only recognised CONFIG_FIELDS
        are taken; a masked secret (••••) is treated as 'keep current' so an
        import never blanks a secret the operator didn't actually re-enter."""
        if not isinstance(data, dict):
            return {'ok': False, 'error': 'Expected a config object'}
        # Some browsers hand us {"config": {...}} — unwrap it.
        if 'config' in data:
            if not isinstance(data['config'], dict):
                return {'ok': False, 'error': 'Expected config to be an object'}
            data = data['config']
        current = config_store.read_config()
        known = {k for k, _ in config_store.CONFIG_FIELDS}
        clean = {}
        for k, v in data.items():
            if k not in known:
                continue
            if k in config_store.SECRET_KEYS and v in ('••••••••', None, ''):
                clean[k] = current.get(k, '')
            else:
                clean[k] = v
        if not clean:
            return {'ok': False, 'error': 'No recognised settings in the file'}
        config_store.write_config(clean)
        if any(str(key).startswith('SUPPORT_TUNNEL_') for key in clean):
            try:
                from desktop import support_tunnel
                support_tunnel.restart()
            except Exception:  # noqa: BLE001
                logger.exception('imported support tunnel config apply failed')
        return {'ok': True, 'imported': sorted(clean),
                'restart_required': self.server.is_running()}

    # -- notifications: per-chat message routing ----------------------------
    @_safe
    def notif_routing(self):
        """Every configured Telegram chat with its label + which message
        categories it receives, so the panel can render the master-detail
        recipients screen. A chat missing from chat_routing defaults to ON for
        every category."""
        self.server.ensure_django()
        from notifications.models import NotificationSettings, ROUTABLE_TYPES
        ns = NotificationSettings.load()
        recipients = [{
            'cid': str(c),
            'label': ((ns.chat_routing or {}).get(str(c), {}) or {}).get('label', ''),
            'events': ns.routing_for(c),
        } for c in (ns.chat_ids or [])]
        return {'ok': True, 'types': list(ROUTABLE_TYPES), 'recipients': recipients}

    @_safe
    def set_notif_routing(self, recipients=None):
        """Persist the recipient list + per-chat routing. `recipients` is a list
        of {cid, label, events:{type:bool}}; this becomes the chat_ids set and
        the chat_routing map in one write."""
        self.server.ensure_django()
        from notifications.models import NotificationSettings, ROUTABLE_TYPES
        ns = NotificationSettings.load()
        chat_ids, routing = [], {}
        for r in (recipients or []):
            cid = str((r or {}).get('cid', '')).strip()
            if not cid:
                continue
            chat_ids.append(cid)
            events = (r.get('events') or {})
            routing[cid] = {
                'label': str(r.get('label', '') or ''),
                'events': {tp: bool(events.get(tp, True)) for tp in ROUTABLE_TYPES},
            }
        ns.chat_ids = chat_ids
        ns.chat_routing = routing
        ns.save()  # save() pins pk=1 and clears the cached singleton
        return {'ok': True, 'count': len(chat_ids)}

    @_safe
    def send_test_to_chat(self, chat_id):
        """Send a one-off test message to a single chat id (the recipient
        detail 'send to this chat' button)."""
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        ok, err = TelegramAPI.send_message(
            '✅ Alpha POS test — this chat is wired up correctly.',
            chat_ids=[str(chat_id)])
        return {'ok': bool(ok), 'error': err}

    @_safe
    def notif_catalog(self):
        """The real catalogue of messages this install can send over Telegram,
        built from the live NotificationTemplate rows (the actual layouts) plus
        the routing bucket each maps to. Lets the panel document exactly what
        traffic an install produces — order alerts, shift/daily reports,
        HR & document reminders, the customer-facing bot replies, and the
        system/sync catch-all — instead of a hard-coded list."""
        self.server.ensure_django()
        from notifications.models import (
            NotificationTemplate, ROUTABLE_TYPES, bucket_for)
        # Family = notification_type prefix, in display order. Anything that
        # doesn't match a prefix lands in 'system' (the catch-all bucket that
        # also carries background sync / fiscal / license alerts).
        families = (('orders', 'order.'), ('shifts', 'shift.'),
                    ('hr', 'hr.'), ('bot', 'telegram.'))

        def family_of(nt):
            for key, prefix in families:
                if nt.startswith(prefix):
                    return key
            return 'system'

        grouped = {key: [] for key, _ in families}
        grouped['system'] = []
        rows = list(NotificationTemplate.objects.all())
        for tpl in rows:
            nt = tpl.notification_type
            grouped[family_of(nt)].append({
                'type': nt,
                'name': tpl.name,
                'enabled': bool(tpl.is_enabled),
                'bucket': bucket_for(nt),
            })
        order = ('orders', 'shifts', 'hr', 'system', 'bot')
        groups = [{'key': key, 'items': grouped.get(key, [])} for key in order]
        return {'ok': True, 'types': list(ROUTABLE_TYPES),
                'count': len(rows), 'groups': groups}

    # -- install + server lifecycle -----------------------------------------
    @_safe
    def run_setup(self):
        logs = []
        self.server.first_time_install(log=logs.append)
        return {'ok': True, 'logs': logs}

    @_safe
    def start_server(self):
        return {'ok': True, **self.server.start()}

    @_safe
    def stop_server(self):
        return {'ok': True, **self.server.stop()}

    @_safe
    def flush_database(self, confirm=False):
        """Wipe ALL data (orders, products, users, shifts, …) and rebuild a clean
        empty database, KEEPING the install config + secrets. Restarts the
        backend in place — one click, no app restart. The admin login is
        recreated (new password shown in the panel)."""
        if confirm is not True:
            return {'ok': False, 'error': 'Confirmation required'}
        import sys
        if not getattr(sys, 'frozen', False):
            return {'ok': False,
                    'error': 'Database flush only runs in the installed app.'}
        try:
            stopped = self.server.stop(worker_timeout=35)
            if not stopped.get('workers_quiescent', False):
                return {
                    'ok': False,
                    'error': 'A background sync is still finishing. Wait a moment and retry.',
                }
        except Exception:  # noqa: BLE001
            logger.exception('stop during flush failed')
            return {'ok': False, 'error': 'Could not stop the database safely.'}
        try:
            from django.db import connections
            connections.close_all()
        except Exception:  # noqa: BLE001
            pass
        # Wipe the DATA but KEEP config: stop embedded Postgres, delete its data
        # cluster (+ any legacy sqlite), then bring a fresh EMPTY cluster back up.
        # The old code deleted only db.sqlite3 — a no-op on the Postgres build, so it
        # wiped NOTHING while reporting success (orders/products/users/admin creds all
        # survived). .env / secrets / logs / media are kept so the install stays
        # configured; the schema is rebuilt by first_time_install below.
        import shutil
        try:
            from desktop import pg_embedded
            if not pg_embedded.stop():
                return {
                    'ok': False,
                    'error': 'Embedded database is still running; flush cancelled safely.',
                }
        except Exception:  # noqa: BLE001
            logger.exception('embedded Postgres stop during flush failed')
            return {'ok': False, 'error': 'Could not stop the embedded database safely.'}
        # The operator explicitly requested a new empty database. Prevent an old
        # pre-canonical cluster from being imported after canonical pgdata is
        # removed, and authorize start() to initialize the empty replacement.
        try:
            config_store._write_protected(
                config_store.LEGACY_PG_MIGRATION_MARKER, 'factory-reset\n',
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception('could not arm PostgreSQL flush marker')
            return {'ok': False, 'error': f'Could not prepare database flush: {exc}'}
        for _name in ('db.sqlite3', 'db.sqlite3-wal', 'db.sqlite3-shm'):
            try:
                (config_store.DATA_DIR / _name).unlink(missing_ok=True)
            except OSError:
                pass
        shutil.rmtree(config_store.DATA_DIR / 'pgdata', ignore_errors=True)
        try:
            from desktop import pg_embedded
            if not pg_embedded.start():   # re-initialises a fresh empty cluster
                return {
                    'ok': False,
                    'error': 'Embedded database is not available; rebuild cancelled.',
                }
        except Exception as exc:  # noqa: BLE001
            logger.exception('embedded Postgres restart during flush failed')
            return {
                'ok': False,
                'error': f'Embedded database restart failed; rebuild cancelled: {exc}',
            }
        # setup_sig describes the old cluster. Keeping it would make
        # first_time_install() skip migrations on this brand-new empty database.
        try:
            def clear_setup_signature(state):
                state.pop('setup_sig', None)
                return state
            config_store.update_state(clear_setup_signature)
        except Exception as exc:  # noqa: BLE001
            logger.exception('could not clear setup signature during flush')
            return {'ok': False, 'error': f'Could not prepare schema rebuild: {exc}'}
        # Rebuild empty schema + reseed (payment methods, templates) + admin.
        try:
            self.server.first_time_install()
        except Exception as exc:  # noqa: BLE001
            logger.exception('rebuild after flush failed')
            return {'ok': False, 'error': f'Rebuild failed: {exc}'}
        try:
            started = self.server.start()
            if not started.get('running'):
                return {
                    'ok': False,
                    'error': started.get('error') or 'Server failed to restart after rebuild.',
                }
        except Exception as exc:  # noqa: BLE001
            logger.exception('start after flush failed')
            return {'ok': False, 'error': f'Server failed to restart after rebuild: {exc}'}
        return {'ok': True,
                'message': 'Database flushed — clean data, same configuration. '
                           'The admin login was reset (see the Dashboard).'}

    @_safe
    def factory_reset(self, confirm=False):
        """Delete the entire install — database, settings, secrets, logs, media
        — so the operator can start over with a clean first install. Requires
        an explicit confirm flag from the UI dialog."""
        if confirm is not True:
            return {'ok': False, 'error': 'Confirmation required'}
        # Guard: in a source checkout DATA_DIR is the project root, so the wipe
        # would delete the repo. Only allow it in the packaged (frozen) app.
        import sys
        if not getattr(sys, 'frozen', False):
            return {'ok': False,
                    'error': 'Factory reset only runs in the installed app.'}
        # Stop the POS server and drop DB connections so the sqlite file isn't
        # locked when we delete it.
        try:
            stopped = self.server.stop(worker_timeout=35)
            if not stopped.get('workers_quiescent', False):
                return {
                    'ok': False,
                    'error': 'A background sync is still finishing. Wait a moment and retry.',
                }
        except Exception:  # noqa: BLE001
            logger.exception('stop during factory reset failed')
            return {'ok': False, 'error': 'Could not stop the database safely.'}
        try:
            from desktop import support_tunnel
            if not support_tunnel.stop(timeout=8):
                return {'ok': False, 'error': 'Support tunnel is still stopping.'}
        except Exception:  # noqa: BLE001
            logger.exception('support tunnel stop during factory reset failed')
            return {'ok': False, 'error': 'Could not stop support tunnel safely.'}
        # The audit collector owns its own thread-local Django connection and
        # can append/recreate evidence independently of uvicorn. It must be
        # fully joined before the destructive wipe can be considered complete.
        try:
            from desktop import order_audit
            if not order_audit.stop_background_collector(timeout=35):
                return {
                    'ok': False,
                    'error': 'Order audit is still finishing. Wait a moment and retry.',
                }
        except Exception:  # noqa: BLE001
            logger.exception('order audit stop during factory reset failed')
            return {'ok': False, 'error': 'Could not stop order audit safely.'}
        try:
            from django.db import connections
            connections.close_all()
        except Exception:  # noqa: BLE001
            pass
        result = config_store.factory_reset()
        return {
            'ok': True,
            'removed': result.get('removed', []),
            'message': 'All data deleted. Close and reopen Alpha POS to set it '
                       'up fresh.',
        }

    @_safe
    def server_status(self):
        return {'ok': True, **self.server.status()}

    @_safe
    def support_tunnel_status(self):
        from desktop import support_tunnel
        return {'ok': True, **support_tunnel.status()}

    @_safe
    def set_support_tunnel_enabled(self, on):
        """Persist and immediately apply the restricted support-tunnel switch."""
        from desktop import support_tunnel
        return {'ok': True, **support_tunnel.set_enabled(bool(on))}

    @_safe
    def test_server_connection(self):
        import urllib.request
        if not self.server.is_running():
            return {'ok': False, 'error': 'Server is not running'}
        # Probe the local bind directly. The advertised LAN URL can be blocked by
        # Windows hairpin/firewall rules even while uvicorn is perfectly healthy.
        url = f'http://127.0.0.1:{self.server.port}/healthz'
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode('utf-8', 'replace')
        return {'ok': resp.status == 200, 'status': resp.status, 'body': body[:50]}

    # -- self-update --------------------------------------------------------
    def _ensure_update_env(self):
        """Mirror the authoritative persisted update URL into this process.

        The panel can be used before the boot worker applies the full env.  A
        stale/injected parent variable must not win in that window, and clearing
        or changing the configured URL must take effect without a restart.
        ``read_config`` is lightweight and merges the canonical file over the
        packaged default without importing Django.
        """
        import os
        key = 'ALPHA_POS_UPDATE_URL'
        url = str(config_store.read_config().get(key, '') or '').strip()
        if url:
            os.environ[key] = url
        else:
            os.environ.pop(key, None)

    @_safe
    def update_status(self):
        """Full update state for the Updates page: installed version, whether
        updates are enabled, the configured server, pending state, and the
        recorded last-check / last-update / available-version / history."""
        self._ensure_update_env()
        from desktop import updater
        return {'ok': True, **updater.get_status_info()}

    @_safe
    def check_updates_only(self):
        """Ask the server whether a newer version exists WITHOUT installing it,
        so the page can show 'up to date' or offer an install."""
        self._ensure_update_env()
        from desktop import updater
        return {'ok': True, **updater.check_only()}

    @_safe
    def check_updates_now(self):
        """Start the signed download in the background and return immediately.

        Progress is exposed by update_status().  Once verification completes,
        the launcher gracefully stops the backend and the windowless helper
        performs a bounded atomic swap + relaunch.
        """
        self._ensure_update_env()
        from desktop import updater
        result = updater.start_update()
        return {'ok': True, **result}

    # -- dashboards ----------------------------------------------------------
    @_safe
    def license_status(self):
        self.server.ensure_django()
        from django.conf import settings as _dj
        from licensing.models import License
        lic = License.load()
        return {'ok': True, 'license': {
            'status': lic.status,
            'org_name': getattr(lic, 'org_name', ''),
            'plan': getattr(lic, 'plan_name', '') or '',
            'email': getattr(lic, 'email', ''),
            'expires_at': lic.expires_at.isoformat() if lic.expires_at else None,
            'last_heartbeat_at': lic.last_heartbeat_at.isoformat() if lic.last_heartbeat_at else None,
            'balance': str(lic.balance) if getattr(lic, 'balance', None) is not None else None,
            'days_remaining': getattr(lic, 'days_remaining', None),
            'warn': bool(getattr(lic, 'warn', False)),
            'last_message': getattr(lic, 'last_message', ''),
            'control_center_url': (getattr(_dj, 'LICENSE_CONTROL_CENTER_URL', '') or ''),
        }}

    @_safe
    def sync_status(self):
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        from desktop import shift_close_sync
        shift_close_sync.ensure_started()
        sync = SyncService.get_status()
        sync['shift_close'] = shift_close_sync.get_status()
        return {'ok': True, 'sync': sync}

    @_safe
    def send_mock_sync(self):
        """Loopback: push a temp record through the receive pipeline, read it
        back, then remove it. Proves the sync machinery end-to-end with no
        cloud server. Leaves no junk behind."""
        self.server.ensure_django()
        from django.conf import settings
        from base.services.sync.receiver import CloudReceiver
        from base.models import Customer
        # Customer is deliberately branch-owned. Catalog entities such as
        # Category are globally pulled/cloud-owned and the receiver must refuse
        # a branch write to them, even when it comes from this diagnostic.
        branch = getattr(settings, 'BRANCH_ID', 'main') or 'main'
        u = str(uuid_mod.uuid4())
        record = {'uuid': u, 'sync_version': 1, 'is_deleted': False,
                  'name': 'ALPHA POS SYNC SELFTEST', 'phone_number': '',
                  'branch_id': branch}
        result = CloudReceiver.receive_batch('customer', branch, [record])
        readback = Customer.objects.filter(uuid=u).first()
        roundtrip_ok = bool(
            result.get('success') is True
            and result.get('created') == 1
            and result.get('updated') == 0
            and result.get('skipped') == 0
            and not result.get('errors')
            and readback is not None
            and str(readback.uuid) == u
            and readback.branch_id == branch
            and readback.name == record['name']
            and readback.sync_version == record['sync_version']
            and readback.is_deleted is False
        )
        if readback:
            # This is diagnostic scratch data, not a real local deletion. The
            # model's hard_delete path correctly publishes a sync tombstone, so
            # invoking it here would leave fake outbound work after a supposedly
            # side-effect-free loopback test. QuerySet.delete performs the direct
            # cleanup without calling the model override.
            Customer.objects.filter(pk=readback.pk).delete()
        response = {'ok': roundtrip_ok, 'model': 'customer', 'sent': record,
                    'received': {
                        'success': result.get('success'),
                        'created': result.get('created'),
                        'updated': result.get('updated'),
                        'skipped': result.get('skipped'),
                        'errors': result.get('errors'),
                    }, 'read_back': roundtrip_ok}
        if not roundtrip_ok:
            response['error'] = 'mock customer sync did not round-trip exactly'
        return response

    @_safe
    def fetch_mock_sync(self):
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        from base.models import Category
        rows = SyncService.get_unsynced(Category)
        return {'ok': True, 'unsynced_categories': len(rows), 'sample': rows[:3]}

    # -- cloud sync (this branch <-> the cloud hub) --------------------------
    @_safe
    def cloud_status(self):
        """Sync config + whether the cloud hub is reachable right now."""
        self.server.ensure_django()
        from base.services.sync.config import SyncConfig, get_cloud_url
        from base.services.sync import transport
        cfg = SyncConfig.get_status()
        reachable = bool(get_cloud_url()) and transport.check_health()
        return {'ok': True, 'config': cfg, 'reachable': reachable}

    @_safe
    def cloud_test_connection(self):
        """Ping the cloud hub's /health over the configured CLOUD_SYNC_URL."""
        self.server.ensure_django()
        from base.services.sync import transport
        from base.services.sync.config import get_cloud_url
        url = get_cloud_url()
        if not url:
            return {'ok': False, 'error': 'CLOUD_SYNC_URL not set (Configuration tab)'}
        ok = transport.check_health()
        return {'ok': ok, 'reachable': ok, 'url': url,
                'message': 'reachable' if ok else 'unreachable'}

    @_safe
    def cloud_make_test_category(self, name=None):
        """Create a local Category so there's a real record to push up."""
        self.server.ensure_django()
        from base.models import Category
        from django.conf import settings
        branch = getattr(settings, 'BRANCH_ID', 'main') or 'main'
        nm = name or 'Desktop sync test'
        cat = Category.objects.create(name=nm, branch_id=branch)
        return {'ok': True, 'uuid': str(cat.uuid), 'name': nm, 'branch_id': branch}

    @_safe
    def cloud_push(self):
        """Push all unsynced local records up to the cloud hub."""
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        from desktop import shift_close_sync
        tracker_error = None
        try:
            shift_close_sync.prepare_for_push()
        except Exception as exc:  # noqa: BLE001 - still deliver ordinary records
            tracker_error = exc
            logger.exception('could not prepare shift-close acknowledgement')
        result = SyncService.push()
        try:
            close_status = shift_close_sync.after_push(result)
        except Exception as exc:  # noqa: BLE001
            tracker_error = exc
            logger.exception('could not verify shift-close acknowledgement')
            close_status = _shift_close_tracker_failure(shift_close_sync, exc)
        if tracker_error is not None and close_status.get('clear'):
            close_status = _shift_close_tracker_failure(
                shift_close_sync, tracker_error,
            )
        return _attach_shift_close_status(
            _sync_response(result, operation='Cloud push'), close_status,
        )

    @_safe
    def cloud_pull(self):
        """Pull changes from the cloud hub down into this branch."""
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        return _sync_response(SyncService.pull_from_cloud(), operation='Cloud pull')

    @_safe
    def cloud_sync_now(self):
        """Push pending local records + pull cloud changes right now — the same
        thing the background worker does every interval, on demand."""
        self.server.ensure_django()
        from base.services.sync.service import SyncService
        from base.services.sync.config import get_pull_enabled
        from desktop import shift_close_sync
        tracker_error = None
        try:
            shift_close_sync.prepare_for_push()
        except Exception as exc:  # noqa: BLE001 - still run push and pull
            tracker_error = exc
            logger.exception('could not prepare shift-close acknowledgement')
        push = SyncService.push()
        try:
            close_status = shift_close_sync.after_push(push)
        except Exception as exc:  # noqa: BLE001
            tracker_error = exc
            logger.exception('could not verify shift-close acknowledgement')
            close_status = _shift_close_tracker_failure(shift_close_sync, exc)
        if tracker_error is not None and close_status.get('clear'):
            close_status = _shift_close_tracker_failure(
                shift_close_sync, tracker_error,
            )
        pull = (
            SyncService.pull_from_cloud()
            if get_pull_enabled()
            else {'success': True, 'skipped': True, 'message': 'Pull disabled'}
        )
        push_response = _sync_response(push, operation='Cloud push')
        pull_response = _sync_response(pull, operation='Cloud pull')
        response = {
            'ok': push_response['ok'] and pull_response['ok'],
            'push': push,
            'pull': pull,
            'shift_close': close_status,
        }
        if not response['ok']:
            response['error'] = (
                push_response.get('error') or pull_response.get('error')
                or 'Cloud sync failed'
            )
        return _attach_shift_close_status(response, close_status)

    @_safe
    def cloud_dead_letters(self):
        """Per-model count of records that failed to push enough times to be
        dropped from the normal outbound batch (dead-lettered). A non-zero
        'shift'/'order' here is why a shift/sale is 'missing' on the cloud panel
        while it still exists on this till."""
        self.server.ensure_django()
        from collections import Counter
        from base.models import SyncQueueRecord
        from base.services.sync.config import get_sync_max_queue_attempts
        cap = get_sync_max_queue_attempts()
        by_model, total = {}, 0
        if cap:
            qs = SyncQueueRecord.objects.filter(attempts__gte=cap)
            by_model = dict(Counter(qs.values_list('model_name', flat=True)))
            total = sum(by_model.values())
        return {'ok': True, 'total': total, 'by_model': by_model, 'cap': cap}

    @_safe
    def cloud_resync_failed(self):
        """Recover stuck records: reset every dead-lettered row's attempt counter
        so it re-enters the outbound batch, then push right now. This is the
        'Retry stuck records' button — use it after the cloud is confirmed
        reachable to recover a shift/order that had gone permanently missing."""
        self.server.ensure_django()
        from base.models import SyncQueueRecord
        from base.services.sync.config import get_sync_max_queue_attempts
        from base.services.sync.service import SyncService
        cap = get_sync_max_queue_attempts()
        requeued = 0
        if cap:
            requeued = SyncQueueRecord.objects.filter(
                attempts__gte=cap).update(attempts=0, last_error='')
        push = SyncService.push()
        return {'ok': True, 'requeued': requeued, 'push': push}

    # -- telegram / notifications -------------------------------------------
    @_safe
    def order_audit_status(self):
        """Local append-only order evidence (independent from cloud sync)."""
        self.server.ensure_django()
        from desktop import order_audit
        order_audit.start_background_collector()
        return {'ok': True, **order_audit.get_status()}

    @_safe
    def set_order_audit_enabled(self, on):
        """Persist the collector toggle. Missing state intentionally means ON."""
        self.server.ensure_django()
        from desktop import order_audit
        order_audit.start_background_collector()
        return {'ok': True, **order_audit.set_enabled(bool(on))}

    @_safe
    def set_order_audit_auto_send(self, on):
        """Persist automatic direct-to-Telegram delivery (default ON)."""
        self.server.ensure_django()
        from desktop import order_audit
        order_audit.start_background_collector()
        return {'ok': True, **order_audit.set_auto_send(bool(on))}

    @_safe
    def send_order_audit_now(self):
        """Freeze and send raw local evidence directly to Telegram Bot API."""
        self.server.ensure_django()
        from desktop import order_audit
        order_audit.start_background_collector()
        # Drain the current database into the append-only file before freezing
        # it. This intentionally bypasses cloud sync/the AlphaPOS server.
        sweep = order_audit.capture_all_orders(reason='manual_export_sweep')
        result = order_audit.send_export_now()
        result['sweep'] = sweep
        return result

    @_safe
    def telegram_test(self):
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        # send_message returns (ok, error) — a REAL send to api.telegram.org.
        ok, err = TelegramAPI.send_message('✅ Alpha POS test message from the control panel.')
        return {'ok': bool(ok), 'error': err}

    @_safe
    def send_fake_notification(self):
        self.server.ensure_django()
        from base.notifications.telegram import TelegramAPI
        text = ('🧾 <b>TEST notification</b>\n\nOrder #TEST paid: 60 000 soʼm\n'
                'This is a fake notification from the control panel.')
        ok, err = TelegramAPI.send_message(text)
        return {'ok': bool(ok), 'error': err}

    @_safe
    def get_telegram(self):
        self.server.ensure_django()
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        return {'ok': True, 'bot_token_set': bool(ns.bot_token), 'chat_ids': ns.chat_ids}

    # -- notifications: admin telegram config + message layouts -------------
    @_safe
    def notif_settings(self):
        self.server.ensure_django()
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        return {'ok': True, 'bot_token_set': bool(ns.bot_token),
                'chat_ids': ns.chat_ids, 'brand_name': getattr(ns, 'brand_name', ''),
                'is_enabled': bool(ns.is_enabled)}

    @_safe
    def save_notif_settings(self, bot_token=None, chat_ids=None, brand_name=None):
        self.server.ensure_django()
        from django.core.cache import cache
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        if bot_token and bot_token != '••••••••':
            ns.bot_token = bot_token.strip()
        if chat_ids is not None:
            if isinstance(chat_ids, str):
                chat_ids = [c.strip() for c in chat_ids.replace(' ', ',').split(',') if c.strip()]
            ns.chat_ids = chat_ids
        if brand_name is not None:
            ns.brand_name = brand_name
        ns.save()
        try:
            cache.delete(getattr(NotificationSettings, '_CACHE_KEY', 'notif:settings:v1'))
        except Exception:
            pass
        return {'ok': True}

    @_safe
    def set_notif_enabled(self, on):
        """Master ON/OFF for the staff notifications Telegram bot (NotificationSettings.is_enabled)."""
        self.server.ensure_django()
        from django.core.cache import cache
        from notifications.models import NotificationSettings
        ns = NotificationSettings.load()
        ns.is_enabled = bool(on)
        ns.save(update_fields=['is_enabled', 'updated_at'])
        try:
            cache.delete(getattr(NotificationSettings, '_CACHE_KEY', 'notif:settings:v1'))
        except Exception:
            pass
        return {'ok': True, 'is_enabled': ns.is_enabled}

    @_safe
    def list_templates(self):
        """All Telegram/notification message layouts, editable."""
        self.server.ensure_django()
        from notifications.models import NotificationTemplate
        rows = [{
            'id': t.id, 'notification_type': t.notification_type, 'name': t.name,
            'template_text': t.template_text, 'description': t.description,
            'is_enabled': t.is_enabled, 'language': t.language,
        } for t in NotificationTemplate.objects.all()]
        return {'ok': True, 'templates': rows}

    @_safe
    def save_template(self, template_id, template_text, is_enabled=True):
        self.server.ensure_django()
        from django.core.cache import cache
        from notifications.models import NotificationTemplate
        from notifications.services.safe_format import validate_template_text
        err = validate_template_text(template_text)
        if err:
            return {'ok': False, 'error': err}
        t = NotificationTemplate.objects.filter(id=template_id).first()
        if not t:
            return {'ok': False, 'error': 'template not found'}
        t.template_text = template_text
        t.is_enabled = bool(is_enabled)
        t.save()
        try:
            cache.delete(f'notif:template:{t.notification_type}')
        except Exception:
            pass
        return {'ok': True}

    @_safe
    def preview_template(self, template_text):
        self.server.ensure_django()
        import string
        from notifications.services.safe_format import validate_template_text, safe_format
        err = validate_template_text(template_text)
        if err:
            return {'ok': False, 'error': err}
        samples = {'order_id': 'A-0042', 'display_id': 'A-0042', 'total': '60 000',
                   'amount': '60 000', 'customer': 'Akmal', 'name': 'Akmal',
                   'status': 'READY', 'branch': 'Main', 'phone': '+998 90 123 45 67',
                   'brand_name': 'My Cafe', 'time': '14:32', 'date': '2026-06-05',
                   'cashier': 'Dilnoza', 'table': '7', 'points': '12'}
        ctx = {}
        for _l, f, _s, _c in string.Formatter().parse(template_text):
            if f:
                ctx[f] = samples.get(f, f.upper())
        try:
            return {'ok': True, 'rendered': safe_format(template_text, **ctx)}
        except Exception as exc:  # noqa: BLE001
            return {'ok': False, 'error': str(exc)}

    @_safe
    def admin_credentials(self):
        """The first-admin login the app created on this PC, so the operator can
        sign in to the POS / admin panel. Stored locally (the GUI exe has no
        console where the bootstrap banner would appear)."""
        creds = config_store.read_admin_creds()
        return {'ok': True, 'email': creds.get('email', ''),
                'password': creds.get('password', ''), 'set': bool(creds.get('email'))}

    @_safe
    def admin_url(self):
        """The Django admin — full CRUD over every backend model (products,
        users, stock, loyalty, queue, ...)."""
        return {'ok': True, 'url': self.server.url() + '/admin/',
                'running': self.server.is_running()}

    @_safe
    def create_django_admin(self, username='admin', password='', email=''):
        """Create (or reset) the Django /admin/ superuser for this PC so the
        'Open full admin panel' button has a login. This is the Django auth
        user (username-based), separate from the POS app admin (email-based)."""
        if not username or not password:
            return {'ok': False, 'error': 'username and password are required'}
        self.server.ensure_django()
        # Make sure the auth tables exist even if Start was never pressed.
        try:
            self.server.run_management_command(
                'migrate', '--noinput', verbosity=0,
            )
        except Exception:  # noqa: BLE001
            logger.exception('migrate before admin create failed')
        from django.contrib.auth import get_user_model
        User = get_user_model()
        u = User.objects.filter(username=username).first()
        if u:
            u.set_password(password)
            u.is_staff = u.is_superuser = u.is_active = True
            u.save()
            return {'ok': True, 'created': False, 'username': username,
                    'message': 'password reset'}
        User.objects.create_superuser(username=username, email=email or '', password=password)
        return {'ok': True, 'created': True, 'username': username}

    # -- license / subscription ---------------------------------------------
    @_safe
    def license_register(self, email, plan_id=None):
        """Register this install against the control center (online). Requires
        LICENSE_CONTROL_CENTER_URL — returns its error if not configured."""
        self.server.ensure_django()
        from licensing.services import heartbeat
        body, status = heartbeat.register(email, plan_id)
        return {'ok': bool(body.get('success')), 'status': status, 'data': body}

    @_safe
    def license_plans(self):
        self.server.ensure_django()
        from licensing.services import heartbeat
        body, status = heartbeat.list_plans()
        return {'ok': status == 200, 'status': status, 'data': body}

    @_safe
    def license_plan_change(self, plan_id, note=''):
        self.server.ensure_django()
        from licensing.services import heartbeat
        body, status = heartbeat.request_plan_change(plan_id, note)
        return {'ok': status in (200, 201) or bool(body.get('success')),
                'status': status, 'data': body}

    @_safe
    def license_heartbeat_now(self):
        self.server.ensure_django()
        from licensing.services.heartbeat import do_heartbeat
        body, status = do_heartbeat()
        return {'ok': status == 200, 'status': status, 'data': body}

    @_safe
    def license_activate_offline(self, email='', org='', expires=''):
        """Interim activation with no control center: flips the license ACTIVE
        locally. expires='' means a perpetual license (explicit)."""
        self.server.ensure_django()
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('activate_offline', stdout=out, email=email or '', org=org or '',
                     expires=expires or '', perpetual=not bool(expires), deactivate=False)
        return {'ok': True, 'output': out.getvalue().strip()}

    @_safe
    def license_deactivate(self):
        self.server.ensure_django()
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('activate_offline', stdout=out, deactivate=True,
                     email='', org='', expires='', perpetual=False)
        return {'ok': True, 'output': out.getvalue().strip()}

    # -- fiscalization -------------------------------------------------------
    @_safe
    def fiscal_status(self):
        self.server.ensure_django()
        from fiscalization.services import FiscalizationService
        return {'ok': True, 'fiscal': FiscalizationService.stats()}

    @_safe
    def fiscal_set_mode(self, mode):
        self.server.ensure_django()
        from fiscalization.config import FiscalConfig
        FiscalConfig.set_mode(mode)
        return {'ok': True, 'mode': FiscalConfig.get_mode()}

    @_safe
    def fiscal_test(self):
        self.server.ensure_django()
        from fiscalization.config import FiscalConfig
        from fiscalization.providers import MockProvider
        payload = {'tin': FiscalConfig.tenant().get('tin') or '000000000',
                   'receipt_type': 'SALE', 'order_id': 'TEST', 'total': 5000000,
                   'items': [{'name': 'Test item', 'ikpu': '00000000000000000',
                              'price': 5000000, 'quantity': 1, 'vat_percent': 0, 'vat': 0}]}
        r = MockProvider(FiscalConfig.tenant()).fiscalize(payload)
        return {'ok': r.success, 'fiscal_sign': r.fiscal_sign, 'qr_url': r.qr_url,
                'fiscal_number': r.fiscal_number, 'error': r.error}

    # -- diagnostics: application logs ---------------------------------------
    _LOG_LINE_RE = None

    @_safe
    def app_logs(self, source='app', limit=600):
        """Parsed application log for the Logs page. `source` is 'app' (every
        record at the configured level and up — the default) or 'error'
        (ERROR+ only). The rotating file is tailed so a 10 MB log never blows
        up the panel. Each entry is {ts, level, logger, message}; lines that
        don't match the log format (tracebacks, multi-line messages) attach to
        the entry above them so an error keeps its stack trace.

        No ensure_django(): the log directory is resolved the same way
        settings.py does (LOG_DIR env, else DATA_DIR/logs) so this stays a
        cheap file read that works even before the POS server is started."""
        import os
        import re
        log_dir = os.environ.get('LOG_DIR') or str(config_store.DATA_DIR / 'logs')
        name = 'error.log' if source == 'error' else 'app.log'
        path = os.path.join(log_dir, name)
        try:
            limit = max(1, min(int(limit), 5000))
        except (TypeError, ValueError):
            limit = 600
        empty_counts = {'total': 0, 'error': 0, 'warning': 0, 'info': 0}
        if not os.path.exists(path):
            return {'ok': True, 'source': source, 'path': path, 'exists': False,
                    'entries': [], 'counts': empty_counts}
        # Tail the last ~1.5 MB so a large rotated file stays cheap to read.
        try:
            size = os.path.getsize(path)
            with open(path, 'rb') as fh:
                if size > 1_500_000:
                    fh.seek(size - 1_500_000)
                    fh.readline()  # drop the partial first line after the seek
                raw = fh.read().decode('utf-8', 'replace')
        except OSError as exc:
            return {'ok': False, 'error': str(exc), 'path': path}
        if Api._LOG_LINE_RE is None:
            # Mirrors the 'verbose' formatter in settings.LOGGING:
            #   {asctime} {levelname} {name} [{process}] {message}
            Api._LOG_LINE_RE = re.compile(
                r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[.,]?\d*)\s+'
                r'(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+'
                r'(\S+)\s+(?:\[\d+\]\s+)?(.*)$')
        entries = []
        for line in raw.splitlines():
            m = Api._LOG_LINE_RE.match(line)
            if m:
                ts, level, logger_name, msg = m.groups()
                entries.append({'ts': ts, 'level': level,
                                'logger': logger_name, 'message': msg})
            elif entries:
                # Continuation line (traceback / wrapped message).
                entries[-1]['message'] += '\n' + line
            # else: pre-first-record noise — drop it.
        entries = entries[-limit:]
        counts = {'total': len(entries), 'error': 0, 'warning': 0, 'info': 0}
        for e in entries:
            lv = e['level']
            if lv in ('ERROR', 'CRITICAL'):
                counts['error'] += 1
            elif lv == 'WARNING':
                counts['warning'] += 1
            else:
                counts['info'] += 1
        return {'ok': True, 'source': source, 'path': path, 'exists': True,
                'entries': entries, 'counts': counts}
