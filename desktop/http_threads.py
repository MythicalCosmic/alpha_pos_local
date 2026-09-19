"""Serve Django HTTP from a fixed pool of long-lived threads.

Django's ASGI handler runs every synchronous view on ONE shared thread, so
concurrent requests from waiters, cashiers and displays queued behind each
other, and each request opened a fresh PostgreSQL connection (TCP, password
authentication and, on Windows, a new postgres.exe). This adapter keeps the
ASGI server (websockets stay on Channels) but runs the plain Django WSGI
application on a bounded thread pool:

- requests run in parallel, one per worker thread;
- every worker keeps its own database connection open between requests
  (``CONN_MAX_AGE=None`` for these threads only; everything else keeps the
  project default), so the number of connections is bounded by the pool;
- the response is iterated and closed in the same worker thread, so Django's
  ``request_finished`` handling (connection health checks) runs where the
  connection lives.
"""
from __future__ import annotations

import asyncio
import io
import sys
from concurrent.futures import ThreadPoolExecutor

DEFAULT_WORKERS = 16


def _persistent_connections():
    """Thread initializer: this worker's connections survive between requests."""
    from django.db import connections

    for alias in connections:
        conn = connections[alias]
        if conn.vendor == 'postgresql':
            conn.settings_dict = {**conn.settings_dict, 'CONN_MAX_AGE': None, 'CONN_HEALTH_CHECKS': True}


def build_environ(scope, body: bytes) -> dict:
    script_name = scope.get('root_path', '').encode('utf8').decode('latin1')
    path_info = scope['path'].encode('utf8').decode('latin1')
    if script_name and path_info.startswith(script_name):
        path_info = path_info[len(script_name):]
    server = scope.get('server') or ('localhost', 80)
    environ = {
        'REQUEST_METHOD': scope['method'],
        'SCRIPT_NAME': script_name,
        'PATH_INFO': path_info,
        'QUERY_STRING': scope.get('query_string', b'').decode('latin1'),
        'SERVER_PROTOCOL': f"HTTP/{scope.get('http_version', '1.1')}",
        'SERVER_NAME': str(server[0]),
        'SERVER_PORT': str(server[1]),
        'wsgi.version': (1, 0),
        'wsgi.url_scheme': scope.get('scheme', 'http'),
        'wsgi.input': io.BytesIO(body),
        'wsgi.errors': sys.stderr,
        'wsgi.multithread': True,
        'wsgi.multiprocess': False,
        'wsgi.run_once': False,
    }
    client = scope.get('client')
    if client:
        environ['REMOTE_ADDR'] = client[0]
        environ['REMOTE_PORT'] = str(client[1])
    for raw_name, raw_value in scope.get('headers', []):
        name = raw_name.decode('latin1')
        value = raw_value.decode('latin1')
        if name == 'content-length':
            key = 'CONTENT_LENGTH'
        elif name == 'content-type':
            key = 'CONTENT_TYPE'
        else:
            key = 'HTTP_' + name.upper().replace('-', '_')
        environ[key] = f'{environ[key]},{value}' if key in environ else value
    return environ


class ThreadedWSGI:
    """ASGI app that runs a WSGI app on a bounded pool of persistent threads."""

    def __init__(self, wsgi_app, workers: int = DEFAULT_WORKERS):
        self.app = wsgi_app
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, int(workers)),
            thread_name_prefix='pos-http',
            initializer=_persistent_connections,
        )

    def _run(self, environ):
        response = {}
        chunks = []

        def start_response(status, headers, exc_info=None):
            response['status'] = int(status.split(' ', 1)[0])
            response['headers'] = [(k.encode('latin1'), v.encode('latin1')) for k, v in headers]
            return chunks.append  # legacy write() callable

        result = self.app(environ, start_response)
        try:
            for chunk in result:
                if chunk:
                    chunks.append(chunk)
        finally:
            close = getattr(result, 'close', None)
            if close is not None:
                close()
        return response['status'], response['headers'], b''.join(chunks)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            raise ValueError(f"ThreadedWSGI only serves http, not {scope['type']}")
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body += message.get('body', b'')
            if not message.get('more_body', False):
                break
        environ = build_environ(scope, bytes(body))
        loop = asyncio.get_running_loop()
        status, headers, content = await loop.run_in_executor(self.executor, self._run, environ)
        await send({'type': 'http.response.start', 'status': status, 'headers': headers})
        await send({'type': 'http.response.body', 'body': content, 'more_body': False})
