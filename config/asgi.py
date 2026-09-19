"""ASGI entrypoint — local edition. Serves HTTP (Django) + websockets (channels,
InMemoryChannelLayer) through one ProtocolTypeRouter. Run with embedded uvicorn
inside the desktop build."""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.asgi import get_asgi_application

# Initialise Django (populate the app registry) BEFORE importing consumers.
django_asgi_app = get_asgi_application()

from django.core.wsgi import get_wsgi_application  # noqa: E402

from desktop.http_threads import ThreadedWSGI  # noqa: E402

# HTTP runs on a bounded pool of threads with persistent database connections
# (see desktop/http_threads.py); Django's ASGI handler would serialize every
# request onto one thread and reconnect to PostgreSQL each time.
http_app = ThreadedWSGI(
    get_wsgi_application(),
    workers=int(os.environ.get('ALPHA_POS_HTTP_THREADS', '32') or 32),
)

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from core.realtime.routing import websocket_urlpatterns  # noqa: E402
from couriers.routing import (  # noqa: E402
    websocket_urlpatterns as courier_ws_urlpatterns,
)

application = ProtocolTypeRouter({
    'http': http_app,
    'websocket': AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns + courier_ws_urlpatterns)),
})
