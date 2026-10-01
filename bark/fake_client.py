import time

from .client import BarkNoWallet, BarkUnavailable


class FakeBarkClient:
    """Stessa interfaccia di BarkClient, dati finti: sviluppo GUI senza barkd né fondi.

    scenario: 'ok' | 'no_wallet' | 'down'
    Il campo `balances` si può cambiare a mano per simulare la fase "con fondi".
    """

    def __init__(self, scenario='no_wallet'):
        self.scenario = scenario
        self.balances = dict(ark=0, pending_board=0, oc_confirmed=0, oc_spendable=0)

    def sync(self):
        time.sleep(0.3)

    def snapshot(self, sync=False):
        time.sleep(0.2)  # simula latenza di rete
        if self.scenario == 'down':
            raise BarkUnavailable("fake: barkd spento")
        if self.scenario == 'no_wallet':
            raise BarkNoWallet()
        b = self.balances
        return {
            'connected': True,
            'ark_address': 'tark1qfakefakefakefakefakefakefakefakefakefake',
            'ark_spendable_sat': b['ark'],
            'ark_pending_board_sat': b['pending_board'],
            'onchain_address': 'tb1qfakefakefakefakefakefakefakefakefake',
            'onchain_confirmed_sat': b['oc_confirmed'],
            'onchain_spendable_sat': b['oc_spendable'],
        }

    def create_wallet(self):
        time.sleep(0.3)
        self.scenario = 'ok'
