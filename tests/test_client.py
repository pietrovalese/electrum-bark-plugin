"""BarkClient reale (con la vera libreria barkd_client) contro il mock HTTP di barkd."""
import pytest

from bark.client import BarkClient, BarkError, BarkNoWallet, BarkUnavailable
from mock_barkd import MockBarkd, TOKEN, TXID_BOARD, TXID_OFFBOARD


@pytest.fixture
def barkd():
    mock = MockBarkd()
    yield mock
    mock.stop()


@pytest.fixture
def client(barkd):
    return BarkClient(host=barkd.url, token=TOKEN)


# --------------------------------------------------------------------------- letture
def test_snapshot_parses_balances(client):
    snap = client.snapshot()
    assert snap == {
        'connected': True,
        'ark_spendable_sat': 5000,
        'ark_pending_board_sat': 300,
        'onchain_confirmed_sat': 9000,
        'onchain_spendable_sat': 9000,
        'onchain_pending_sat': 150,   # trusted 100 + untrusted 50
    }


def test_snapshot_without_sync_does_not_sync(client, barkd):
    client.snapshot(sync=False)
    assert not barkd.calls('POST', '/onchain/sync')


def test_snapshot_with_sync_syncs_before_reading_balances(client, barkd):
    client.snapshot(sync=True)
    paths = [r['path'] for r in barkd.requests]
    assert '/api/v1/onchain/sync' in paths
    assert paths.index('/api/v1/onchain/sync') < paths.index('/api/v1/onchain/balance')


def test_polling_never_creates_addresses(client, barkd):
    """Gli endpoint degli indirizzi di barkd ne generano uno nuovo a ogni chiamata."""
    client.snapshot()
    client.snapshot(sync=True)
    client.history()
    assert not [r for r in barkd.requests if 'addresses' in r['path'] or 'bip321' in r['path']]


def test_every_request_carries_the_bearer_token(client, barkd):
    client.snapshot()
    client.history()
    assert barkd.requests
    assert all(r['auth'] == f'Bearer {TOKEN}' for r in barkd.requests)


def test_history_is_parsed_and_sorted_newest_first(client):
    rows = client.history()
    assert [r['id'] for r in rows] == [8, 7]
    sent = rows[1]
    assert sent['type'] == 'send' and sent['status'] == 'successful'
    assert sent['amount_sat'] == -1500 and sent['fee_sat'] == 5
    assert sent['counterparty'] == 'tark1dest'
    assert isinstance(sent['time'], int)
    received = rows[0]
    assert received['amount_sat'] == 2000 and received['status'] == 'pending'
    assert received['counterparty'] == 'tark1mine'


def test_pending_boards(client):
    assert client.pending_boards() == [
        {'amount_sat': 300, 'txid': TXID_BOARD, 'movement_id': 3}]


def test_new_onchain_address(client, barkd):
    assert client.new_onchain_address() == 'tb1pfreshaddress'
    assert len(barkd.calls('POST', '/onchain/addresses/next')) == 1


# --------------------------------------------------------------------------- azioni
def test_receive_uri_sends_all_fields_and_returns_parts(client, barkd):
    res = client.receive_uri(5000, ' cena ', 'grazie', onchain=False)
    assert res == {'bip321': 'bitcoin:tb1pfallback?ark=tark1abc&lightning=lntbs1xyz',
                   'ark': 'tark1abc', 'bolt11': 'lntbs1xyz', 'onchain': 'tb1pfallback'}
    body = barkd.calls('POST', '/wallet/bip321')[0]['body']
    assert body['amount_sat'] == 5000
    assert body['label'] == 'cena' and body['message'] == 'grazie'
    assert body['onchain'] is False


def test_receive_uri_without_optional_fields(client, barkd):
    client.receive_uri()
    body = barkd.calls('POST', '/wallet/bip321')[0]['body']
    assert body.get('amount_sat') is None
    assert body.get('label') is None and body.get('message') is None
    assert body['onchain'] is True


def test_receive_uri_optional_fields_may_be_missing_in_response(client, barkd):
    barkd.routes[('POST', '/api/v1/wallet/bip321')] = {"bip321": "bitcoin:?ark=tark1abc"}
    res = client.receive_uri()
    assert res['ark'] is None and res['bolt11'] is None and res['onchain'] is None
    assert res['bip321'] == 'bitcoin:?ark=tark1abc'


def test_send_request_body(client, barkd):
    res = client.send(' tark1dest ', 250, 'ciao')
    assert res == {'message': 'payment sent', 'payment_hash': None}
    body = barkd.calls('POST', '/wallet/send')[0]['body']
    assert body['destination'] == 'tark1dest'
    assert body['amount_sat'] == 250 and body['comment'] == 'ciao'


def test_send_without_amount_for_invoices(client, barkd):
    client.send('lntbs1invoice')
    body = barkd.calls('POST', '/wallet/send')[0]['body']
    assert body['destination'] == 'lntbs1invoice' and body.get('amount_sat') is None


def test_send_onchain_request_body_and_result(client, barkd):
    assert client.send_onchain('tb1paddr', 700) == {'txid': TXID_OFFBOARD}
    body = barkd.calls('POST', '/wallet/send-onchain')[0]['body']
    assert body == {'destination': 'tb1paddr', 'amount_sat': 700}


def test_board_all_and_board_amount(client, barkd):
    assert client.board_all() == {'amount_sat': 9000, 'txid': TXID_BOARD, 'movement_id': 3}
    assert barkd.calls('POST', '/boards/board-all')
    assert client.board_amount(500) == {'amount_sat': 500, 'txid': TXID_BOARD, 'movement_id': 4}
    assert barkd.calls('POST', '/boards/board-amount')[0]['body'] == {'amount_sat': 500}


def test_create_wallet_targets_signet(client, barkd):
    barkd.has_wallet = False       # /wallet/create deve funzionare anche senza wallet
    client.create_wallet()
    body = barkd.calls('POST', '/wallet/create')[0]['body']
    assert body['network'] == 'signet'
    assert body['ark_server'] == 'https://ark.signet.2nd.dev'
    assert 'https://esplora.signet.2nd.dev' in str(body['chain_source'])


def test_sync(client, barkd):
    client.sync()
    assert len(barkd.calls('POST', '/onchain/sync')) == 1


# --------------------------------------------------------------------------- errori
def test_no_wallet_is_mapped(client, barkd):
    barkd.has_wallet = False
    for call in (client.snapshot, client.history, client.new_onchain_address,
                 client.board_all, lambda: client.send('tark1x', 1)):
        with pytest.raises(BarkNoWallet):
            call()


def test_wrong_token_gives_clear_message(barkd):
    bad = BarkClient(host=barkd.url, token='wrong')
    with pytest.raises(BarkError, match='Unauthorized') as exc:
        bad.snapshot()
    assert not isinstance(exc.value, (BarkNoWallet, BarkUnavailable))


def test_missing_token(barkd, monkeypatch):
    monkeypatch.delenv('BARKD_TOKEN', raising=False)
    with pytest.raises(BarkError, match='token'):
        BarkClient(host=barkd.url, token=None).snapshot()
    assert not barkd.requests          # nessuna richiesta senza token


def test_token_and_host_fall_back_to_environment(barkd, monkeypatch):
    monkeypatch.setenv('BARKD_TOKEN', TOKEN)
    monkeypatch.setenv('BARKD_HOST', barkd.url)
    assert BarkClient().snapshot()['ark_spendable_sat'] == 5000


def test_unreachable_server():
    # porta 1: connessione rifiutata
    with pytest.raises(BarkUnavailable):
        BarkClient(host='http://127.0.0.1:1', token=TOKEN).snapshot()


def test_barkd_error_message_is_surfaced(client, barkd):
    barkd.fail[('POST', '/api/v1/boards/board-all')] = (
        400, '{"message": "not enough confirmed funds"}')
    with pytest.raises(BarkError, match='not enough confirmed funds') as exc:
        client.board_all()
    assert '400' in str(exc.value)
    assert not isinstance(exc.value, (BarkNoWallet, BarkUnavailable))


def test_non_json_error_body_is_surfaced(client, barkd):
    barkd.fail[('POST', '/api/v1/wallet/send')] = (500, 'boom')
    with pytest.raises(BarkError, match='boom'):
        client.send('tark1x', 1)


def test_unexpected_response_shape_becomes_barkerror(client, barkd):
    barkd.routes[('GET', '/api/v1/wallet/balance')] = {"unexpected": True}
    with pytest.raises(BarkError):
        client.snapshot()


# --------------------------------------------------------------------------- validazione
@pytest.mark.parametrize('amount', [0, -1, 1.5, '10', True])
def test_invalid_amounts_are_rejected_before_any_request(client, barkd, amount):
    for call in (lambda: client.board_amount(amount),
                 lambda: client.send_onchain('tb1paddr', amount),
                 lambda: client.send('tark1x', amount),
                 lambda: client.receive_uri(amount)):
        with pytest.raises(BarkError):
            call()
    assert not barkd.requests


@pytest.mark.parametrize('destination', ['', '   ', None])
def test_empty_destination_is_rejected(client, barkd, destination):
    with pytest.raises(BarkError):
        client.send(destination, 10)
    with pytest.raises(BarkError):
        client.send_onchain(destination, 10)
    assert not barkd.requests


def test_required_amounts(client, barkd):
    with pytest.raises(BarkError):
        client.board_amount(None)
    with pytest.raises(BarkError):
        client.send_onchain('tb1paddr', None)
    assert not barkd.requests
