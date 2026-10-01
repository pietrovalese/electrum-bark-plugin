#!/usr/bin/env bash
# Collega bark/ dentro un checkout di Electrum (symlink) e lo nasconde da git status.
# Uso: ./script/dev_link.sh ../electrum
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <path-to-electrum-checkout>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$(dirname "$SCRIPT_DIR")/bark"
ELECTRUM_DIR="$(cd "$1" && pwd)"
PLUGINS_DIR="$ELECTRUM_DIR/electrum/plugins"
LINK="$PLUGINS_DIR/bark"

if [ ! -d "$PLUGINS_DIR" ]; then
    echo "not an Electrum checkout: $PLUGINS_DIR does not exist" >&2
    exit 1
fi

if [ -L "$LINK" ]; then
    if [ "$(readlink -f "$LINK")" = "$(readlink -f "$PLUGIN_SRC")" ]; then
        echo "already linked: $LINK -> $PLUGIN_SRC"
    else
        echo "$LINK is a symlink to something else: $(readlink "$LINK")" >&2
        exit 1
    fi
elif [ -e "$LINK" ]; then
    echo "$LINK already exists and is not a symlink; refusing to touch it" >&2
    exit 1
else
    ln -s "$PLUGIN_SRC" "$LINK"
    echo "linked: $LINK -> $PLUGIN_SRC"
fi

# nascondi il link dallo status git del checkout di Electrum
EXCLUDE="$ELECTRUM_DIR/.git/info/exclude"
if [ -d "$ELECTRUM_DIR/.git" ]; then
    mkdir -p "$(dirname "$EXCLUDE")"
    touch "$EXCLUDE"
    grep -qxF 'electrum/plugins/bark' "$EXCLUDE" || echo 'electrum/plugins/bark' >> "$EXCLUDE"
fi
