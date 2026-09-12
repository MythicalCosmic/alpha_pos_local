"""Serve the compiled waiter client from the local POS process.

The HTML is deliberately public: the Vue application performs waiter-session
recovery and the JSON APIs remain the authorization boundary. Serving the shell
before login also lets a phone recover cleanly after its cookie expires.
"""
from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def index(request, route=None):
    response = render(request, 'waiter/index.html')
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_GET
def service_worker(_request):
    asset = finders.find('waiter/sw.js')
    if not asset:
        raise Http404('Waiter service worker is not installed')
    response = FileResponse(
        Path(asset).open('rb'),
        content_type='application/javascript; charset=utf-8',
    )
    response['Cache-Control'] = 'no-cache'
    response['Service-Worker-Allowed'] = '/waiter/'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
