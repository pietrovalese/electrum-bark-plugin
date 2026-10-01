from functools import partial

from PyQt6.QtWidgets import (
    QVBoxLayout, QFormLayout, QLabel, QLineEdit, QCheckBox, QDialogButtonBox,
)

from electrum.i18n import _
from electrum.plugin import hook
from electrum.gui.qt.util import WindowModalDialog, EnterButton

from .bark import BarkPlugin
from .ui import BarkTab


class Plugin(BarkPlugin):
    """Punto d'ingresso per la GUI Qt: Electrum istanzia questa classe."""

    def __init__(self, parent, config, name):
        BarkPlugin.__init__(self, parent, config, name)
        self.tabs = {}  # window -> BarkTab

    # --- hook di Electrum ---
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
                self._remove_tab(window, tab)

    def on_close(self):
        # plugin disabilitato: via le tab da tutte le finestre e ferma i timer
        for window, tab in list(self.tabs.items()):
            self._remove_tab(window, tab)

    def _remove_tab(self, window, tab):
        tab.stop()
        idx = window.tabs.indexOf(tab)
        if idx >= 0:
            window.tabs.removeTab(idx)
        tab.deleteLater()
        self.tabs.pop(window, None)

    # --- impostazioni (pulsante nel dialog Tools -> Plugins e nella tab Bark) ---
    def requires_settings(self) -> bool:
        return True

    def settings_widget(self, window):
        return EnterButton(_('Settings'), partial(self.settings_dialog, window))

    def settings_dialog(self, window):
        d = WindowModalDialog(window, _('Bark settings'))
        host = QLineEdit(self.get_host())
        token = QLineEdit(self.get_token())
        token.setEchoMode(QLineEdit.EchoMode.Password)
        token.setPlaceholderText(_('empty: use the BARKD_TOKEN environment variable'))
        fake = QCheckBox(_('Use fake client (no barkd needed)'))
        fake.setChecked(self.use_fake())

        form = QFormLayout()
        form.addRow(_('barkd URL:'), host)
        form.addRow(_('Auth token:'), token)
        form.addRow(fake)
        note = QLabel(_(
            'The token is stored in clear text in the Electrum config. '
            'Prefer leaving it empty and exporting BARKD_TOKEN before starting Electrum.'))
        note.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay = QVBoxLayout(d)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(bb)

        if d.exec():
            self.save_settings(host.text(), token.text(), fake.isChecked())
            for tab in self.tabs.values():
                tab.refresh(sync=False)
