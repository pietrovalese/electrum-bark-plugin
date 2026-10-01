# Sourced dagli altri script: imposta BARKD (eseguibile), DATADIR e PORT.
# Ordine di ricerca del binario: $BARKD_BIN, barkd nel PATH, ../barkd/barkd.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_REPO_DIR="$(dirname "$_SCRIPT_DIR")"

if [ -n "${BARKD_BIN:-}" ]; then
    BARKD="$BARKD_BIN"
elif command -v barkd >/dev/null 2>&1; then
    BARKD="$(command -v barkd)"
elif [ -x "$_REPO_DIR/../barkd/barkd" ]; then
    BARKD="$_REPO_DIR/../barkd/barkd"
else
    echo "barkd not found: put it in PATH, in ../barkd/, or set BARKD_BIN." >&2
    exit 1
fi

DATADIR="${BARKD_DATADIR:-$HOME/.bark-signet}"
PORT="${BARKD_PORT:-3001}"
