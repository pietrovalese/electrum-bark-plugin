"""BarkTab con Qt offscreen e il FakeBarkClient: percorso completo senza barkd né Electrum
in esecuzione. Usa i widget veri di Electrum (QRCodeWidget): senza Electrum nel PYTHONPATH
o senza PyQt6 questi test vengono saltati (usa ./script/run_tests.sh)."""
import time
import types

import pytest

pytest.importorskip('PyQt6.QtWidgets')
pytest.importorskip('electrum.gui.qt.qrcodewidget')

from PyQt6.QtWidgets import QApplication, QWidget, QTabWidget  # noqa: E402

from bark.fake_client import FakeBarkClient, FAUCET_SAT  # noqa: E402
from bark.ui import BarkTab, PAGE_HISTORY, fmt_sat, parse_sat  # noqa: E402


@pytest.fixture(scope='session')
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_latency(monkeypatch):
    monkeypatch.setattr('bark.fake_client.time',
                        types.SimpleNamespace(sleep=lambda s: None, time=time.time))


class FakeSendTab:
    def __init__(self):
        self.identifiers = []

    def set_payment_identifier(self, text):
        self.identifiers.append(text)


class FakeWindow(QWidget):
    """Le poche cose di ElectrumWindow che la tab usa: finestre di dialogo registrate."""
    def __init__(self):
        super().__init__()
        self.tabs = QTabWidget()
        self.send_tab = FakeSendTab()
        self.errors, self.messages, self.questions = [], [], []
        self.answer = True            # risposta alle domande di conferma
        self.send_tab_shown = False

    def show_error(self, msg, **kw):
        self.errors.append(msg)

    def show_message(self, msg, **kw):
        self.messages.append(msg)

    def question(self, msg, **kw):
        self.questions.append(msg)
        return self.answer

    def show_send_tab(self):
        self.send_tab_shown = True


class FakePlugin:
    def __init__(self, client):
        self._client = client
        self.settings_opened = 0

    def client(self):
        return self._client

    def settings_dialog(self, window):
        self.settings_opened += 1


def pump(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError('timeout in attesa della GUI')


def idle(tab):
    return lambda: not tab._acting and not tab._polling


@pytest.fixture
def make_tab(qapp):
    tabs = []

    def make(scenario='no_wallet'):
        client = FakeBarkClient(scenario)
        plugin, window = FakePlugin(client), FakeWindow()
        tab = BarkTab(plugin, window)
        tabs.append(tab)
        return tab, client, window, plugin

    yield make
    for t in tabs:
        t.stop()
        t.deleteLater()


@pytest.fixture
def funded(qapp, make_tab):
    """Tab con wallet creato e fondi on-chain confermati (client finto)."""
    tab, client, window, plugin = make_tab('ok')
    client.faucet()
    tab.refresh()
    pump(qapp, lambda: tab.oc_bal.text() != '-' and idle(tab)())
    return tab, client, window, plugin


def make_spendable(qapp, tab):
    """Board di tutto + due refresh: i fondi diventano spendibili in Ark."""
    tab.board_all()
    pump(qapp, idle(tab))
    for _ in range(2):
        tab.refresh()
        pump(qapp, idle(tab))
    assert tab.ark_bal.text() == fmt_sat(FAUCET_SAT)


# ----------------------------------------------------------------------------- helper puri
def test_parse_sat():
    assert parse_sat('', 'x') is None and parse_sat('  ', 'x') is None
    assert parse_sat('1,000', 'x') == 1000 and parse_sat(' 25 000 ', 'x') == 25000
    for bad in ('abc', '1.5', '0', '-3'):
        with pytest.raises(ValueError):
            parse_sat(bad, 'Amount')


def test_fmt_sat():
    assert fmt_sat(1234567) == '1,234,567 sat'
    assert fmt_sat(-1500, signed=True) == '-1,500 sat'
    assert fmt_sat(2000, signed=True) == '+2,000 sat'
    assert fmt_sat(None) == '-'


# ----------------------------------------------------------------------------- stati
def test_no_wallet_shows_create_button_then_connected(qapp, make_tab):
    tab, client, window, plugin = make_tab('no_wallet')
    tab.refresh()
    pump(qapp, lambda: not tab.create_btn.isHidden())
    assert 'no wallet' in tab.status.text()
    assert tab.ark_bal.text() == '-'

    tab.create_wallet()
    pump(qapp, lambda: tab.create_btn.isHidden() and idle(tab)()
         and 'Connected' in tab.status.text())
    assert '[fake client]' in tab.status.text()
    assert tab.ark_bal.text() == fmt_sat(0)


def test_barkd_down_shows_status_and_clears_values(qapp, make_tab):
    tab, client, window, plugin = make_tab('down')
    tab.refresh()
    pump(qapp, lambda: 'not reachable' in tab.status.text())
    assert tab.ark_bal.text() == '-' and tab.create_btn.isHidden()


def test_faucet_button_only_with_fake_client(qapp, make_tab):
    tab, client, window, plugin = make_tab('ok')
    tab.refresh()
    pump(qapp, lambda: 'Connected' in tab.status.text())
    assert not tab.faucet_btn.isHidden()
    plugin._client = types.SimpleNamespace(      # un client "vero"
        snapshot=lambda sync=False: client.snapshot())
    tab.refresh()
    pump(qapp, idle(tab))
    assert tab.faucet_btn.isHidden()


def test_settings_button_opens_plugin_settings(qapp, make_tab):
    tab, client, window, plugin = make_tab('ok')
    tab.settings_btn.click()
    assert plugin.settings_opened == 1


# ----------------------------------------------------------------------------- percorso completo
def test_faucet_updates_overview(qapp, make_tab):
    tab, client, window, plugin = make_tab('ok')
    tab.fake_faucet()
    pump(qapp, lambda: tab.oc_bal.text() == fmt_sat(FAUCET_SAT) and idle(tab)())


def test_fund_barkd_prefills_electrum_send_tab(qapp, funded):
    tab, client, window, plugin = funded
    tab.fund_barkd()
    pump(qapp, lambda: window.send_tab_shown)
    assert len(window.send_tab.identifiers) == 1
    uri = window.send_tab.identifiers[0]
    assert uri.startswith('bitcoin:tb1q')
    assert QApplication.clipboard().text() == uri[len('bitcoin:'):]


def test_board_all_requires_confirmation(qapp, funded):
    tab, client, window, plugin = funded
    window.answer = False
    tab.board_all()
    assert window.questions and not window.messages
    assert tab.oc_bal.text() == fmt_sat(FAUCET_SAT) and not tab._acting


def test_board_all_pending_then_spendable(qapp, funded):
    tab, client, window, plugin = funded
    tab.board_all()
    pump(qapp, lambda: window.messages and idle(tab)()
         and tab.ark_pending.text() == fmt_sat(FAUCET_SAT))
    assert 'Boarding' in window.messages[0]
    assert tab.oc_bal.text() == fmt_sat(0) and tab.ark_bal.text() == fmt_sat(0)
    for _ in range(2):
        tab.refresh()
        pump(qapp, idle(tab))
    assert tab.ark_bal.text() == fmt_sat(FAUCET_SAT)
    assert tab.ark_pending.text() == fmt_sat(0)


def test_board_specific_amount(qapp, funded, monkeypatch):
    tab, client, window, plugin = funded
    monkeypatch.setattr('bark.ui.QInputDialog.getInt', lambda *a, **k: (30_000, True))
    tab.board_amount()
    pump(qapp, lambda: window.messages and idle(tab)()
         and tab.oc_bal.text() == fmt_sat(FAUCET_SAT - 30_000))


def test_board_specific_amount_cancelled(qapp, funded, monkeypatch):
    tab, client, window, plugin = funded
    monkeypatch.setattr('bark.ui.QInputDialog.getInt', lambda *a, **k: (0, False))
    tab.board_amount()
    assert not window.questions and not window.messages


def test_receive_generates_request_with_qr(qapp, funded):
    tab, client, window, plugin = funded
    tab.rx_amount.setText('5,000')
    tab.rx_label.setText('cena')
    tab.generate_request()
    pump(qapp, lambda: tab.rx_fields['bolt11'].text() and idle(tab)())
    assert tab.rx_fields['bip321'].text().startswith('bitcoin:')
    assert tab.rx_fields['ark'].text().startswith('tark1')
    assert tab.rx_fields['onchain'].text().startswith('tb1')
    assert tab.rx_qr.data == tab.rx_fields['bip321'].text()
    assert 'Lightning' not in tab.rx_qr_note.text()


def test_receive_without_amount_warns_about_missing_invoice(qapp, funded):
    tab, client, window, plugin = funded
    tab.rx_onchain.setChecked(False)
    tab.generate_request()
    pump(qapp, lambda: tab.rx_fields['ark'].text() and idle(tab)())
    assert tab.rx_fields['bolt11'].text() == '' and tab.rx_fields['onchain'].text() == ''
    assert 'No Lightning invoice' in tab.rx_qr_note.text()


def test_receive_rejects_bad_amount(qapp, funded):
    tab, client, window, plugin = funded
    tab.rx_amount.setText('abc')
    tab.generate_request()
    assert window.errors and not tab._acting


def test_send_ark_payment(qapp, funded):
    tab, client, window, plugin = funded
    make_spendable(qapp, tab)
    tab.tx_dest.setText('tark1qdestination')
    tab.tx_amount.setText('2500')
    tab.send_payment()
    pump(qapp, lambda: tab.ark_bal.text() == fmt_sat(FAUCET_SAT - 2500) and idle(tab)())
    assert window.questions and 'tark1qdestination' in window.questions[-1]
    assert window.messages[-1].startswith('Payment sent')
    assert tab.tx_dest.text() == '' and tab.tx_amount.text() == ''


def test_send_onchain_payment(qapp, funded):
    tab, client, window, plugin = funded
    make_spendable(qapp, tab)
    tab.tx_onchain.setChecked(True)
    tab.tx_dest.setText('tb1qfakefakefakefakefake')
    tab.tx_amount.setText('1000')
    tab.send_payment()
    pump(qapp, lambda: window.messages and tab.ark_bal.text() != fmt_sat(FAUCET_SAT)
         and idle(tab)())
    assert client.history()[0]['type'] == 'offboard'


def test_send_onchain_needs_an_amount(qapp, funded):
    tab, client, window, plugin = funded
    tab.tx_onchain.setChecked(True)
    tab.tx_dest.setText('tb1qfakefakefakefakefake')
    tab.send_payment()
    assert window.errors and not window.questions


def test_send_validation_and_decline(qapp, funded):
    tab, client, window, plugin = funded
    tab.send_payment()                                  # destinazione vuota
    assert len(window.errors) == 1
    tab.tx_dest.setText('tark1qdest')
    tab.tx_amount.setText('abc')
    tab.send_payment()                                  # importo non numerico
    assert len(window.errors) == 2
    tab.tx_amount.setText('10')
    window.answer = False
    tab.send_payment()                                  # conferma rifiutata
    assert not tab._acting and not client.history()


def test_send_failure_is_reported_not_raised(qapp, funded):
    tab, client, window, plugin = funded            # nessun fondo Ark: saldo insufficiente
    tab.tx_dest.setText('tark1qdest')
    tab.tx_amount.setText('100')
    tab.send_payment()
    pump(qapp, lambda: window.errors and idle(tab)())
    assert 'Insufficient' in window.errors[-1]
    assert all(b.isEnabled() for b in tab._action_buttons)   # pulsanti riabilitati


def test_buttons_disabled_while_acting(qapp, funded):
    tab, client, window, plugin = funded
    tab.board_all()
    assert not tab.board_all_btn.isEnabled() and tab._acting
    pump(qapp, idle(tab))
    assert tab.board_all_btn.isEnabled()


def test_send_mode_switch_changes_placeholders(qapp, make_tab):
    tab, *_ = make_tab('ok')
    tab.tx_onchain.setChecked(True)
    assert 'required' in tab.tx_amount.placeholderText()
    tab.tx_ark.setChecked(True)
    assert 'optional' in tab.tx_amount.placeholderText()


def test_history_page_lists_movements(qapp, funded):
    tab, client, window, plugin = funded
    make_spendable(qapp, tab)
    tab.tx_dest.setText('tark1qdest')
    tab.tx_amount.setText('100')
    tab.send_payment()
    pump(qapp, idle(tab))
    tab.pages.setCurrentIndex(PAGE_HISTORY)          # aprire la pagina ricarica la history
    pump(qapp, lambda: tab.hist.topLevelItemCount() == 2)
    top, bottom = tab.hist.topLevelItem(0), tab.hist.topLevelItem(1)
    assert (top.text(1), top.text(3)) == ('send', '-100 sat')
    assert (bottom.text(1), bottom.text(3)) == ('board', f'+{FAUCET_SAT:,} sat')
    assert top.text(5) == 'tark1qdest'


def test_history_empty_note(qapp, make_tab):
    tab, client, window, plugin = make_tab('ok')
    tab.refresh_history()
    pump(qapp, lambda: tab.hist_note.text() != '')
    assert 'No movements' in tab.hist_note.text()


def test_do_sync_updates_overview(qapp, funded):
    tab, client, window, plugin = funded
    tab.do_sync()
    assert not tab.sync_btn.isEnabled()
    pump(qapp, idle(tab))
    assert tab.sync_btn.isEnabled() and 'Connected' in tab.status.text()


# ----------------------------------------------------------------------------- ciclo di vita
def test_stop_halts_timer_and_ignores_late_results(qapp, make_tab):
    tab, client, window, plugin = make_tab('ok')
    tab.refresh()
    tab.stop()
    assert not tab.timer.isActive()
    for _ in range(30):                 # il risultato del worker arriva ma viene scartato
        qapp.processEvents()
        time.sleep(0.01)
    assert tab.ark_bal.text() == '-'
    tab._polling = False                # (il flag resta True perché il risultato è scartato)
    tab.refresh()                       # dopo stop() non parte più nessun worker
    assert not tab._polling
