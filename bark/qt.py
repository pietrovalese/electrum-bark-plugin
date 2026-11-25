from functools import partial

from PyQt6.QtWidgets import (
    QApplication, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QCheckBox, QDialogButtonBox,
)

from electrum.i18n import _
from electrum.plugin import hook
from electrum.gui.qt.util import WindowModalDialog, EnterButton

from .bark import BarkPlugin
from .client import DEFAULT_HOST, is_insecure_remote
from .ui import BarkTab


class Plugin(BarkPlugin):
    """Punto d'ingresso per la GUI Qt: Electrum istanzia questa classe."""

    def __init__(self, parent, config, name):
        BarkPlugin.__init__(self, parent, config, name)
        self.tabs = {}  # window -> BarkTab
        self._attach_open_windows()

    def _attach_open_windows(self):
        app = QApplication.instance()
        if app is None:
            return
        for w in app.topLevelWidgets():
            if getattr(w, 'wallet', None) is not None and hasattr(w, 'tabs'):
                self.load_wallet(w.wallet, w)

    # --- hook di Electrum ---
    @hook
    def load_wallet(self, wallet, window):
        if window is None or window in self.tabs:
            return
        tab = BarkTab(self, window)
        window.tabs.addTab(tab, _('Bark'))
        self.tabs[window] = tab
        tab.refresh(sync=False)

    @hook
    def close_wallet(self, wallet):
        for window, tab in list(self.tabs.items()):
            if getattr(window, 'wallet', None) is wallet:
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
        host.setPlaceholderText(_('empty: use BARKD_HOST or {}').format(DEFAULT_HOST))
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
            raw_host = host.text().strip()
            if not fake.isChecked() and is_insecure_remote(raw_host):
                if not window.question(_(
                    'The barkd URL "{}" uses plain HTTP over a non-local address, '
                    'which sends your auth token unencrypted.\n\nSave anyway?'
                ).format(raw_host)):
                    return
            self.save_settings(raw_host, token.text(), fake.isChecked())
            for tab in self.tabs.values():
                tab.refresh(sync=False)
