"""Tests for config precedence, URL security check, Qt hooks, and the demo HTTP bridge."""
import http.client
import json
import pathlib
import sys
import threading
from http.server import ThreadingHTTPServer

import pytest

from bark.bark import BarkPlugin
from bark.client import DEFAULT_HOST, is_insecure_remote
from bark.fake_client import FakeBarkClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT / 'script') not in sys.path:
    sys.path.insert(0, str(ROOT / 'script'))

import bridge  # noqa: E402


class FakeConfig:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set_key(self, key, value, save=True):
        self.data[key] = value


# --------------------------------------------------------------------------- URL safety
@pytest.mark.parametrize('url,expected', [
    ('', False),
    ('http://localhost:3001', False),
    ('http://127.0.0.1:3001', False),
    ('http://127.0.1.1:3001', False),
    ('http://[::1]:3001', False),
    ('https://barkd.example.com:3001', False),
    ('http://192.168.1.50:3001', True),
    ('http://barkd.example.com:3001', True),
])
def test_is_insecure_remote(url, expected):
    assert is_insecure_remote(url) is expected


# --------------------------------------------------------------------------- BarkPlugin config
def test_plugin_config_precedence_and_env_fallback(monkeypatch):
    cfg = FakeConfig()
    plugin = BarkPlugin(None, cfg, 'bark')
    monkeypatch.setenv('BARKD_HOST', 'http://127.0.0.1:4444')
    monkeypatch.setenv('BARKD_TOKEN', 'env-token')

    c1 = plugin.client()
    assert c1.host == 'http://127.0.0.1:4444'
    assert c1.token == 'env-token'

    monkeypatch.delenv('BARKD_HOST')
    c2 = plugin.client()
    assert c2.host == DEFAULT_HOST

    plugin.save_settings('http://127.0.0.1:5555', 'cfg-token', False)
    c3 = plugin.client()
    assert c3.host == 'http://127.0.0.1:5555'
    assert c3.token == 'cfg-token'


def test_plugin_fake_singleton_reset_on_save():
    cfg = FakeConfig({'bark_use_fake': True})
    plugin = BarkPlugin(None, cfg, 'bark')
    f1 = plugin.client()
    assert isinstance(f1, FakeBarkClient)
    assert plugin.client() is f1
    plugin.save_settings('', '', True)
    f2 = plugin.client()
    assert f2 is not f1


# --------------------------------------------------------------------------- Qt Plugin hooks
def test_qt_plugin_hooks_and_attach_open_windows():
    PyQt6_widgets = pytest.importorskip('PyQt6.QtWidgets')
    pytest.importorskip('electrum.gui.qt.qrcodewidget')
    from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget
    from bark.qt import Plugin

    app = QApplication.instance() or QApplication([])

    class StubWallet:
        pass

    class StubWindow(QWidget):
        def __init__(self, wallet):
            super().__init__()
            self.wallet = wallet
            self.tabs = QTabWidget()

    w1 = StubWallet()
    win1 = StubWindow(w1)
    win1.show()
    app.processEvents()

    cfg = FakeConfig({'bark_use_fake': True})
    plugin = Plugin(None, cfg, 'bark')
    try:
        # Attached automatically to already-open wallet window (L3)
        assert win1 in plugin.tabs
        assert win1.tabs.count() == 1

        # RPC load_wallet calls hook with window=None (L6) -> safely ignored
        plugin.load_wallet(w1, None)
        assert len(plugin.tabs) == 1

        # Second window via load_wallet hook
        w2 = StubWallet()
        win2 = StubWindow(w2)
        plugin.load_wallet(w2, win2)
        assert win2 in plugin.tabs
        assert win2.tabs.count() == 1

        # close_wallet removes only matching window
        plugin.close_wallet(w2)
        assert win2 not in plugin.tabs
        assert win2.tabs.count() == 0
        assert win1 in plugin.tabs

        # on_close cleans remaining tabs
        plugin.on_close()
        assert plugin.tabs == {}
        assert win1.tabs.count() == 0
    finally:
        plugin.on_close()
        win1.close()
        win1.deleteLater()
        app.processEvents()


# --------------------------------------------------------------------------- bridge.py
@pytest.fixture
def bridge_server(monkeypatch):
    import time
    import types
    monkeypatch.setattr('bark.fake_client.time',
                        types.SimpleNamespace(sleep=lambda s: None, time=time.time))
    fake = FakeBarkClient('no_wallet')
    server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.make_handler(fake, True, 0))
    port = server.server_port
    # Rebind handler with actual port for Host check
    server.RequestHandlerClass = bridge.make_handler(fake, True, port)
    t = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    t.start()
    yield port
    server.shutdown()
    server.server_close()


def _req(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    hdrs = {'Host': f'127.0.0.1:{port}'}
    if headers:
        hdrs.update(headers)
    if isinstance(body, str):
        body = body.encode()
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, raw


def test_bridge_guards_and_errors(bridge_server):
    port = bridge_server
    h = {'X-Ark-Quest': '1'}

    status, _ = _req(port, 'GET', '/')
    assert status == 200

    status, _ = _req(port, 'GET', '/api/mode')
    assert status == 403

    status, _ = _req(port, 'GET', '/api/mode', headers={**h, 'Host': 'evil.example'})
    assert status == 403

    status, raw = _req(port, 'GET', '/api/mode', headers=h)
    assert status == 200 and json.loads(raw) == {'live': True, 'fake': True}

    status, _ = _req(port, 'POST', '/api/nope', body='{}', headers=h)
    assert status == 404

    status, _ = _req(port, 'POST', '/api/snapshot', body='{bad json', headers=h)
    assert status == 400

    status, _ = _req(port, 'POST', '/api/snapshot', body='[1, 2]', headers=h)
    assert status == 400

    status, _ = _req(port, 'POST', '/api/snapshot', body='x' * 70000, headers=h)
    assert status == 413

    # Full fake lifecycle through bridge
    status, _ = _req(port, 'POST', '/api/snapshot', body='{}', headers=h)
    assert status == 409
    status, _ = _req(port, 'POST', '/api/create_wallet', body='{}', headers=h)
    assert status == 200
    status, _ = _req(port, 'POST', '/api/faucet', body='{}', headers=h)
    assert status == 200
    status, raw = _req(port, 'POST', '/api/snapshot', body='{}', headers=h)
    assert status == 200 and json.loads(raw)['result']['onchain_confirmed_sat'] == 100_000


def test_bridge_rejects_faucet_in_live_mode():
    server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.make_handler(FakeBarkClient('ok'), False, 0))
    port = server.server_port
    server.RequestHandlerClass = bridge.make_handler(FakeBarkClient('ok'), False, port)
    t = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    t.start()
    try:
        status, _ = _req(port, 'POST', '/api/faucet', body='{}', headers={'X-Ark-Quest': '1'})
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()
