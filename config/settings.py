"""Local edition settings — Windows desktop POS. Extends the shared core spine.

Run with DJANGO_SETTINGS_MODULE=config.settings. The desktop launcher supplies a
per-install SECRET_KEY, ALPHA_POS_DATA_DIR, and (eventually) the embedded-Postgres
DB_* env. OPEN_LAN is on by default — the till serves the POS to LAN devices.
"""
import os

os.environ.setdefault('DEPLOYMENT_MODE', 'local')
# Trusted-LAN appliance: open CORS + drop CSRF host/secure-cookie enforcement so
# arbitrary LAN devices can reach the POS. Must be set BEFORE importing the base
# settings, whose middleware/cookie logic reads OPEN_LAN at import time.
os.environ.setdefault('OPEN_LAN', 'True')

from alpha_pos_core.settings_base import *  # noqa: F401,F403

EDITION = 'local'

# POS apps on top of the shared spine. admins is NOT installed. hr IS installed
# (shared, tables-only — its urls are not mounted), so the AUTO_POS attendance row
# written at cashier login has a table to land in.
INSTALLED_APPS = build_installed_apps(['customers', 'waiters'])  # noqa: F405

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
