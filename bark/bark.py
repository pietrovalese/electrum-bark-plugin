from electrum.plugin import BasePlugin

from .client import BarkClient, DEFAULT_HOST
from .fake_client import FakeBarkClient


class BarkPlugin(BasePlugin):
    """Nucleo del plugin, indipendente dalla GUI: impostazioni e scelta del client."""

    def __init__(self, parent, config, name):
        BasePlugin.__init__(self, parent, config, name)
        self._fake = None

    # --- config (chiavi semplici; il token è in chiaro nella config: ok per hackathon,
    #     meglio lasciarlo vuoto e usare la variabile d'ambiente BARKD_TOKEN) ---
    def get_host(self) -> str:
        return self.config.get('bark_host') or DEFAULT_HOST

    def get_token(self) -> str:
        return self.config.get('bark_token') or ''

    def use_fake(self) -> bool:
        return bool(self.config.get('bark_use_fake', False))

    def save_settings(self, host: str, token: str, use_fake: bool):
        self.config.set_key('bark_host', host.strip())
        self.config.set_key('bark_token', token.strip())
        self.config.set_key('bark_use_fake', bool(use_fake))
        self.reset_fake()   # le impostazioni cambiano: lo stato finto precedente si scarta

    def reset_fake(self):
        self._fake = None

    def client(self):
        """Il client da usare ora: quello finto (sempre lo stesso oggetto) o quello reale."""
        if self.use_fake():
            if self._fake is None:           # stato persistente tra una chiamata e l'altra
                self._fake = FakeBarkClient('no_wallet')
            return self._fake
        return BarkClient(host=self.get_host(), token=self.get_token())
