"""Mini server HTTP che imita barkd (solo libreria standard).

Risponde con JSON nella forma attesa da `barkd_client` 0.7.2 e registra ogni richiesta.
Si può far finta che manchi il wallet, cambiare il token valido, sostituire la risposta di
una rotta o farla fallire. Le rotte sconosciute rispondono 404.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = 'test-token'

MOVE_SEND = {
    "id": 7,
    "effective_balance_sat": -1500, "intended_balance_sat": -1500, "offchain_fee_sat": 5,
    "exited_vtxos": [], "input_vtxos": [], "output_vtxos": [], "metadata": None,
    "received_on": [],
    "sent_to": [{"amount_sat": 1495, "destination": {"type": "ark", "value": "tark1dest"}}],
    "status": "successful",
    "subsystem": {"kind": "send", "name": "bark.arkoor"},
    "time": {"created_at": "2026-10-01T10:00:00Z", "updated_at": "2026-10-01T10:00:01Z",
             "completed_at": "2026-10-01T10:00:01Z"},
}
MOVE_RECEIVE = dict(
    MOVE_SEND, id=8, effective_balance_sat=2000, intended_balance_sat=2000, offchain_fee_sat=0,
    sent_to=[],
    received_on=[{"amount_sat": 2000, "destination": {"type": "ark", "value": "tark1mine"}}],
    subsystem={"kind": "receive", "name": "bark.arkoor"}, status="pending",
    time={"created_at": "2026-10-02T10:00:00Z", "updated_at": "2026-10-02T10:00:00Z",
          "completed_at": None})

TXID_BOARD = 'cd' * 32
TXID_OFFBOARD = 'ab' * 32


def default_routes():
    return {
        ('GET', '/api/v1/wallet/balance'): {
            "spendable_sat": 5000, "pending_board_sat": 300,
            "claimable_lightning_receive_sat": 0, "pending_in_round_sat": 0,
            "pending_lightning_send_sat": 0},
        ('GET', '/api/v1/wallet/connected'): {"connected": True},
        ('GET', '/api/v1/onchain/balance'): {
            "confirmed_sat": 9000, "immature_sat": 0, "total_sat": 9150,
            "trusted_pending_sat": 100, "trusted_spendable_sat": 9000,
            "untrusted_pending_sat": 50},
        ('POST', '/api/v1/onchain/sync'): {},
        ('GET', '/api/v1/history'): [MOVE_SEND, MOVE_RECEIVE],
        ('GET', '/api/v1/boards/pending'): [{
            "amount_sat": 300, "funding_tx": {"tx": "00", "txid": TXID_BOARD},
            "movement_id": 3, "vtxos": []}],
        ('POST', '/api/v1/onchain/addresses/next'): {"address": "tb1pfreshaddress"},
        ('POST', '/api/v1/wallet/bip321'): {
            "bip321": "bitcoin:tb1pfallback?ark=tark1abc&lightning=lntbs1xyz",
            "ark": "tark1abc", "bolt11": "lntbs1xyz", "onchain": "tb1pfallback"},
        ('POST', '/api/v1/wallet/send'): {"message": "payment sent", "payment_hash": None},
        ('POST', '/api/v1/wallet/send-onchain'): {"offboard_txid": TXID_OFFBOARD},
        ('POST', '/api/v1/boards/board-all'): {
            "amount_sat": 9000, "funding_tx": {"tx": "00", "txid": TXID_BOARD},
            "movement_id": 3, "vtxos": []},
        ('POST', '/api/v1/boards/board-amount'): {
            "amount_sat": 500, "funding_tx": {"tx": "00", "txid": TXID_BOARD},
            "movement_id": 4, "vtxos": []},
        ('POST', '/api/v1/wallet/create'): {"fingerprint": "deadbeef"},
    }


class MockBarkd:
    def __init__(self, token=TOKEN):
        self.token = token          # token accettato
        self.has_wallet = True      # False -> 422 "No wallet set" (tranne /wallet/create)
        self.routes = default_routes()
        self.fail = {}              # (metodo, path) -> (status, testo del corpo)
        self.requests = []          # una dict per richiesta ricevuta
        self._lock = threading.Lock()

        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                length = int(self.headers.get('Content-Length') or 0)
                raw = self.rfile.read(length).decode() if length else ''
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw
                path = self.path.split('?')[0]
                with mock._lock:
                    mock.requests.append({
                        'method': self.command, 'path': path, 'body': body,
                        'auth': self.headers.get('Authorization')})
                status, payload = mock._answer(self.command, path,
                                               self.headers.get('Authorization'))
                data = payload if isinstance(payload, str) else json.dumps(payload)
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(data.encode())

            do_GET = do_POST = do_PUT = do_DELETE = _handle

        self._server = HTTPServer(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True)
        self._thread.start()

    def _answer(self, method, path, auth):
        if auth != f'Bearer {self.token}':
            return 401, 'Unauthorized'
        key = (method, path)
        if key in self.fail:
            return self.fail[key]
        if not self.has_wallet and path != '/api/v1/wallet/create':
            return 422, json.dumps({"message": "No wallet set"})
        if key in self.routes:
            return 200, self.routes[key]
        return 404, 'not found'

    @property
    def url(self):
        return f'http://127.0.0.1:{self._server.server_port}'

    def calls(self, method=None, path=None):
        """Richieste ricevute, filtrabili per metodo e/o suffisso del path."""
        return [r for r in self.requests
                if (method is None or r['method'] == method)
                and (path is None or r['path'].endswith(path))]

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
