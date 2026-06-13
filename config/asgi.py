"""ASGI entrypoint — local edition. Serves HTTP (Django) + websockets (channels,
InMemoryChannelLayer) through one ProtocolTypeRouter. Run with embedded uvicorn
inside the desktop build."""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.core.asgi import get_asgi_application

# Initialise Django (populate the app registry) BEFORE importing consumers.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from core.realtime.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
