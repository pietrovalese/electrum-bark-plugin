#!/usr/bin/env bash
# Stampa il token di autenticazione di barkd, da esportare come BARKD_TOKEN:
#   export BARKD_TOKEN=$(./script/barkd_token.sh)
# Usa lo stesso BARKD_DATADIR con cui è stato avviato barkd. Non committare mai il token.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_barkd_bin.sh"

exec "$BARKD" --datadir "$DATADIR" secret show
