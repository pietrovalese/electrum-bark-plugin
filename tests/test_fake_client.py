import pytest

from bark.client import BarkError, BarkNoWallet, BarkUnavailable
from bark.fake_client import FakeBarkClient, BOARD_CONFIRM_REFRESHES, FAUCET_SAT


@pytest.fixture(autouse=True)
def no_latency(monkeypatch):
    """Il client finto simula la latenza con time.sleep: nei test non serve."""
    import time
    import types
    monkeypatch.setattr('bark.fake_client.time',
                        types.SimpleNamespace(sleep=lambda s: None, time=time.time))


@pytest.fixture
def funded():
    """Client finto con wallet creato e fondi on-chain confermati."""
    c = FakeBarkClient('no_wallet')
    c.create_wallet()
    c.faucet()
    return c


def test_no_wallet_then_create():
    c = FakeBarkClient('no_wallet')
    with pytest.raises(BarkNoWallet):
        c.snapshot()
    c.create_wallet()
    assert c.snapshot()['ark_spendable_sat'] == 0


def test_down():
    with pytest.raises(BarkUnavailable):
        FakeBarkClient('down').snapshot()


def test_every_wallet_method_requires_a_wallet():
    c = FakeBarkClient('no_wallet')
    for call in (c.history, c.new_onchain_address, c.board_all, c.receive_uri,
                 c.faucet, lambda: c.board_amount(1), lambda: c.send('tark1x', 1),
                 lambda: c.send_onchain('tb1qxxxxxxxxxxxxxx', 1)):
        with pytest.raises(BarkNoWallet):
            call()


def test_faucet_adds_confirmed_onchain_funds(funded):
    snap = funded.snapshot()
    assert snap['onchain_confirmed_sat'] == FAUCET_SAT
    assert snap['onchain_spendable_sat'] == FAUCET_SAT


def test_board_goes_pending_then_spendable_after_refreshes(funded):
    res = funded.board_all()
    assert res['amount_sat'] == FAUCET_SAT and len(res['txid']) == 64
    snap = funded.snapshot()   # prima lettura dopo il board: ancora in attesa
    assert snap['onchain_confirmed_sat'] == 0
    assert snap['ark_pending_board_sat'] == FAUCET_SAT and snap['ark_spendable_sat'] == 0
    assert len(funded.pending_boards()) == 1
    for _ in range(BOARD_CONFIRM_REFRESHES - 1):
        snap = funded.snapshot()
    assert snap['ark_pending_board_sat'] == 0 and snap['ark_spendable_sat'] == FAUCET_SAT
    assert funded.pending_boards() == []


def test_board_amount_partial_and_limits(funded):
    funded.board_amount(30_000)
    assert funded.snapshot()['onchain_confirmed_sat'] == FAUCET_SAT - 30_000
    with pytest.raises(BarkError):
        funded.board_amount(FAUCET_SAT)        # più di quanto resta
    with pytest.raises(BarkError):
        funded.board_amount(0)


def test_board_all_without_funds_fails():
    c = FakeBarkClient('no_wallet')
    c.create_wallet()
    with pytest.raises(BarkError):
        c.board_all()


def _spendable(c):
    c.board_all()
    for _ in range(BOARD_CONFIRM_REFRESHES):
        c.snapshot()
    return c


def test_send_ark_reduces_balance_and_appears_in_history(funded):
    _spendable(funded)
    funded.send('tark1qdestination', 2_500)
    assert funded.snapshot()['ark_spendable_sat'] == FAUCET_SAT - 2_500
    top = funded.history()[0]
    assert top['type'] == 'send' and top['amount_sat'] == -2_500
    assert top['counterparty'] == 'tark1qdestination'


def test_send_lightning_charges_a_fee(funded):
    _spendable(funded)
    funded.send('lntbs1fakeinvoice', 10_000)
    top = funded.history()[0]
    assert top['fee_sat'] > 0 and top['amount_sat'] == -(10_000 + top['fee_sat'])


def test_send_errors(funded):
    _spendable(funded)
    with pytest.raises(BarkError):
        funded.send('tark1qdest')                       # importo mancante per Ark
    with pytest.raises(BarkError):
        funded.send('not-a-destination', 10)
    with pytest.raises(BarkError):
        funded.send('tark1qdest', FAUCET_SAT + 1)       # saldo insufficiente
    with pytest.raises(BarkError):
        funded.send('', 10)


def test_send_onchain_pays_fee_and_validates(funded):
    _spendable(funded)
    res = funded.send_onchain('tb1qfakefakefakefakefake', 1_000)
    assert len(res['txid']) == 64
    top = funded.history()[0]
    assert top['type'] == 'offboard' and top['amount_sat'] < -1_000
    with pytest.raises(BarkError):
        funded.send_onchain('tark1qnotonchain', 1_000)
    with pytest.raises(BarkError):
        funded.send_onchain('tb1qfakefakefakefakefake', None)


def test_history_newest_first_and_board_completes(funded):
    _spendable(funded)
    funded.send('tark1qdest', 100)
    rows = funded.history()
    assert [r['type'] for r in rows] == ['send', 'board']
    assert rows[1]['status'] == 'successful'      # il board è confermato


def test_receive_uri_shapes(funded):
    with_amount = funded.receive_uri(5_000, 'cena', 'grazie mille', onchain=True)
    assert with_amount['ark'].startswith('tark1') and with_amount['bolt11']
    assert with_amount['onchain'].startswith('tb1')
    uri = with_amount['bip321']
    assert uri.startswith('bitcoin:') and 'amount=0.00005000' in uri
    assert 'label=cena' in uri and 'message=grazie%20mille' in uri

    no_amount = funded.receive_uri(onchain=False)
    assert no_amount['bolt11'] is None and no_amount['onchain'] is None
    assert no_amount['ark'] != with_amount['ark']        # indirizzi sempre nuovi


def test_new_onchain_addresses_are_distinct(funded):
    assert funded.new_onchain_address() != funded.new_onchain_address()
