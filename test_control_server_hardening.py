"""The desktop panel must not 403 ('forbidden') on a fresh PC: accept any
loopback host, persist its API token across launches, and bind a free port when
something else squats on 8765 (instead of loading the wrong server)."""
import http.server
import threading

import pytest

from desktop import control_server as cs


def _fake(host):
    class F:
        pass
    f = F()
    f.headers = {'Host': host}
    return f


def test_host_check_accepts_loopback_rejects_others():
    ok = cs.Handler._host_ok
    assert ok(_fake('127.0.0.1:8765'))
    assert ok(_fake('localhost:51234'))      # any port (fallback ports)
    assert ok(_fake('127.0.0.1'))            # no port
    assert ok(_fake('[::1]:8765'))           # IPv6 loopback
    assert not ok(_fake('evil.com:8765'))    # DNS-rebinding attempt
    assert not ok(_fake('192.168.1.50:8765'))
    assert not ok(_fake(''))


def test_token_persisted_across_launches(tmp_path, monkeypatch):
    from desktop import config_store
    monkeypatch.setattr(config_store, 'DATA_DIR', tmp_path)
    t1 = cs._load_or_make_token()
    t2 = cs._load_or_make_token()
    assert t1 and t1 == t2
    assert (tmp_path / '.control_token').exists()


def test_serve_falls_back_when_port_squatted_by_other_app():
    class _Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'not-alphapos')   # /healthz != our marker
        def log_message(self, *a):
            pass

    try:
        other = http.server.ThreadingHTTPServer(('127.0.0.1', 8765), _Other)
    except OSError:
        pytest.skip('port 8765 already in use on this machine')
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        httpd = cs.serve()                       # 8765 taken by a non-panel app
        try:
            assert cs.CONTROL_PORT != 8765       # bound a free fallback instead
            assert httpd.server_address[1] == cs.CONTROL_PORT
        finally:
            httpd.server_close()
    finally:
        other.shutdown()
        other.server_close()
        cs.CONTROL_PORT = 8765                    # restore module default
