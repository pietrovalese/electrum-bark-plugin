import os
import pathlib
import sys

# GUI headless: serve prima che PyQt6 venga importato da qualunque test
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = pathlib.Path(__file__).resolve().parent

# `bark` (il plugin) e `mock_barkd` (il mock) devono essere importabili come moduli top-level.
# Il mock NON si importa come `tests.mock_barkd`: Electrum ha un suo pacchetto `tests`
# che farebbe ombra al nostro.
for p in (str(ROOT), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)
