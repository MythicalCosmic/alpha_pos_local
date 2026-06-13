"""ASGI entrypoint — local edition.

Phase 0: a plain Django ASGI app (served by embedded uvicorn in place of waitress).
The websocket phase wraps this in a channels ProtocolTypeRouter so the LAN order
queue / KDS / cashier-control sockets run in-process (InMemoryChannelLayer).
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
