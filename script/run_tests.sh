#!/usr/bin/env bash
# Esegue tutta la suite con l'ambiente giusto: Electrum nel PYTHONPATH (per il test della
# GUI) e Qt in modalità offscreen. Argomenti extra vanno a pytest, es.:
#   ./script/run_tests.sh -k client -x
# Electrum si cerca in $ELECTRUM_DIR (default ../electrum). Senza Electrum o PyQt6 il test
# headless della GUI viene saltato; gli altri girano comunque.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELECTRUM_DIR="${ELECTRUM_DIR:-$ROOT/../electrum}"

export PYTHONPATH="$ROOT:$ELECTRUM_DIR${PYTHONPATH:+:$PYTHONPATH}"
export QT_QPA_PLATFORM=offscreen

cd "$ROOT"
exec python -m pytest tests "$@"
