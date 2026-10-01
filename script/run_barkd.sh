#!/usr/bin/env bash
# Avvia barkd per lo sviluppo: datadir dedicato, porta 3001 (la 3000 è spesso occupata).
# Variabili: BARKD_DATADIR (default ~/.bark-signet), BARKD_PORT (default 3001), BARKD_BIN.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_barkd_bin.sh"

mkdir -p "$DATADIR"
echo "barkd: $BARKD" >&2
echo "datadir: $DATADIR  port: $PORT" >&2
exec "$BARKD" --datadir "$DATADIR" --port "$PORT"
