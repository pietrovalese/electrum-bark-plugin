import threading
from datetime import datetime
from functools import partial

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QInputDialog, QRadioButton, QButtonGroup,
)

from electrum.i18n import _
from electrum.gui.qt.qrcodewidget import QRCodeWidget, QrCodeDataOverflow

from .client import BarkNoWallet, BarkUnavailable
from .fake_client import FakeBarkClient, FAUCET_SAT

REFRESH_MS = 15_000
MAX_BOARD_INPUT_SAT = 2_147_483_647   # limite di QInputDialog.getInt (int32)

PAGE_HISTORY = 3


def fmt_sat(n, signed=False) -> str:
    if n is None:
        return '-'
    return f"{n:+,} sat" if signed else f"{n:,} sat"


def parse_sat(text: str, name: str):
    """Testo -> intero positivo di sat, oppure None se vuoto. ValueError se non valido."""
    text = (text or '').strip().replace(',', '').replace('_', '').replace(' ', '')
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        raise ValueError(_('{} must be a whole number of sat.').format(name)) from None
    if value <= 0:
        raise ValueError(_('{} must be greater than zero.').format(name))
    return value


def _ro_line(text=''):
    e = QLineEdit(text)
    e.setReadOnly(True)
    return e


def _copy_to_clipboard(text: str):
    QGuiApplication.clipboard().setText(text or '')


class BarkTab(QWidget):
    """Tab 'Bark': Overview | Receive | Send | History.

    Regole: la GUI non si blocca mai (ogni chiamata a barkd gira in un thread worker e il
    risultato torna nel thread Qt con un segnale); il polling è solo in lettura.
    """

    # (callback, risultato, errore) -> emesso dal thread worker, ricevuto nel thread Qt
    _done = pyqtSignal(object, object, object)

    def __init__(self, plugin, window):
        super().__init__()
        self.plugin = plugin
        self.window = window
        self._polling = False      # un refresh dei saldi è in corso
        self._acting = False       # un'azione (board, send, sync...) è in corso
        self._closed = False
        self._action_buttons = []  # disabilitati finché un'azione è in corso

        self._build_header()
        self._build_overview()
        self._build_receive()
        self._build_send()
        self._build_history()

        self.pages = QTabWidget()
        self.pages.addTab(self.overview_page, _('Overview'))
        self.pages.addTab(self.receive_page, _('Receive'))
        self.pages.addTab(self.send_page, _('Send'))
        self.pages.addTab(self.history_page, _('History'))
        self.pages.currentChanged.connect(self._on_page_changed)

        lay = QVBoxLayout(self)
        lay.addLayout(self.header)
        lay.addWidget(self.pages, 1)

        self._done.connect(self._dispatch)
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(lambda: self.refresh(sync=False))
        self.timer.start()

    # ------------------------------------------------------------------ costruzione UI
    def _action_button(self, text, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        self._action_buttons.append(btn)
        return btn

    def _build_header(self):
        self.status = QLabel(_('Loading...'))
        self.status.setWordWrap(True)
        self.sync_btn = self._action_button(_('Sync'), lambda: self.do_sync())
        self.create_btn = self._action_button(
            _('Create barkd wallet (signet)'), lambda: self.create_wallet())
        self.create_btn.hide()
        self.settings_btn = QPushButton(_('Settings'))
        self.settings_btn.clicked.connect(lambda: self.plugin.settings_dialog(self.window))

        self.header = QHBoxLayout()
        self.header.addWidget(self.status, 1)
        self.header.addWidget(self.create_btn)
        self.header.addWidget(self.sync_btn)
        self.header.addWidget(self.settings_btn)

    def _build_overview(self):
        self.ark_bal = QLabel('-')
        self.ark_pending = QLabel('-')
        self.oc_bal = QLabel('-')

        form = QFormLayout()
        form.addRow(_('Ark balance (spendable):'), self.ark_bal)
        form.addRow(_('Ark, boarding (pending):'), self.ark_pending)
        form.addRow(_('barkd on-chain (confirmed):'), self.oc_bal)

        self.fund_btn = self._action_button(
            _('1. Fund barkd from this Electrum wallet…'), lambda: self.fund_barkd())
        self.board_all_btn = self._action_button(
            _('2. Board all on-chain funds into Ark'), lambda: self.board_all())
        self.board_amount_btn = self._action_button(
            _('Board a specific amount…'), lambda: self.board_amount())
        self.faucet_btn = self._action_button(
            _('Fake client: simulate faucet (+{} sat)').format(f'{FAUCET_SAT:,}'),
            lambda: self.fake_faucet())
        self.faucet_btn.hide()

        self.overview_hint = QLabel(_(
            'Fund barkd from Electrum (or a faucet), wait for 1 confirmation, '
            'then board the funds into Ark.'))
        self.overview_hint.setWordWrap(True)

        lay = QVBoxLayout()
        lay.addLayout(form)
        lay.addSpacing(8)
        lay.addWidget(self.overview_hint)
        for b in (self.fund_btn, self.board_all_btn, self.board_amount_btn, self.faucet_btn):
            row = QHBoxLayout()
            row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        lay.addStretch(1)
        self.overview_page = QWidget()
        self.overview_page.setLayout(lay)

    def _copy_row(self):
        """Campo di sola lettura + pulsante Copy. Ritorna (campo, pulsante)."""
        field = _ro_line()
        btn = QPushButton(_('Copy'))
        btn.clicked.connect(lambda: self._copy(field.text()))
        return field, btn

    def _build_receive(self):
        self.rx_amount = QLineEdit()
        self.rx_amount.setPlaceholderText(_('optional, in sat'))
        self.rx_label = QLineEdit()
        self.rx_message = QLineEdit()
        self.rx_onchain = QCheckBox(_('Include an on-chain fallback address'))
        self.rx_onchain.setChecked(True)
        self.rx_btn = self._action_button(
            _('Generate payment request'), lambda: self.generate_request())

        form = QFormLayout()
        form.addRow(_('Amount:'), self.rx_amount)
        form.addRow(_('Label:'), self.rx_label)
        form.addRow(_('Message:'), self.rx_message)
        form.addRow(self.rx_onchain)

        self.rx_qr = QRCodeWidget()
        self.rx_qr_note = QLabel('')
        self.rx_qr_note.setWordWrap(True)

        self.rx_fields = {}
        grid = QGridLayout()
        for row, (key, text) in enumerate((
                ('bip321', _('Payment URI (BIP 321):')),
                ('ark', _('Ark address:')),
                ('bolt11', _('Lightning invoice:')),
                ('onchain', _('On-chain address:')))):
            field, btn = self._copy_row()
            self.rx_fields[key] = field
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(btn, row, 2)
        grid.setColumnStretch(1, 1)

        qr_row = QHBoxLayout()
        qr_row.addStretch(1)
        qr_row.addWidget(self.rx_qr)
        qr_row.addStretch(1)

        lay = QVBoxLayout()
        lay.addLayout(form)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.rx_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        lay.addLayout(qr_row)
        lay.addWidget(self.rx_qr_note)
        lay.addLayout(grid)
        lay.addStretch(1)
        self.receive_page = QWidget()
        self.receive_page.setLayout(lay)

    def _build_send(self):
        self.tx_ark = QRadioButton(_('Ark / Lightning (instant)'))
        self.tx_onchain = QRadioButton(_('On-chain (paid from Ark balance)'))
        self.tx_ark.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.tx_ark)
        group.addButton(self.tx_onchain)
        self.tx_group = group
        self.tx_ark.toggled.connect(self._on_send_mode)

        self.tx_dest = QLineEdit()
        self.tx_dest.setPlaceholderText(_('Ark address, Lightning invoice / offer / address'))
        self.tx_amount = QLineEdit()
        self.tx_send_btn = self._action_button(_('Send'), lambda: self.send_payment())

        form = QFormLayout()
        form.addRow(_('Destination:'), self.tx_dest)
        form.addRow(_('Amount:'), self.tx_amount)
        self._on_send_mode()

        lay = QVBoxLayout()
        lay.addWidget(self.tx_ark)
        lay.addWidget(self.tx_onchain)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self.tx_send_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.send_page = QWidget()
        self.send_page.setLayout(lay)

    def _build_history(self):
        self.hist = QTreeWidget()
        self.hist.setRootIsDecorated(False)
        self.hist.setAlternatingRowColors(True)
        self.hist.setHeaderLabels([_('Date'), _('Type'), _('Status'), _('Amount'),
                                   _('Fee'), _('Counterparty')])
        header = self.hist.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.hist_note = QLabel('')
        lay = QVBoxLayout()
        lay.addWidget(self.hist)
        lay.addWidget(self.hist_note)
        self.history_page = QWidget()
        self.history_page.setLayout(lay)

    # ------------------------------------------------------------------ thread worker
    def _run(self, fn, callback):
        """Esegue fn() in un thread; callback(res, err) viene chiamata nel thread Qt."""
        def worker():
            try:
                res, err = fn(), None
            except Exception as e:  # noqa
                res, err = None, e
            try:
                self._done.emit(callback, res, err)
            except RuntimeError:
                pass   # il widget è stato distrutto nel frattempo
        threading.Thread(target=worker, daemon=True).start()

    def _dispatch(self, callback, res, err):
        if not self._closed:
            callback(res, err)

    def _set_acting(self, acting: bool):
        self._acting = acting
        for b in self._action_buttons:
            b.setEnabled(not acting)

    def _action(self, fn, on_ok, *, status=None):
        """Schema comune delle azioni: blocca i pulsanti, lavora in background, poi
        mostra l'esito e riallinea saldi e storico."""
        if self._acting:
            return
        self._set_acting(True)
        if status:
            self.status.setText(status)
        client = self.plugin.client()

        def finished(res, err):
            self._set_acting(False)
            if err:
                self._show_error(err)
            else:
                on_ok(res)
            self.refresh(sync=False)
            if self.pages.currentIndex() == PAGE_HISTORY:
                self.refresh_history()
        self._run(partial(fn, client), finished)

    def _show_error(self, err):
        if isinstance(err, BarkNoWallet):
            self._show_no_wallet()
        elif isinstance(err, BarkUnavailable):
            self._show_unavailable(err)
            self.window.show_error(_('barkd is not reachable: ') + str(err))
        else:
            self.window.show_error(str(err) or err.__class__.__name__)

    # ------------------------------------------------------------------ refresh
    def refresh(self, sync=False):
        if self._closed or self._polling or self._acting:
            return
        self._polling = True
        client = self.plugin.client()
        self._run(partial(client.snapshot, sync), self._on_snapshot)

    def _on_page_changed(self, index):
        if index == PAGE_HISTORY:
            self.refresh_history()

    def refresh_history(self):
        client = self.plugin.client()
        self._run(client.history, self._on_history)

    def _on_snapshot(self, data, err):
        self._polling = False
        self.faucet_btn.setVisible(isinstance(self.plugin.client(), FakeBarkClient))
        if isinstance(err, BarkNoWallet):
            return self._show_no_wallet()
        if isinstance(err, BarkUnavailable):
            return self._show_unavailable(err)
        if err:
            self.create_btn.hide()
            self.status.setText(_('Error: ') + str(err))
            return self._clear()
        self.create_btn.hide()
        fake = ' ' + _('[fake client]') if isinstance(self.plugin.client(), FakeBarkClient) else ''
        self.status.setText(
            (_('Connected to the Ark server') if data['connected']
             else _('NOT connected to the Ark server')) + fake)
        self.ark_bal.setText(fmt_sat(data['ark_spendable_sat']))
        self.ark_pending.setText(fmt_sat(data['ark_pending_board_sat']))
        oc = fmt_sat(data['onchain_confirmed_sat'])
        pending = data.get('onchain_pending_sat') or 0
        if pending:
            oc += ' ' + _('(+{} unconfirmed)').format(fmt_sat(pending))
        self.oc_bal.setText(oc)

    def _show_no_wallet(self):
        self.status.setText(_('barkd is running but has no wallet yet.'))
        self.create_btn.show()
        self._clear()

    def _show_unavailable(self, err):
        self.create_btn.hide()
        self.status.setText(_('barkd is not reachable: ') + str(err))
        self._clear()

    def _clear(self):
        for w in (self.ark_bal, self.ark_pending, self.oc_bal):
            w.setText('-')

    def _on_history(self, rows, err):
        self.hist.clear()
        if err:
            self.hist_note.setText(_('Could not load history: ') + str(err))
            return
        self.hist_note.setText('' if rows else _('No movements yet.'))
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for r in rows:
            when = datetime.fromtimestamp(r['time']).strftime('%Y-%m-%d %H:%M')
            item = QTreeWidgetItem([
                when, str(r['type']), str(r['status']),
                fmt_sat(r['amount_sat'], signed=True),
                fmt_sat(r['fee_sat']) if r['fee_sat'] else '',
                r['counterparty'] or ''])
            item.setTextAlignment(3, right)
            item.setTextAlignment(4, right)
            self.hist.addTopLevelItem(item)

    # ------------------------------------------------------------------ azioni
    def _copy(self, text):
        if text:
            _copy_to_clipboard(text)
            self.status.setText(_('Copied to clipboard.'))

    def do_sync(self):
        if self._acting:
            return
        self._set_acting(True)
        self.status.setText(_('Syncing... (this can take a while)'))
        client = self.plugin.client()

        def finished(data, err):
            self._set_acting(False)
            if err:
                self._show_error(err)
            else:
                self._on_snapshot(data, None)
            if self.pages.currentIndex() == PAGE_HISTORY:
                self.refresh_history()
        self._run(partial(client.snapshot, True), finished)

    def create_wallet(self):
        self._action(lambda c: c.create_wallet(),
                     lambda _r: self.create_btn.hide(),
                     status=_('Creating the barkd wallet...'))

    def fake_faucet(self):
        client = self.plugin.client()
        if not isinstance(client, FakeBarkClient):
            return
        self._action(lambda c: c.faucet(FAUCET_SAT), lambda _r: None)

    def fund_barkd(self):
        """Ponte Electrum -> barkd: indirizzo on-chain di barkd nella Send tab di Electrum."""
        self._action(lambda c: c.new_onchain_address(), self._prefill_electrum_send,
                     status=_('Asking barkd for a fresh on-chain address...'))

    def _prefill_electrum_send(self, address):
        _copy_to_clipboard(address)
        try:
            send_tab = self.window.send_tab
            send_tab.set_payment_identifier(f'bitcoin:{address}')
            # Electrum non solleva errori per un indirizzo non valido: lo segna INVALID e basta
            payto = getattr(send_tab, 'payto_e', None)
            pi = getattr(payto, 'payment_identifier', None)
            if pi is not None and not pi.is_valid():
                raise ValueError('rejected by the Electrum Send tab')
            self.window.show_send_tab()
            self.status.setText(_(
                "Electrum's Send tab now pays barkd's address (also copied to the "
                "clipboard). Enter an amount, send, and wait for 1 confirmation."))
        except Exception:  # noqa — API interna di Electrum: fallback sicuro
            self.window.show_message(_(
                "barkd's on-chain address (copied to the clipboard):\n\n{}\n\n"
                "Paste it as the destination in Electrum's Send tab.").format(address))

    def board_all(self):
        if not self.window.question(_(
                'Board ALL confirmed on-chain funds of barkd into Ark?')):
            return
        self._action(lambda c: c.board_all(), self._board_done,
                     status=_('Boarding...'))

    def board_amount(self):
        amount, ok = QInputDialog.getInt(
            self.window, _('Board a specific amount'),
            _('Amount to board (sat):'), 10_000, 1, MAX_BOARD_INPUT_SAT)
        if not ok:
            return
        if not self.window.question(_('Board {} into Ark?').format(fmt_sat(amount))):
            return
        self._action(lambda c: c.board_amount(amount), self._board_done,
                     status=_('Boarding...'))

    def _board_done(self, res):
        self.window.show_message(_(
            'Boarding {} started. It shows as "Ark, boarding (pending)" until the '
            'funding transaction confirms, then becomes spendable.\n\nTransaction: {}'
        ).format(fmt_sat(res['amount_sat']), res['txid']))

    # --- Receive ---
    def generate_request(self):
        try:
            amount = parse_sat(self.rx_amount.text(), _('Amount'))
        except ValueError as e:
            return self.window.show_error(str(e))
        label, message = self.rx_label.text(), self.rx_message.text()
        onchain = self.rx_onchain.isChecked()
        self._action(
            lambda c: c.receive_uri(amount, label, message, onchain),
            self._show_request, status=_('Generating payment request...'))

    def _show_request(self, res):
        for key, field in self.rx_fields.items():
            field.setText(res.get(key) or '')
        uri = res.get('bip321') or ''
        self.rx_qr_note.setText('')
        try:
            self.rx_qr.setData(uri)
        except QrCodeDataOverflow:
            self.rx_qr.setData(None)
            self.rx_qr_note.setText(_('The URI is too long for a QR code: use Copy instead.'))
        if not res.get('bolt11'):
            self.rx_qr_note.setText(
                (self.rx_qr_note.text() + ' ' if self.rx_qr_note.text() else '') +
                _('No Lightning invoice was returned (try again with an amount).'))

    # --- Send ---
    def _on_send_mode(self, *_args):
        onchain = self.tx_onchain.isChecked()
        self.tx_dest.setPlaceholderText(
            _('On-chain address') if onchain
            else _('Ark address, Lightning invoice / offer / address'))
        self.tx_amount.setPlaceholderText(
            _('required, in sat') if onchain
            else _('optional if the invoice already has an amount, in sat'))

    def send_payment(self):
        dest = self.tx_dest.text().strip()
        onchain = self.tx_onchain.isChecked()
        if not dest:
            return self.window.show_error(_('Please enter a destination.'))
        try:
            amount = parse_sat(self.tx_amount.text(), _('Amount'))
        except ValueError as e:
            return self.window.show_error(str(e))
        if onchain and amount is None:
            return self.window.show_error(_('Please enter an amount for an on-chain payment.'))

        kind = _('on-chain, paid from your Ark balance') if onchain else _('Ark / Lightning')
        amount_txt = fmt_sat(amount) if amount is not None else _('as specified by the destination')
        if not self.window.question(_(
                'Send this payment?\n\nDestination:\n{}\n\nAmount: {}\nType: {}'
        ).format(dest, amount_txt, kind)):
            return

        if onchain:
            fn = lambda c: c.send_onchain(dest, amount)  # noqa: E731
        else:
            fn = lambda c: c.send(dest, amount)          # noqa: E731
        self._action(fn, self._send_done, status=_('Sending...'))

    def _send_done(self, res):
        self.tx_dest.clear()
        self.tx_amount.clear()
        detail = res.get('message') or res.get('txid') or ''
        self.window.show_message(_('Payment sent.') + (f'\n\n{detail}' if detail else ''))

    # ------------------------------------------------------------------ ciclo di vita
    def stop(self):
        self._closed = True
        self.timer.stop()