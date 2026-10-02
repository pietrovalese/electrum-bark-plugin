"""Ponte locale tra Ark Quest (browser) e il client del plugin.

  python script/bridge.py --fake      # client finto: demo senza barkd
  python script/bridge.py             # barkd reale (BARKD_TOKEN, BARKD_HOST come per il plugin)

Serve la pagina su http://127.0.0.1:8765/ e inoltra le missioni agli stessi metodi di
BarkClient che usa il plugin. Il token resta qui, mai nel browser. Solo localhost.
"""
import argparse
import json
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bark.client import BarkClient, BarkError, BarkNoWallet, BarkUnavailable  # noqa: E402
from bark.fake_client import FakeBarkClient  # noqa: E402

PAGE = next((p for p in (ROOT / 'Ark Quest.html', ROOT / 'demo' / 'ark-quest.html')
             if p.exists()), None)

CALLS = {   # nome esposto al browser -> chiamata sul client (come fa ui.py)
    'snapshot': lambda c, a: c.snapshot(),
    'history': lambda c, a: c.history()[:10],
    'create_wallet': lambda c, a: c.create_wallet(),
    'new_onchain_address': lambda c, a: c.new_onchain_address(),
    'board_all': lambda c, a: c.board_all(),
    'board_amount': lambda c, a: c.board_amount(a.get('amount_sat')),
    'receive_uri': lambda c, a: c.receive_uri(
        a.get('amount_sat'), a.get('label'), a.get('message'), a.get('onchain', True)),
    'send': lambda c, a: c.send(a.get('destination'), a.get('amount_sat'), a.get('comment')),
    'send_onchain': lambda c, a: c.send_onchain(a.get('destination'), a.get('amount_sat')),
    'faucet': lambda c, a: c.faucet(),   # solo client finto
}


def make_handler(client, fake, port):
    hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body, ctype='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _guard(self):
            # anti DNS-rebinding / CSRF: solo localhost e header custom (niente CORS concesso)
            if self.headers.get('Host') not in hosts:
                self._send(403, {'error': 'bad host'})
                return False
            if self.path.startswith('/api/') and self.headers.get('X-Ark-Quest') != '1':
                self._send(403, {'error': 'missing X-Ark-Quest header'})
                return False
            return True

        def do_GET(self):
            if not self._guard():
                return
            if self.path in ('/', '/index.html') and PAGE:
                return self._send(200, PAGE.read_bytes(), 'text/html; charset=utf-8')
            if self.path == '/api/mode':
                return self._send(200, {'live': True, 'fake': fake})
            self._send(404, {'error': 'not found'})

        def do_POST(self):
            if not self._guard():
                return
            name = self.path[len('/api/'):] if self.path.startswith('/api/') else ''
            if name not in CALLS:
                return self._send(404, {'error': f'unknown call: {name}'})
            if name == 'faucet' and not fake:
                return self._send(400, {'error': 'faucet exists only with --fake', 'kind': 'error'})
            try:
                n = min(int(self.headers.get('Content-Length') or 0), 65536)
                args = json.loads(self.rfile.read(n) or b'{}')
                self._send(200, {'result': CALLS[name](client, args)})
            except BarkNoWallet as e:
                self._send(409, {'error': str(e), 'kind': 'no_wallet'})
            except BarkUnavailable as e:
                self._send(503, {'error': f'barkd not reachable: {e}', 'kind': 'unavailable'})
            except BarkError as e:
                self._send(400, {'error': str(e), 'kind': 'error'})
            except Exception as e:  # noqa
                self._send(500, {'error': f'{type(e).__name__}: {e}', 'kind': 'error'})

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--fake', action='store_true', help='usa il client finto (nessun barkd)')
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args()
    if PAGE is None:
        sys.exit("Ark Quest.html not found")
    client = FakeBarkClient('no_wallet') if args.fake else BarkClient()
    if not args.fake and not client.token:
        print("warning: BARKD_TOKEN is not set (export BARKD_TOKEN=$(./script/barkd_token.sh))")
    server = ThreadingHTTPServer(('127.0.0.1', args.port),
                                 make_handler(client, args.fake, args.port))
    print(f"Ark Quest on http://127.0.0.1:{args.port}/  "
          f"({'fake client' if args.fake else 'barkd at ' + client.host})  Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()