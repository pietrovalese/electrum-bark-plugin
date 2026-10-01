import pytest
from bark.client import BarkNoWallet, BarkUnavailable
from bark.fake_client import FakeBarkClient


def test_no_wallet_then_create():
    c = FakeBarkClient('no_wallet')
    with pytest.raises(BarkNoWallet):
        c.snapshot()
    c.create_wallet()
    assert c.snapshot()['ark_spendable_sat'] == 0


def test_down():
    with pytest.raises(BarkUnavailable):
        FakeBarkClient('down').snapshot()
