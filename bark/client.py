import os

import barkd_client
from barkd_client import (
    Configuration, WalletApi, OnchainApi,
    CreateWalletRequest, ChainSourceConfig, ChainSourceConfigOneOf1,
    ChainSourceConfigOneOf1Esplora, BarkNetwork,
)
from barkd_client.exceptions import ApiException
from urllib3.exceptions import HTTPError

DEFAULT_HOST = 'http://localhost:3001'
SIGNET_ARK_SERVER = 'https://ark.signet.2nd.dev'
SIGNET_ESPLORA = 'https://esplora.signet.2nd.dev'


class BarkError(Exception):
    """Errore generico da barkd."""


class BarkUnavailable(BarkError):
    """barkd non raggiungibile (spento, host sbagliato...)."""


class BarkNoWallet(BarkError):
    """barkd è su ma non ha ancora un wallet."""


def _call(fn):
    """Esegue fn() traducendo le eccezioni di barkd_client/urllib3 nelle nostre."""
    try:
        return fn()
    except ApiException as e:
        if "No wallet set" in str(e.body):
            raise BarkNoWallet() from e
        raise BarkError(f"barkd {e.status}: {e.body}") from e
    except (HTTPError, OSError) as e:
        raise BarkUnavailable(str(e)) from e


class BarkClient:
    def __init__(self, host=None, token=None):
        self.host = host or os.environ.get('BARKD_HOST', DEFAULT_HOST)
        self.token = token or os.environ.get('BARKD_TOKEN')

    def _api(self):
        if not self.token:
            raise BarkError("Token barkd mancante (Impostazioni del plugin).")
        return barkd_client.ApiClient(
            Configuration(host=self.host, access_token=self.token))

    def sync(self):
        with self._api() as c:
            _call(lambda: OnchainApi(c).onchain_sync())

    def snapshot(self, sync: bool = False) -> dict:
        """Lettura unica per la GUI. sync=True allinea prima con la chain (lento)."""
        def run():
            with self._api() as c:
                wallet, onchain = WalletApi(c), OnchainApi(c)
                ark_address = wallet.address().address  # alza BarkNoWallet se manca
                if sync:
                    onchain.onchain_sync()
                ark_bal = wallet.balance()
                oc_bal = onchain.onchain_balance()
                return {
                    'connected': wallet.connected().connected,
                    'ark_address': ark_address,
                    'ark_spendable_sat': ark_bal.spendable_sat,
                    'ark_pending_board_sat': ark_bal.pending_board_sat,
                    'onchain_address': onchain.onchain_address().address,
                    'onchain_confirmed_sat': oc_bal.confirmed_sat,
                    'onchain_spendable_sat': oc_bal.trusted_spendable_sat,
                }
        return _call(run)

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
                ))
        _call(run)
