"""Local edition URLconf — the in-store POS surface.

Mounts the cashier (customers) + waiter POS, sync, licensing, fiscalization, and
the Telegram/QR self-order webhooks (order-taking lives on the terminal). No
back-office admin REST API (api/admins/*) is mounted here.
"""
import os

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include

from base.services.sync.views import get_sync_urls
from notifications.views import telegram_views, qr_order_views


def healthz(_request):
    sha = os.environ.get('APP_GIT_SHA', 'unknown')
    return HttpResponse(f'ok {sha}', content_type='text/plain')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz', healthz),
    path('api/waiters/', include('waiters.urls')),
    path('api/sync/', include(get_sync_urls())),
    path('api/licensing/', include('licensing.urls')),
    path('api/fiscalization/', include('fiscalization.urls')),
    # Telegram webhook + public QR self-order — order-taking surfaces, terminal-side.
    path('api/telegram/webhook/', telegram_views.webhook, name='telegram-webhook'),
    path('api/qr/menu/<str:token>/', qr_order_views.menu_view, name='qr-menu'),
    path('api/qr/order/<str:token>/', qr_order_views.order_view, name='qr-order'),
    path('', include('customers.urls')),
]
