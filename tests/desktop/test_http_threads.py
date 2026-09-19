"""HTTP on a bounded thread pool with persistent database connections."""
import asyncio
import threading

import pytest

from desktop.http_threads import ThreadedWSGI, _persistent_connections, build_environ


def _scope(path='/x', method='GET', query=b'', headers=()):
    return {
        'type': 'http', 'method': method, 'path': path, 'root_path': '', 'query_string': query,
        'http_version': '1.1', 'scheme': 'http', 'server': ('127.0.0.1', 8000),
        'client': ('127.0.0.1', 51000), 'headers': list(headers),
    }


def _serve(app, scope, messages):
    """Run one request; return (sent messages, whether the app was called)."""
    inbox = list(messages)
    sent = []

    async def receive():
        return inbox.pop(0) if inbox else {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


class _Result:
    """A WSGI result that records where and whether close() ran."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.closed_in = None

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed_in = threading.current_thread().name


def test_response_status_headers_and_body_and_close_in_the_worker():
    seen = {}

    def wsgi(environ, start_response):
        seen['environ'] = environ
        seen['result'] = _Result([b'hel', b'', b'lo'])
        start_response('201 Created', [('Content-Type', 'text/plain'), ('X-Name', 'caf\xe9')])
        return seen['result']

    app = ThreadedWSGI(wsgi, workers=2)
    sent = _serve(app, _scope(), [{'type': 'http.request', 'body': b'', 'more_body': False}])

    assert sent[0] == {
        'type': 'http.response.start', 'status': 201,
        'headers': [(b'Content-Type', b'text/plain'), (b'X-Name', b'caf\xe9')],
    }
    assert sent[1] == {'type': 'http.response.body', 'body': b'hello', 'more_body': False}
    assert seen['result'].closed_in.startswith('pos-http')


def test_request_body_and_headers_reach_the_environ():
    captured = {}

    def wsgi(environ, start_response):
        captured.update(environ)
        captured['body'] = environ['wsgi.input'].read()
        start_response('200 OK', [])
        return [b'']

    headers = [
        (b'content-type', b'application/json'), (b'content-length', b'12'),
        (b'x-device-id', b'till-1'), (b'accept', b'a'), (b'accept', b'b'),
        (b'user-agent', b'Caf\xe9'),
    ]
    _serve(ThreadedWSGI(wsgi, workers=1), _scope('/api/orders', 'POST', b'page=2', headers), [
        {'type': 'http.request', 'body': b'{"a":', 'more_body': True},
        {'type': 'http.request', 'body': b' 12345}', 'more_body': False},
    ])

    assert captured['body'] == b'{"a": 12345}'
    assert captured['REQUEST_METHOD'] == 'POST'
    assert captured['PATH_INFO'] == '/api/orders'
    assert captured['QUERY_STRING'] == 'page=2'
    assert captured['CONTENT_TYPE'] == 'application/json'
    assert captured['CONTENT_LENGTH'] == '12'
    assert captured['HTTP_X_DEVICE_ID'] == 'till-1'
    assert captured['HTTP_ACCEPT'] == 'a,b'
    assert captured['HTTP_USER_AGENT'] == 'Caf\xe9'
    assert captured['REMOTE_ADDR'] == '127.0.0.1'
    assert captured['wsgi.multithread'] is True


def test_client_gone_before_the_body_arrives_skips_the_view():
    called = []

    def wsgi(environ, start_response):
        called.append(True)
        start_response('200 OK', [])
        return [b'']

    sent = _serve(ThreadedWSGI(wsgi, workers=1), _scope(method='POST'), [
        {'type': 'http.request', 'body': b'part', 'more_body': True},
        {'type': 'http.disconnect'},
    ])

    assert sent == [] and called == []


def test_requests_run_in_parallel():
    both_inside = threading.Barrier(2, timeout=5)

    def wsgi(environ, start_response):
        both_inside.wait()  # deadlocks (BrokenBarrierError) if requests are serialized
        start_response('200 OK', [])
        return [environ['PATH_INFO'].encode()]

    app = ThreadedWSGI(wsgi, workers=4)

    async def run_two():
        async def one(path):
            sent = []
            inbox = [{'type': 'http.request', 'body': b'', 'more_body': False}]

            async def receive():
                return inbox.pop(0) if inbox else {'type': 'http.disconnect'}

            async def send(message):
                sent.append(message)

            await app(_scope(path), receive, send)
            return sent[1]['body']

        return await asyncio.gather(one('/a'), one('/b'))

    assert asyncio.run(run_two()) == [b'/a', b'/b']


def test_async_to_sync_in_a_view_runs_on_the_server_loop():
    """Realtime publishes (async_to_sync -> channel layer) must use the serving
    loop: the in-memory channel layer is not safe across event loops/threads."""
    from asgiref.sync import async_to_sync

    seen = {}

    async def publish():
        seen['loop'] = asyncio.get_running_loop()

    def wsgi(environ, start_response):
        async_to_sync(publish)()
        seen['thread'] = threading.current_thread().name
        start_response('200 OK', [])
        return [b'']

    app = ThreadedWSGI(wsgi, workers=1)

    async def serve():
        seen['server_loop'] = asyncio.get_running_loop()
        inbox = [{'type': 'http.request', 'body': b'', 'more_body': False}]

        async def receive():
            return inbox.pop(0) if inbox else {'type': 'http.disconnect'}

        async def send(message):
            pass

        await app(_scope(), receive, send)

    asyncio.run(serve())
    assert seen['thread'].startswith('pos-http')
    assert seen['loop'] is seen['server_loop']


def test_only_http_is_served():
    with pytest.raises(ValueError):
        asyncio.run(ThreadedWSGI(lambda e, s: [], workers=1)({'type': 'websocket'}, None, None))


def test_a_chunked_body_without_content_length_still_reaches_the_view():
    environ = build_environ(_scope(method='POST', headers=[(b'content-type', b'application/json')]), b'{"a": 1}')
    assert environ['CONTENT_LENGTH'] == '8'
    assert environ['wsgi.input'].read() == b'{"a": 1}'


def test_root_path_is_split_from_the_path():
    environ = build_environ({**_scope('/pos/api/x'), 'root_path': '/pos'}, b'')
    assert environ['SCRIPT_NAME'] == '/pos'
    assert environ['PATH_INFO'] == '/api/x'


def test_worker_threads_keep_their_postgres_connection():
    from django.db import connections

    main_setting = connections['default'].settings_dict.get('CONN_MAX_AGE')
    worker = {}

    def run():
        _persistent_connections()
        conn = connections['default']
        worker['vendor'] = conn.vendor
        worker['max_age'] = conn.settings_dict.get('CONN_MAX_AGE')
        worker['health_checks'] = conn.settings_dict.get('CONN_HEALTH_CHECKS')

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    if worker['vendor'] == 'postgresql':
        assert worker['max_age'] is None and worker['health_checks'] is True
    # Only the pool's threads change; every other thread keeps the default.
    assert connections['default'].settings_dict.get('CONN_MAX_AGE') == main_setting


def test_the_asgi_application_serves_http_from_the_thread_pool():
    from config import asgi

    assert isinstance(asgi.http_app, ThreadedWSGI)
    sent = _serve(asgi.application, _scope('/healthz'), [
        {'type': 'http.request', 'body': b'', 'more_body': False},
    ])
    assert sent[0]['status'] == 200
    assert sent[1]['body'].startswith(b'ok ')
