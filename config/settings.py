"""Local edition settings — Windows desktop POS. Extends the shared core spine.

Run with DJANGO_SETTINGS_MODULE=config.settings. The desktop launcher supplies a
per-install SECRET_KEY, ALPHA_POS_DATA_DIR, and (eventually) the embedded-Postgres
DB_* env. OPEN_LAN is on by default — the till serves the POS to LAN devices.
"""
import os

from desktop.version import __version__ as DESKTOP_VERSION

os.environ.setdefault('DEPLOYMENT_MODE', 'local')
# Trusted-LAN appliance: open CORS + drop CSRF host/secure-cookie enforcement so
# arbitrary LAN devices can reach the POS. Must be set BEFORE importing the base
# settings, whose middleware/cookie logic reads OPEN_LAN at import time.
os.environ.setdefault('OPEN_LAN', 'True')
os.environ.setdefault('ALPHA_POS_CLIENT_VERSION', f'alpha_pos/{DESKTOP_VERSION}')

from alpha_pos_core.settings_base import *  # noqa: F401,F403

EDITION = 'local'

# POS apps on top of the shared spine. admins is NOT installed. hr IS installed
# (shared, tables-only — its urls are not mounted), so the AUTO_POS attendance row
# written at cashier login has a table to land in.
INSTALLED_APPS = build_installed_apps(['customers', 'waiters', 'couriers'])  # noqa: F405

# Local-only request/response evidence. It must wrap LoginTransitionGuard so a
# rejected cookie/Bearer conflict is still durably captured, while remaining
# after Django's AuthenticationMiddleware. It never ships on the cloud edition.
_ORDER_HTTP_AUDIT_MIDDLEWARE = (
    'desktop.order_http_audit.OrderMutationEvidenceMiddleware'
)
_LOGIN_TRANSITION_GUARD_MIDDLEWARE = (
    'base.middlewares.login_transition_guard.LoginTransitionGuardMiddleware'
)
_DJANGO_AUTH_MIDDLEWARE = (
    'django.contrib.auth.middleware.AuthenticationMiddleware'
)


def _with_order_http_audit(middleware):
    ordered = [
        entry for entry in middleware
        if entry != _ORDER_HTTP_AUDIT_MIDDLEWARE
    ]
    auth_index = ordered.index(_DJANGO_AUTH_MIDDLEWARE)
    if _LOGIN_TRANSITION_GUARD_MIDDLEWARE in ordered:
        guard_index = ordered.index(_LOGIN_TRANSITION_GUARD_MIDDLEWARE)
        if guard_index <= auth_index:
            raise RuntimeError(
                'LoginTransitionGuardMiddleware must follow '
                'AuthenticationMiddleware'
            )
        ordered.insert(guard_index, _ORDER_HTTP_AUDIT_MIDDLEWARE)
    else:
        # Compatibility with an older pinned core during a staged upgrade.
        # Once the guard is present, the branch above guarantees wrapping.
        ordered.insert(auth_index + 1, _ORDER_HTTP_AUDIT_MIDDLEWARE)
    return ordered


MIDDLEWARE = _with_order_http_audit(MIDDLEWARE)  # noqa: F405

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Single process (the desktop .exe): in-memory channel layer — no Redis, no file.
# (Activates once 'channels' is added in the websocket phase; inert until then.)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
        # capacity per channel: the default 100 silently DROPS messages under an
        # order burst (load test: 100 -> 50% delivered; 5000 -> 100% at >100k msg/s).
        'CONFIG': {'capacity': 5000},
    },
}
