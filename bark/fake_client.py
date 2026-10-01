import hashlib
import threading
import time
from urllib.parse import quote

from .client import BarkError, BarkNoWallet, BarkUnavailable

FAUCET_SAT = 100_000
BOARD_CONFIRM_REFRESHES = 2   # snapshot() necessari perché un board diventi spendibile
LN_FEE_PPM = 1000             # commissione finta Lightning: 0.1%
ONCHAIN_FEE_SAT = 200         # commissione finta per pagare on-chain dal saldo Ark
FAKE_INVOICE_SAT = 1_000      # importo "contenuto" nelle invoice finte senza importo esplicito


def _check_amount(amount, *, required=False):
    if amount is None:
        if required:
            raise BarkError("Missing amount.")
        return None
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise BarkError("Invalid amount: must be a positive whole number of sat.")
    return amount


def _fake_txid(n: int) -> str:
    return hashlib.sha256(f'fake-tx-{n}'.encode()).hexdigest()


class FakeBarkClient:
    """Stessa interfaccia di BarkClient, dati finti: sviluppo GUI senza barkd né fondi.

    scenario: 'ok' | 'no_wallet' | 'down'
    Stato in memoria: parte senza wallet; create_wallet() -> faucet() -> board ->
    (dopo BOARD_CONFIRM_REFRESHES snapshot) fondi Ark spendibili -> send -> history.
    Il campo `balances` si può anche cambiare a mano per simulare la fase "con fondi".
    """

    def __init__(self, scenario='no_wallet'):
        self.scenario = scenario
        self.balances = dict(ark=0, pending_board=0, oc_confirmed=0, oc_spendable=0)
        self._lock = threading.RLock()   # la GUI chiama da thread worker diversi
        self._boards = []                # board in attesa: dict con 'ticks' residui
        self._moves = []                 # movimenti, dal più vecchio al più recente
        self._counter = 0

    # --- helper interni (da chiamare con il lock preso) ---
    def _require_wallet(self):
        if self.scenario == 'down':
            raise BarkUnavailable("fake: barkd is switched off")
        if self.scenario == 'no_wallet':
            raise BarkNoWallet()

    def _next(self) -> int:
        self._counter += 1
        return self._counter

    def _add_move(self, kind, status, amount_sat, fee_sat=0, counterparty='') -> dict:
        move = {'id': self._next(), 'time': int(time.time()), 'type': kind,
                'status': status, 'amount_sat': amount_sat, 'fee_sat': fee_sat,
                'counterparty': counterparty}
        self._moves.append(move)
        return move

    def _tick(self):
        """Ogni snapshot fa avanzare i board in attesa; a 0 diventano spendibili."""
        for board in list(self._boards):
            board['ticks'] -= 1
            if board['ticks'] <= 0:
                amt = board['amount_sat']
                self.balances['pending_board'] -= amt
                self.balances['ark'] += amt
                board['move']['status'] = 'successful'
                self._boards.remove(board)

    def _board(self, amount_sat: int) -> dict:
        b = self.balances
        b['oc_confirmed'] -= amount_sat
        b['oc_spendable'] -= amount_sat
        b['pending_board'] += amount_sat
        move = self._add_move('board', 'pending', amount_sat, 0, '')
        txid = _fake_txid(move['id'])
        self._boards.append({'amount_sat': amount_sat, 'txid': txid,
                             'movement_id': move['id'], 'ticks': BOARD_CONFIRM_REFRESHES,
                             'move': move})
        return {'amount_sat': amount_sat, 'txid': txid, 'movement_id': move['id']}

    def _spend_ark(self, total_sat: int):
        if total_sat > self.balances['ark']:
            raise BarkError("Insufficient Ark balance.")
        self.balances['ark'] -= total_sat

    # --- stessa interfaccia di BarkClient ---
    def sync(self):
        time.sleep(0.3)
        with self._lock:
            self._require_wallet()
            self._tick()

    def snapshot(self, sync=False):
        time.sleep(0.5 if sync else 0.2)  # simula latenza di rete
        with self._lock:
            self._require_wallet()
            self._tick()
            b = self.balances
            return {
                'connected': True,
                'ark_spendable_sat': b['ark'],
                'ark_pending_board_sat': b['pending_board'],
                'onchain_confirmed_sat': b['oc_confirmed'],
                'onchain_spendable_sat': b['oc_spendable'],
                'onchain_pending_sat': 0,
            }

    def create_wallet(self):
        time.sleep(0.3)
        with self._lock:
            if self.scenario == 'down':
                raise BarkUnavailable("fake: barkd is switched off")
            self.scenario = 'ok'

    def faucet(self, amount_sat: int = FAUCET_SAT):
        """Solo fake: simula l'arrivo di fondi on-chain confermati nel wallet barkd."""
        time.sleep(0.2)
        with self._lock:
            self._require_wallet()
            self.balances['oc_confirmed'] += amount_sat
            self.balances['oc_spendable'] += amount_sat

    def new_onchain_address(self) -> str:
        time.sleep(0.1)
        with self._lock:
            self._require_wallet()
            return f'tb1qfakefakefakefakefakefake{self._next():06d}'

    def receive_uri(self, amount_sat=None, label=None, message=None, onchain=True) -> dict:
        time.sleep(0.2)
        amount_sat = _check_amount(amount_sat)
        with self._lock:
            self._require_wallet()
            n = self._next()
            ark = f'tark1qfakefakefakefakefakefakefake{n:06d}'
            # come probabile barkd reale: l'invoice Lightning solo se c'è un importo
            bolt11 = f'lntbsfakeinvoice{n:06d}fakefakefake' if amount_sat else None
            oc = f'tb1qfakefakefakefakefakefake{n:06d}' if onchain else None
            params = [f'ark={ark}']
            if bolt11:
                params.append(f'lightning={bolt11}')
            if amount_sat:
                params.append(f'amount={amount_sat / 1e8:.8f}')
            if label and label.strip():
                params.append(f'label={quote(label.strip())}')
            if message and message.strip():
                params.append(f'message={quote(message.strip())}')
            uri = f'bitcoin:{oc or ""}?' + '&'.join(params)
            return {'bip321': uri, 'ark': ark, 'bolt11': bolt11, 'onchain': oc}

    def history(self) -> list:
        time.sleep(0.1)
        with self._lock:
            self._require_wallet()
            return [dict(m) for m in reversed(self._moves)]   # più recente per primo

    def pending_boards(self) -> list:
        with self._lock:
            self._require_wallet()
            return [{'amount_sat': b['amount_sat'], 'txid': b['txid'],
                     'movement_id': b['movement_id']} for b in self._boards]

    def board_all(self) -> dict:
        time.sleep(0.3)
        with self._lock:
            self._require_wallet()
            amount = self.balances['oc_spendable']
            if amount <= 0:
                raise BarkError("No confirmed on-chain funds to board.")
            return self._board(amount)

    def board_amount(self, amount_sat: int) -> dict:
        amount_sat = _check_amount(amount_sat, required=True)
        time.sleep(0.3)
        with self._lock:
            self._require_wallet()
            if amount_sat > self.balances['oc_spendable']:
                raise BarkError("Insufficient confirmed on-chain funds.")
            return self._board(amount_sat)

    def send(self, destination: str, amount_sat=None, comment=None) -> dict:
        if not isinstance(destination, str) or not destination.strip():
            raise BarkError("Missing destination.")
        dest = destination.strip()
        amount_sat = _check_amount(amount_sat)
        low = dest.lower()
        is_ln = low.startswith(('ln', 'lightning:')) or '@' in dest
        is_ark = low.startswith(('tark1', 'ark1'))
        if not (is_ln or is_ark):
            raise BarkError(f"Unrecognized destination: {dest[:40]}")
        if amount_sat is None:
            # le invoice "contengono" l'importo; per Ark e indirizzi Lightning serve
            if low.startswith(('lnbc', 'lntb', 'lno1')):
                amount_sat = FAKE_INVOICE_SAT
            else:
                raise BarkError("Missing amount.")
        fee = max(1, amount_sat * LN_FEE_PPM // 1_000_000) if is_ln else 0
        time.sleep(0.4)
        with self._lock:
            self._require_wallet()
            self._spend_ark(amount_sat + fee)
            move = self._add_move('send', 'successful', -(amount_sat + fee), fee, dest)
            payment_hash = hashlib.sha256(f'fake-pay-{move["id"]}'.encode()).hexdigest()
            return {'message': 'Fake payment sent',
                    'payment_hash': payment_hash if is_ln else None}

    def send_onchain(self, destination: str, amount_sat: int) -> dict:
        if not isinstance(destination, str) or not destination.strip():
            raise BarkError("Missing destination.")
        dest = destination.strip()
        amount_sat = _check_amount(amount_sat, required=True)
        if dest.lower().startswith(('ln', 'tark1', 'ark1')) or len(dest) < 14:
            raise BarkError(f"Not an on-chain address: {dest[:40]}")
        time.sleep(0.4)
        with self._lock:
            self._require_wallet()
            self._spend_ark(amount_sat + ONCHAIN_FEE_SAT)
            move = self._add_move('offboard', 'successful', -(amount_sat + ONCHAIN_FEE_SAT),
                                  ONCHAIN_FEE_SAT, dest)
            return {'txid': _fake_txid(move['id'])}
