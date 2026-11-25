# electrum-bark-plugin

An [Electrum](https://electrum.org) (Qt) plugin that drives **barkd**, the wallet daemon of **Bark**
(Second's implementation of the **Ark** protocol), through its local REST API.

It adds a *Bark* tab to the Electrum main window: Ark and on-chain balances, a one-click bridge from an
Electrum on-chain wallet to barkd's wallet, boarding, BIP 321 payment requests, Ark / Lightning / on-chain
payments, and movement history. Private keys never enter Electrum: the Ark wallet lives in barkd's datadir
and the plugin only holds an API bearer token.

> **Scope:** signet only, version `0.1.1`. Do not point it at mainnet funds (mainnet addresses are rejected by the client).
> **Verification status:** the 92-test suite passes (Python 3.10.12, Electrum 4.8.2, PyQt6 offscreen), the
> plugin loads through Electrum's real `Plugins` manager, and `barkd 0.7.1` was verified live against
> `https://ark.signet.2nd.dev` (`smoke_test.py`, `snapshot(sync=True)`, `new_onchain_address`, `receive_uri`,
> live Ark receive via `arkfaucet.com`, live `arkoor` `send`, `history`, and `BarkTab` Qt rendering against the
> live client). Details and remaining unverified flows (on-chain boarding / `send_onchain` / full `ElectrumWindow`):
> [documentation.md §15](documentation.md#15-known-limitations).

## Features

| Feature | Tab | barkd endpoint(s) |
|---|---|---|
| Balances: Ark spendable, Ark boarding (pending + in-flight), barkd on-chain | Overview | `GET /wallet/balance`, `GET /onchain/balance`, `GET /wallet/connected` |
| **Fund barkd from Electrum**: fresh barkd address copied to the clipboard and pre-filled in Electrum's own Send tab | Overview | `POST /onchain/addresses/next` |
| Board all / a specific amount of barkd's on-chain funds into Ark | Overview | `POST /boards/board-all`, `POST /boards/board-amount` |
| One BIP 321 URI + QR (Ark address, BOLT11 if an amount is set, optional on-chain fallback) | Receive | `POST /wallet/bip321` |
| Pay an Ark address / BOLT11 / BOLT12 / Lightning address, or an on-chain address from the Ark balance | Send | `POST /wallet/send`, `POST /wallet/send-onchain` |
| Movements (date, type, status, signed amount, fee, counterparty) | History | `GET /history` |
| Create the barkd wallet on signet (shown only when barkd has no wallet) | Header | `POST /wallet/create` |
| Manual full sync (both Ark wallet and on-chain wallet) | Header | `POST /wallet/sync`, `POST /onchain/sync` |
| In-memory `FakeBarkClient` (same interface) for development and demos without barkd or funds | Settings | none |

## Architecture at a glance

```
┌──────────────────────── Electrum process (Python, Qt) ────────────────────────┐
│ bark/qt.py          Plugin: hooks load_wallet / close_wallet, settings dialog │
│ bark/ui.py          BarkTab (Overview | Receive | Send | History), 15 s poll  │
│ bark/bark.py        BarkPlugin: config keys, client selection (real / fake)   │
│ bark/client.py      BarkClient: the ONLY importer of barkd_client             │
│ bark/fake_client.py FakeBarkClient: same interface, in-memory state machine   │
└──────────────┬────────────────────────────────────────────────────────────────┘
               │ HTTP + "Authorization: Bearer <token>"   (default http://localhost:3001)
               ▼
        barkd  (owns keys, VTXOs, wallet DB)  ──►  Ark server  https://ark.signet.2nd.dev
                                              └──►  Esplora     https://esplora.signet.2nd.dev
```

Design invariants: no I/O on the GUI thread (one worker thread per call, results return through a Qt
signal); `client.py` is Qt/Electrum-free and returns plain `dict`/`list`/`str`; polling is strictly
read-only (barkd's address endpoints allocate a new address on every call); failures surface as three
typed errors (`BarkUnavailable`, `BarkNoWallet`, `BarkError`). See [documentation.md §3](documentation.md#3-architecture).

## Requirements

| Component | Version | Status |
|---|---|---|
| Python | 3.10+ | 3.12.3: full suite verified; 3.10: author-reported |
| Electrum (from source) | 4.8.2 | verified (plugin API changes between versions: pin your checkout) |
| `barkd_client` (PyPI) | `0.7.2` (pinned in `requirements.txt`) | verified |
| barkd | 0.7.1 | verified live (`smoke_test.py`, `receive_uri`, `history`) |
| PyQt6 | any recent | verified |

The plugin imports `barkd_client`, which Electrum does not ship, so the interpreter running Electrum must
provide it. This works for source checkouts; it cannot work with Electrum's prebuilt binaries.

## Quick start (development)

```bash
# System packages (Debian/Ubuntu): electrum_ecc compiles libsecp256k1; Qt6 needs xcb-cursor
sudo apt install -y git python3-venv python3-pip build-essential autoconf automake libtool pkg-config libxcb-cursor0

# Environment, Electrum, plugin
mkdir -p ~/hackathon && cd ~/hackathon
python3 -m venv venv && source venv/bin/activate
git clone https://github.com/spesmilo/electrum.git
pip install --upgrade pip
pip install -r electrum/contrib/requirements/requirements.txt PyQt6 cryptography
git clone https://github.com/pietrovalese/electrum-bark-plugin.git
cd electrum-bark-plugin
pip install -r requirements-dev.txt      # barkd_client==0.7.2 + pytest

# Symlink bark/ into the Electrum checkout and hide it from that checkout's git status
./script/dev_link.sh ../electrum

# Terminal 1: barkd (binary on $PATH, in ../barkd, ../barkd/barkd, or $BARKD_BIN)
./script/run_barkd.sh                       # barkd --datadir ~/.bark-signet --port 3001

# Terminal 2: Electrum on signet
export BARKD_TOKEN="$(./script/barkd_token.sh)"
cd ../electrum && ./run_electrum --signet -v
```

In Electrum: **Tools → Plugins → Bark (Ark) → Enable**, then **Settings** (barkd URL and token, or tick
*Use fake client*). The tab attaches automatically to already-open wallet windows as well as newly loaded ones.

Check barkd and the client without Electrum: `python script/smoke_test.py` (needs `BARKD_TOKEN`).

## Configuration

| Setting | Stored in | Resolution order |
|---|---|---|
| barkd URL | Electrum config key `bark_host` | `bark_host` → `$BARKD_HOST` → `http://localhost:3001`. |
| Auth token | Electrum config key `bark_token` (**clear text**, `<datadir>/signet/config`) | `bark_token` → `$BARKD_TOKEN` of the process that launched Electrum → error `barkd token missing`. Prefer leaving the field empty and exporting `BARKD_TOKEN`. |
| Fake client | Electrum config key `bark_use_fake` | `false` by default; saving settings discards the fake's state. |

Script variables: `BARKD_BIN`, `BARKD_DATADIR` (default `~/.bark-signet`), `BARKD_PORT` (default `3001`),
`ELECTRUM_DIR` (default `../electrum`, used by `run_tests.sh`).

## Tests

```bash
./script/run_tests.sh          # PYTHONPATH += repo + $ELECTRUM_DIR, QT_QPA_PLATFORM=offscreen, then pytest tests
./script/run_tests.sh -k client -x
```

| Module | Tests | Subject |
|---|---|---|
| `tests/test_client.py` | 37 | the real `barkd_client` against `tests/mock_barkd.py` (stdlib HTTP server): parsing, in-flight balance, error mapping, read-timeout, mainnet rejection, validation, exact request bodies, "polling creates no addresses" |
| `tests/test_fake_client.py` | 14 | `FakeBarkClient` state machine and error paths |
| `tests/test_settings.py` | 13 | URL security check, config/`BARKD_HOST` precedence, Qt plugin hooks & open-window attach, `bridge.py` HTTP guards/errors |
| `tests/test_ui_headless.py` | 28 | the real `BarkTab` with real Electrum Qt widgets, a stub window and the fake client |

Without Electrum or PyQt6 importable, Qt GUI tests are skipped; with them, `92 passed`.

## Repository layout

```
bark/            the plugin (symlinked into Electrum, or zipped by build_zip.sh)
script/          run_barkd.sh  barkd_token.sh  _barkd_bin.sh  dev_link.sh  build_zip.sh  run_tests.sh
                 smoke_test.py  bridge.py
tests/           pytest suite and the mock barkd
Ark Quest.html   pixel-art demo game: simulation, or live mode when served by script/bridge.py
docs/index.html  static, simulation-only copy of the game for hosting
documentation.md full technical documentation
```

## Demo app

`Ark Quest.html` ("B(Ark) Quest") is a self-contained canvas game that walks through
Electrum → barkd → Ark. Opened directly it is a pure simulation. Served by the bridge it switches to live
mode and calls the same `BarkClient` / `FakeBarkClient` methods as the plugin:

```bash
python script/bridge.py --fake     # fake client, no barkd needed
python script/bridge.py            # real barkd (BARKD_TOKEN / BARKD_HOST)
# then open http://127.0.0.1:8765/
```

The bridge binds to loopback and requires a custom header, but it has **no confirmation step**: in live mode
any local process that sends `X-Ark-Quest: 1` can make barkd spend its funds. Use it on signet only.

## Packaging

`./script/build_zip.sh` writes `dist/bark-<version>.zip` (version from `bark/manifest.json`, currently `0.1.1`)
for Electrum's **Tools → Plugins → Add**. The target interpreter still needs `barkd_client==0.7.2`.

## Security notes

* The bearer token controls the barkd wallet (send, board, offboard). It is stored in clear text in Electrum's
  config if typed into Settings, and it travels over plain HTTP: keep barkd bound to `127.0.0.1`. The Settings
  dialog asks for confirmation if you enter a non-local `http://` URL.
* Never commit tokens, datadirs or mnemonics. `.gitignore` excludes `__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `dist/`, `venv/`, `.venv/`, `.env`, and `*.egg-info/`.
* Rotate a leaked token with barkd's `secret refresh` command, then restart barkd.

## License

Licensed under MIT — see [LICENSE](LICENSE).

Full documentation: **[documentation.md](documentation.md)**.