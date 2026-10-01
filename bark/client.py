import json
import os

import barkd_client
from barkd_client import (
    Configuration, WalletApi, OnchainApi, BoardsApi, HistoryApi,
    CreateWalletRequest, ChainSourceConfig, ChainSourceConfigOneOf1,
    ChainSourceConfigOneOf1Esplora, BarkNetwork,
    Bip321UriRequest, BoardRequest, SendRequest, SendOnchainRequest,
)
from barkd_client.exceptions import ApiException, OpenApiException
from pydantic import ValidationError
from urllib3.exceptions import HTTPError

DEFAULT_HOST = 'http://localhost:3001'
SIGNET_ARK_SERVER = 'https://ark.signet.2nd.dev'
SIGNET_ESPLORA = 'https://esplora.signet.2nd.dev'

# timeout in secondi per tipo di operazione
READ_TIMEOUT = 15      # letture semplici (saldi, history, indirizzi)
ACTION_TIMEOUT = 60    # board / send / bip321 (possono passare da un round Ark)
SYNC_TIMEOUT = 90      # sync con la chain / creazione wallet


class BarkError(Exception):
    """Errore generico da barkd (il messaggio è quello di barkd)."""


class BarkUnavailable(BarkError):
    """barkd non raggiungibile (spento, host sbagliato, timeout...)."""


class BarkNoWallet(BarkError):
    """barkd è su ma non ha ancora un wallet."""

    def __init__(self, msg="barkd has no wallet yet"):
        super().__init__(msg)


def _detail(body) -> str:
    """Estrae un messaggio leggibile dal corpo di una risposta di errore."""
    if not body:
        return ''
    text = body if isinstance(body, str) else str(body)
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        for key in ('message', 'error', 'detail'):
            if data.get(key):
                return str(data[key])
    return text


def _call(fn):
    """Esegue fn() traducendo le eccezioni di barkd_client/urllib3 nelle nostre."""
    try:
        return fn()
    except ApiException as e:
        if "No wallet set" in str(e.body):
            raise BarkNoWallet() from e
        if e.status == 401:
            raise BarkError("Unauthorized: wrong or missing barkd token") from e
        raise BarkError(f"barkd error {e.status}: {_detail(e.body)}") from e
    except (HTTPError, OSError) as e:
        raise BarkUnavailable(str(e)) from e
    except (OpenApiException, ValidationError) as e:
        # risposta di barkd con una forma diversa da quella attesa dal client
        raise BarkError(f"Unexpected response from barkd: {e}") from e


def _check_amount(amount, *, required=False, name='amount'):
    """Valida un importo in sat: None (se non richiesto) oppure intero > 0."""
    if amount is None:
        if required:
            raise BarkError(f"Missing {name}.")
        return None
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise BarkError(f"Invalid {name}: must be a positive whole number of sat.")
    return amount


def _check_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise BarkError(f"Missing {name}.")
    return value.strip()


def _movement_to_dict(m) -> dict:
    """Movement di barkd -> dict semplice (stessa forma in FakeBarkClient.history)."""
    if m.sent_to:
        counterparty = m.sent_to[0].destination.value
    elif m.received_on:
        counterparty = m.received_on[0].destination.value
    else:
        counterparty = ''
    status = m.status.value if hasattr(m.status, 'value') else str(m.status)
    return {
        'id': m.id,
        'time': int(m.time.created_at.timestamp()),
        'type': m.subsystem.kind or m.subsystem.name,
        'status': status,
        'amount_sat': m.effective_balance_sat,   # con segno: negativo = uscita
        'fee_sat': m.offchain_fee_sat,
        'counterparty': counterparty,
    }


class BarkClient:
    def __init__(self, host=None, token=None):
        self.host = host or os.environ.get('BARKD_HOST', DEFAULT_HOST)
        self.token = token or os.environ.get('BARKD_TOKEN')

    def _api(self):
        if not self.token:
            raise BarkError(
                "barkd token missing: set it in the plugin Settings "
                "or export BARKD_TOKEN before starting Electrum.")
        return barkd_client.ApiClient(
            Configuration(host=self.host, access_token=self.token))

    # --- lettura (mai effetti collaterali: niente generazione di indirizzi) ---
    def snapshot(self, sync: bool = False) -> dict:
        """Lettura unica per la GUI. sync=True allinea prima con la chain (lento).

        Solo letture: gli endpoint degli indirizzi di barkd ne creano uno nuovo a ogni
        chiamata, quindi qui non vengono mai usati (vedi new_onchain_address/receive_uri).
        """
        def run():
            with self._api() as c:
                wallet, onchain = WalletApi(c), OnchainApi(c)
                ark_bal = wallet.balance(_request_timeout=READ_TIMEOUT)  # alza BarkNoWallet
                if sync:
                    onchain.onchain_sync(_request_timeout=SYNC_TIMEOUT)
                    ark_bal = wallet.balance(_request_timeout=READ_TIMEOUT)
                oc_bal = onchain.onchain_balance(_request_timeout=READ_TIMEOUT)
                connected = wallet.connected(_request_timeout=READ_TIMEOUT).connected
                return {
                    'connected': connected,
                    'ark_spendable_sat': ark_bal.spendable_sat,
                    'ark_pending_board_sat': ark_bal.pending_board_sat,
                    'onchain_confirmed_sat': oc_bal.confirmed_sat,
                    'onchain_spendable_sat': oc_bal.trusted_spendable_sat,
                    'onchain_pending_sat':
                        oc_bal.trusted_pending_sat + oc_bal.untrusted_pending_sat,
                }
        return _call(run)

    def sync(self):
        def run():
            with self._api() as c:
                OnchainApi(c).onchain_sync(_request_timeout=SYNC_TIMEOUT)
        _call(run)

    def history(self) -> list:
        """Movimenti di barkd, dal più recente: lista di dict (vedi _movement_to_dict)."""
        def run():
            with self._api() as c:
                moves = HistoryApi(c).list(_request_timeout=READ_TIMEOUT)
                return [_movement_to_dict(m) for m in moves]
        rows = _call(run)
        rows.sort(key=lambda r: (r['time'], r['id']), reverse=True)
        return rows

    def pending_boards(self) -> list:
        """Board in attesa di conferma (disponibile, non ancora mostrato nella GUI)."""
        def run():
            with self._api() as c:
                infos = BoardsApi(c).get_pending_boards(_request_timeout=READ_TIMEOUT)
                return [{'amount_sat': i.amount_sat, 'txid': i.funding_tx.txid,
                         'movement_id': i.movement_id} for i in infos]
        return _call(run)

    # --- indirizzi / richieste di pagamento (ogni chiamata ne crea di nuovi) ---
    def new_onchain_address(self) -> str:
        """Nuovo indirizzo on-chain del wallet barkd (per finanziarlo da Electrum)."""
        def run():
            with self._api() as c:
                return OnchainApi(c).onchain_address(_request_timeout=READ_TIMEOUT).address
        return _call(run)

    def receive_uri(self, amount_sat=None, label=None, message=None, onchain=True) -> dict:
        """URI BIP 321 con indirizzo Ark, invoice Lightning e (opz.) fallback on-chain.

        Ritorna {'bip321', 'ark', 'bolt11', 'onchain'}: i campi opzionali possono essere None.
        """
        amount_sat = _check_amount(amount_sat)
        req = Bip321UriRequest(
            amount_sat=amount_sat,
            label=(label or '').strip() or None,
            message=(message or '').strip() or None,
            onchain=bool(onchain),
        )

        def run():
            with self._api() as c:
                r = WalletApi(c).bip321_uri(req, _request_timeout=ACTION_TIMEOUT)
                return {'bip321': r.bip321, 'ark': r.ark,
                        'bolt11': r.bolt11, 'onchain': r.onchain}
        return _call(run)

    # --- azioni ---
    def create_wallet(self):
        """Crea il wallet barkd su signet (stessa logica di smoke_test.py)."""
        def run():
            with self._api() as c:
                WalletApi(c).create_wallet(CreateWalletRequest(
                    ark_server=SIGNET_ARK_SERVER,
                    chain_source=ChainSourceConfig(
                        actual_instance=ChainSourceConfigOneOf1(
                            esplora=ChainSourceConfigOneOf1Esplora(url=SIGNET_ESPLORA))),
                    network=BarkNetwork.SIGNET,
                ), _request_timeout=SYNC_TIMEOUT)
        _call(run)

    @staticmethod
    def _board_result(info) -> dict:
        return {'amount_sat': info.amount_sat, 'txid': info.funding_tx.txid,
                'movement_id': info.movement_id}

    def board_all(self) -> dict:
        """Porta in Ark tutti i fondi on-chain di barkd."""
        def run():
            with self._api() as c:
                return self._board_result(
                    BoardsApi(c).board_all(_request_timeout=ACTION_TIMEOUT))
        return _call(run)

    def board_amount(self, amount_sat: int) -> dict:
        """Porta in Ark un importo preciso dei fondi on-chain di barkd."""
        amount_sat = _check_amount(amount_sat, required=True)

        def run():
            with self._api() as c:
                return self._board_result(BoardsApi(c).board_amount(
                    BoardRequest(amount_sat=amount_sat), _request_timeout=ACTION_TIMEOUT))
        return _call(run)

    def send(self, destination: str, amount_sat=None, comment=None) -> dict:
        """Paga un indirizzo Ark, un'invoice/offer BOLT12/indirizzo Lightning.

        amount_sat può mancare solo se la destinazione contiene già un importo.
        """
        destination = _check_text(destination, 'destination')
        amount_sat = _check_amount(amount_sat)
        req = SendRequest(destination=destination, amount_sat=amount_sat,
                          comment=(comment or '').strip() or None)

        def run():
            with self._api() as c:
                r = WalletApi(c).send(req, _request_timeout=ACTION_TIMEOUT)
                return {'message': r.message, 'payment_hash': r.payment_hash}
        return _call(run)

    def send_onchain(self, destination: str, amount_sat: int) -> dict:
        """Paga un indirizzo on-chain dal saldo Ark (con la cooperazione del server)."""
        destination = _check_text(destination, 'destination')
        amount_sat = _check_amount(amount_sat, required=True)
        req = SendOnchainRequest(destination=destination, amount_sat=amount_sat)

        def run():
            with self._api() as c:
                r = WalletApi(c).send_onchain(req, _request_timeout=ACTION_TIMEOUT)
                return {'txid': r.offboard_txid}
        return _call(run)
