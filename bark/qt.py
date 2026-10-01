import threading
from functools import partial

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QDialogButtonBox,
)

from electrum.i18n import _
from electrum.plugin import hook
from electrum.gui.qt.util import WindowModalDialog, EnterButton

from .bark import BarkPlugin
from .client import BarkNoWallet, BarkUnavailable

REFRESH_MS = 15_000


def _ro_line(text=''):
    e = QLineEdit(text)
    e.setReadOnly(True)
    return e


class BarkTab(QWidget):
    # (callback, risultato, errore) -> emesso dal thread worker, ricevuto nel thread Qt
    _done = pyqtSignal(object, object, object)

    def __init__(self, plugin: 'Plugin', window):
        super().__init__()
        self.plugin = plugin
        self.window = window
        self._busy = False

        self.status = QLabel(_('Caricamento...'))
        self.status.setWordWrap(True)
        self.ark_addr = _ro_line()
        self.ark_bal = QLabel('-')
        self.ark_pending = QLabel('-')
        self.oc_addr = _ro_line()
        self.oc_bal = QLabel('-')

        self.refresh_btn = QPushButton(_('Aggiorna (sync)'))
        self.refresh_btn.clicked.connect(lambda: self.refresh(sync=True))
        self.settings_btn = QPushButton(_('Impostazioni'))
        self.settings_btn.clicked.connect(lambda: self.plugin.settings_dialog(self.window))
        self.create_btn = QPushButton(_('Crea wallet barkd (signet)'))
        self.create_btn.clicked.connect(self.create_wallet)
        self.create_btn.hide()

        form = QFormLayout()
        form.addRow(_('Indirizzo Ark:'), self.ark_addr)
        form.addRow(_('Saldo Ark (spendibile):'), self.ark_bal)
        form.addRow(_('Ark in board (pending):'), self.ark_pending)
        form.addRow(_('Indirizzo on-chain:'), self.oc_addr)
        form.addRow(_('Saldo on-chain:'), self.oc_bal)

        btns = QHBoxLayout()
        btns.addWidget(self.refresh_btn)
        btns.addWidget(self.create_btn)
        btns.addWidget(self.settings_btn)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addWidget(self.status)
        lay.addLayout(form)
        lay.addLayout(btns)
        lay.addStretch(1)

        self._done.connect(lambda cb, res, err: cb(res, err))
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(lambda: self.refresh(sync=False))
        self.timer.start()

    # --- esecuzione fuori dal thread GUI ---
    def _run(self, fn, callback):
        def worker():
            try:
                res, err = fn(), None
            except Exception as e:  # noqa
                res, err = None, e
            self._done.emit(callback, res, err)
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self, sync=False):
        if self._busy:
            return
        self._busy = True
        client = self.plugin.client()
        self._run(partial(client.snapshot, sync), self._on_snapshot)

    def create_wallet(self):
        self.create_btn.setEnabled(False)
        self.status.setText(_('Creazione wallet in corso...'))
        client = self.plugin.client()
        self._run(client.create_wallet, lambda _r, err: (
            self.create_btn.setEnabled(True),
            self.status.setText(str(err)) if err else self.refresh(sync=True)))

    def _on_snapshot(self, data, err):
        self._busy = False
        self.create_btn.hide()
        if isinstance(err, BarkNoWallet):
            self.status.setText(_('barkd è attivo ma non ha un wallet.'))
            self.create_btn.show()
            return self._clear()
        if isinstance(err, BarkUnavailable):
            self.status.setText(_('barkd non raggiungibile: ') + str(err))
            return self._clear()
        if err:
            self.status.setText(_('Errore: ') + str(err))
            return self._clear()
        srv = _('connesso al server Ark') if data['connected'] else _('NON connesso al server Ark')
        self.status.setText(srv)
        self.ark_addr.setText(data['ark_address'])
        self.ark_bal.setText(f"{data['ark_spendable_sat']} sat")
        self.ark_pending.setText(f"{data['ark_pending_board_sat']} sat")
        self.oc_addr.setText(data['onchain_address'])
        self.oc_bal.setText(
            f"{data['onchain_confirmed_sat']} sat confermati "
            f"({data['onchain_spendable_sat']} spendibili)")

    def _clear(self):
        for w in (self.ark_addr, self.oc_addr):
            w.setText('')
        for w in (self.ark_bal, self.ark_pending, self.oc_bal):
            w.setText('-')

    def stop(self):
        self.timer.stop()


class Plugin(BarkPlugin):
    def __init__(self, parent, config, name):
        BarkPlugin.__init__(self, parent, config, name)
        self.tabs = {}  # window -> BarkTab

    @hook
    def load_wallet(self, wallet, window):
        if window in self.tabs:
            return
        tab = BarkTab(self, window)
        window.tabs.addTab(tab, _('Bark'))
        self.tabs[window] = tab
        tab.refresh(sync=False)

    @hook
    def close_wallet(self, wallet):
        for window, tab in list(self.tabs.items()):
            if window.wallet is wallet:
                tab.stop()
                idx = window.tabs.indexOf(tab)
                if idx >= 0:
                    window.tabs.removeTab(idx)
                del self.tabs[window]

    # --- impostazioni (pulsante nel dialog Tools -> Plugins) ---
    def requires_settings(self) -> bool:
        return True

    def settings_widget(self, window):
        return EnterButton(_('Impostazioni'), partial(self.settings_dialog, window))

    def settings_dialog(self, window):
        d = WindowModalDialog(window, _('Impostazioni Bark'))
        host = QLineEdit(self.get_host())
        token = QLineEdit(self.get_token())
        token.setEchoMode(QLineEdit.EchoMode.Password)
        fake = QCheckBox(_('Usa client finto (senza barkd)'))
        fake.setChecked(self.use_fake())

        form = QFormLayout()
        form.addRow(_('Host barkd:'), host)
        form.addRow(_('Token:'), token)
        form.addRow(fake)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay = QVBoxLayout(d)
        lay.addLayout(form)
        lay.addWidget(bb)

        if d.exec():
            self.save_settings(host.text(), token.text(), fake.isChecked())
            self._fake = None
            for tab in self.tabs.values():
                tab.refresh(sync=False)