# electrum-bark-plugin — Complete Documentation

> An [Electrum](https://electrum.org) (Qt) plugin that integrates **Bark**, Second's implementation of the **Ark** protocol, through the local **`barkd`** daemon.
> Built for a hackathon. Target network: **signet** (test coins only).

**Document status:** this document explains the project; the source code lives in the repository. What has and has not been verified is described in [§14 What is tested (and what is not)](#14-what-is-tested-and-what-is-not). Read that section before demoing: the plugin has **not** yet been run against a real `barkd` with funded signet coins.

---

## Table of contents

1. [What this project is](#1-what-this-project-is)
2. [Ark concepts you need](#2-ark-concepts-you-need)
3. [Architecture](#3-architecture)
4. [Prerequisites and tested versions](#4-prerequisites-and-tested-versions)
5. [Workspace layout](#5-workspace-layout)
6. [Setup, step by step](#6-setup-step-by-step)
7. [Running barkd](#7-running-barkd)
8. [Getting signet coins](#8-getting-signet-coins)
9. [Running Electrum with the plugin](#9-running-electrum-with-the-plugin)
10. [Using the plugin (walkthrough)](#10-using-the-plugin-walkthrough)
11. [Fake client mode (no barkd, no funds)](#11-fake-client-mode-no-barkd-no-funds)
12. [Repository structure: what each file does and how they communicate](#12-repository-structure-what-each-file-does-and-how-they-communicate)
13. [API mapping: plugin → barkd](#13-api-mapping-plugin--barkd)
14. [What is tested (and what is not)](#14-what-is-tested-and-what-is-not)
15. [Packaging and distribution](#15-packaging-and-distribution)
16. [Troubleshooting](#16-troubleshooting)
17. [Security notes](#17-security-notes)
18. [References](#20-references)

---

## 1. What this project is

Electrum is a self-custodial on-chain Bitcoin wallet written in Python. Ark is a Bitcoin layer-2 protocol for cheap, fast payments. Bark is Second's implementation of Ark. `barkd` is Bark's wallet daemon: it holds an Ark wallet and exposes it over a local REST API.

This plugin adds a **Bark** tab to Electrum's main window that talks to `barkd`:

| Feature | Where in the UI |
|---|---|
| Balances: Ark spendable, Ark boarding (pending), barkd on-chain | Overview |
| **Fund barkd from your Electrum wallet** (puts barkd's fresh on-chain address into Electrum's own Send tab) | Overview, button 1 |
| **Board** all or part of barkd's on-chain funds into Ark | Overview, button 2 / "Board a specific amount" |
| Receive: one **BIP 321** URI + QR code (Ark address, Lightning invoice, optional on-chain fallback) | Receive |
| Send to an Ark address, Lightning invoice / BOLT12 offer / Lightning address, or an on-chain address (paid from the Ark balance) | Send |
| Movement history | History |
| Create the barkd wallet on signet with one click | Header button (shown only when no wallet exists) |
| Fake client for demos/development without barkd | Settings |

The bridge "Electrum on-chain wallet → barkd → Ark" is the headline demo feature: it connects an existing on-chain wallet to Ark without leaving Electrum.

## 2. Ark concepts you need

Short glossary (the official one lives in the Second docs):

* **VTXO** — a virtual UTXO: the off-chain "coins" your Ark balance is made of. VTXOs **expire**; they must be refreshed.
* **Board** — turning on-chain bitcoin into Ark funds. The funding transaction needs confirmations before the funds are spendable on Ark.
* **Round / refresh** — periodic server-coordinated rounds in which VTXOs are renewed with a fresh expiry.
* **Arkoor** — instant out-of-round Ark payments (temporary trust in the server until refreshed).
* **Offboard** — move Ark funds back on-chain with the server's cooperation.
* **Emergency exit** — move funds on-chain *without* the server's cooperation; costlier, and what keeps Ark self-custodial.
* **barkd** — the wallet daemon. **Bark** — the implementation/SDK. **Ark server (ASP)** — Second's server, `https://ark.signet.2nd.dev` on signet.

## 3. Architecture

```
┌──────────────────────────── Electrum (Python, Qt) ───────────────────────────┐
│  bark/qt.py      Plugin class, hooks (load_wallet / close_wallet), settings  │
│  bark/ui.py      BarkTab: Overview | Receive | Send | History                │
│  bark/bark.py    config handling, picks real or fake client                  │
│  bark/client.py  BarkClient  ── only module that imports barkd_client        │
│  bark/fake_client.py  FakeBarkClient (same interface, in-memory)             │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ HTTP + "Authorization: Bearer <token>"   (127.0.0.1:3001)
                ▼
         barkd (daemon, owns the Ark wallet and the keys)
                │
                ├── Ark server    https://ark.signet.2nd.dev
                └── Esplora       https://esplora.signet.2nd.dev
```

Design rules (they explain most of the code):

1. **The GUI thread never blocks.** Every barkd call runs in a worker thread; results return to the GUI thread through a Qt signal (`BarkTab._run`).
2. **One module talks to barkd** (`client.py`). Everything above it handles plain dicts, so the GUI can be tested with `FakeBarkClient`.
3. **Polling is read-only.** The 15-second refresh never generates addresses (barkd's address endpoints create a *new* address on each call).
4. **Errors are typed:** `BarkUnavailable` (barkd down), `BarkNoWallet` (no wallet yet), `BarkError` (everything else, with barkd's message).
5. **Keys never enter Electrum.** The Ark wallet lives in barkd's datadir; the plugin only holds a token.

## 4. Prerequisites and tested versions

| Component | Version used | Notes |
|---|---|---|
| OS | Linux | Commands in this document assume Linux (Debian/Ubuntu package names); barkd availability on other OSes per Second's docs |
| Python | 3.10 (author) / 3.12 (test run) | 3.10+ |
| Electrum (from source) | **4.8.2** (main branch, Oct 2026) | Plugin API changes between versions; pin your checkout |
| barkd | **0.7.1** | the version the author ran |
| `barkd-client` (PyPI) | **0.7.2** | pinned in `requirements.txt` |
| PyQt6 | any recent | installed with Electrum's GUI deps |

System packages (Ubuntu/Debian) needed to build and run Electrum from source:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip build-essential \
    autoconf automake libtool pkg-config libxcb-cursor0
```

(`autoconf automake libtool` are needed because Electrum's `electrum_ecc` dependency compiles libsecp256k1; `libxcb-cursor0` is required by Qt6 on recent Ubuntu.)

## 5. Workspace layout

All commands in this document assume this layout:

```
~/hackathon/
├── electrum/                 # Electrum source checkout (not modified)
├── electrum-bark-plugin/     # THIS repository
├── barkd/                    # (optional) where you keep the barkd binary
└── venv/                     # one Python virtual environment for everything
```

The plugin repo is **separate** from Electrum and linked in with a symlink (§6.4). Do not fork Electrum unless you must change its core.

## 6. Setup, step by step

### 6.1 Python environment and Electrum

```bash
mkdir -p ~/hackathon && cd ~/hackathon
python3 -m venv venv
source venv/bin/activate

git clone https://github.com/spesmilo/electrum.git
cd electrum
git describe --tags            # note the version you are on
pip install --upgrade pip
pip install -r contrib/requirements/requirements.txt
pip install PyQt6 cryptography
cd ..
```

Check that Electrum starts at all (close it after the window appears):

```bash
cd electrum && ./run_electrum --signet && cd ..
```

### 6.2 This repository

```bash
cd ~/hackathon
git clone https://github.com/pietrovalese/electrum-bark-plugin.git
cd electrum-bark-plugin
pip install -r requirements-dev.txt      # barkd-client + pytest
```

If your checkout predates this documentation, make sure the files match the structure in §12, and delete the obsolete `script/smoke_test2.py` and `script/test_client.py`.

### 6.3 barkd

Install `barkd` by following *Install Barkd* in the Second documentation (https://second.tech/docs). Verify:

```bash
barkd --help           # the author ran barkd 0.7.1 (printed in its startup log)
```

### 6.4 Link the plugin into Electrum

```bash
cd ~/hackathon/electrum-bark-plugin
./script/dev_link.sh ../electrum
```

This creates the symlink `electrum/electrum/plugins/bark -> electrum-bark-plugin/bark` and adds it to the Electrum clone's `.git/info/exclude`, so the clone stays clean. Edits to the plugin take effect the next time you start Electrum.

## 7. Running barkd

Open a **dedicated terminal** and leave it running:

```bash
cd ~/hackathon/electrum-bark-plugin
./script/run_barkd.sh          # = barkd --datadir ~/.bark-signet --port 3001
```

Expected log: `Server starting on http://127.0.0.1:3001`. On the first start barkd logs `No auth token found — generated a new one` and `No wallet found. Starting rest server without daemon`; both are normal.

> **Why port 3001?** barkd defaults to 3000, which is commonly taken (Node dev servers, Docker, other tools). If `Address already in use` appears, either free the port (`sudo ss -ltnp | grep :3000`) or keep using 3001. Override with `BARKD_PORT=3002 ./script/run_barkd.sh` and set the same URL in the plugin settings.

### 7.1 The auth token

Every request needs `Authorization: Bearer <token>`. Read it with:

```bash
export BARKD_TOKEN=$(./script/barkd_token.sh)
```

* The `export` lasts for that terminal only.
* **Never commit the token and never paste it in public chats.** If it leaks, rotate it: stop barkd, run `barkd --datadir ~/.bark-signet secret refresh`, restart barkd.
* barkd refuses `--no-auth` on non-local hosts. Keep it bound to `127.0.0.1`.

### 7.2 Smoke test (no Electrum needed)

With barkd running and `BARKD_TOKEN` exported:

```bash
python script/smoke_test.py
```

It prints barkd's URL and a balance snapshot, creating the wallet on signet if none exists, then prints a fresh on-chain address. If this works, barkd and the Python client are fine, and any later problem is in Electrum or the plugin.

## 8. Getting signet coins

You need coins in barkd's **on-chain** wallet before you can board.

1. Get a fresh on-chain address: `python script/smoke_test.py` prints one (or click *Fund barkd…* in the plugin).
2. Request coins from the faucet described in Second's guide **"Test on signet"** (https://second.tech/docs/getting-started/bark-cli/signet) and use the on-chain address (`tb1p…`, **not** the `tark1…` Ark address).
3. Wait for confirmation, then check: `python script/smoke_test.py` → `onchain_confirmed_sat` > 0.

> **Caveat (unverified):** Second's servers live under `2nd.dev` (`ark.signet.2nd.dev`, `esplora.signet.2nd.dev`). If their signet is a network separate from the public one, coins from a generic public signet faucet will **not** arrive. Use the faucet from Second's own guide, and check your address on `https://esplora.signet.2nd.dev` to see whether a transaction appeared. If you cannot get coins in time, use [fake client mode](#11-fake-client-mode-no-barkd-no-funds).

## 9. Running Electrum with the plugin

```bash
cd ~/hackathon/electrum
export BARKD_TOKEN=$(~/hackathon/electrum-bark-plugin/script/barkd_token.sh)   # optional, see below
./run_electrum --signet
```

1. Create or open a **signet** wallet (a throwaway one).
2. **Tools → Plugins → Bark (Ark)** → enable. If you enable it while a wallet is already open, **close and reopen the wallet**: the tab is added by the `load_wallet` hook, which runs when a wallet loads.
3. Click the plugin's **Settings** button (or the *Settings* button inside the Bark tab):
   * **barkd URL:** `http://localhost:3001`
   * **Auth token:** paste the output of `./script/barkd_token.sh`, **or** leave it empty and rely on the `BARKD_TOKEN` environment variable of the shell that launched Electrum.
4. A **Bark** tab appears. The status line should read *Connected to the Ark server*, or *barkd is running but has no wallet yet* with a **Create barkd wallet (signet)** button.

## 10. Using the plugin (walkthrough)

1. **Create the wallet** (first run only): click *Create barkd wallet (signet)*.
2. **Fund barkd from Electrum:** Overview → *1. Fund barkd from this Electrum wallet…*. The plugin asks barkd for a new on-chain address, copies it to the clipboard and pre-fills Electrum's **Send** tab with `bitcoin:<address>`. Enter an amount, pay as usual, wait for 1 confirmation. (Alternatively get coins from the faucet, §8.)
3. **Board:** when *barkd on-chain (confirmed)* shows the funds, press *2. Board all on-chain funds into Ark* (or *Board a specific amount…*). *Ark, boarding (pending)* shows the amount until the funding transaction confirms; then it moves into *Ark balance (spendable)*.
4. **Receive:** Receive tab → optional amount/label/message → *Generate payment request*. You get one BIP 321 URI and QR, plus the Ark address, Lightning invoice and (optionally) on-chain address separately, each with a *Copy* button.
5. **Send:** Send tab → choose *Ark / Lightning (instant)* or *On-chain (paid from Ark balance)*, paste the destination, set an amount (optional for invoices that already carry one), *Send*, confirm.
6. **History:** shows barkd's movements (date, type, status, signed amount, fee, counterparty). It refreshes when you open the tab and after each action.

The *Sync* button forces an on-chain/Ark sync (slow, up to ~90 s timeout). The tab also refreshes balances every 15 s without syncing.

## 11. Fake client mode (no barkd, no funds)

*Settings → "Use fake client"* swaps the real client for `FakeBarkClient`, an in-memory simulation with the same interface and a realistic state machine:

* starts with *no wallet* → *Create barkd wallet* works;
* a **"Fake client: simulate faucet (+100,000 sat)"** button appears in Overview;
* *Board* moves funds to "pending", and they become spendable after two refreshes;
* *Send* decreases the Ark balance and appears in *History*;
* *Receive* returns clearly fake addresses.

Use it to develop the GUI, to rehearse the demo, and as a **fallback when the faucet or Wi-Fi fails** during the presentation. Disable it again to talk to the real barkd.

## 12. Repository structure: what each file does and how they communicate

The source code lives in the repository; this section explains how it is organised.

```
electrum-bark-plugin/
├── README.md                 # this document
├── requirements.txt          # runtime dependency: barkd_client (pinned)
├── requirements-dev.txt      # + pytest
├── .gitignore
├── bark/                     # the plugin: this folder is symlinked or zipped
│   ├── __init__.py
│   ├── manifest.json
│   ├── qt.py
│   ├── bark.py
│   ├── ui.py
│   ├── client.py
│   └── fake_client.py
├── script/                   # developer helpers (shell + one Python script)
├── tests/                    # automated tests
└── demo/
    └── ark-quest.html        # gamified presentation web app (standalone)
```

### 12.1 The plugin files (`bark/`)

| File | What it does | Talks to |
|---|---|---|
| `manifest.json` | Metadata Electrum reads **before** loading any code: internal name, display name, description, supported GUIs (`qt` only), version. Without it Electrum ignores the folder. | Read by Electrum's plugin manager |
| `__init__.py` | Marks the folder as a Python package. Intentionally empty of logic. | – |
| `qt.py` | **Entry point.** For the Qt GUI, Electrum instantiates the `Plugin` class defined here. It registers Electrum hooks so that a *Bark* tab is added when a wallet window opens and removed when it closes or when the plugin is disabled, and it provides the *Settings* dialog (URL, token, fake-client switch). | Electrum (hooks, plugin manager, main window); inherits from `bark.py`; creates the tab from `ui.py` |
| `bark.py` | **GUI-independent plugin core.** Reads and writes the plugin's settings in Electrum's config file and decides which client object the rest of the plugin gets: the real one or the fake one. | Electrum's config; `client.py`; `fake_client.py` |
| `ui.py` | **The Bark tab** with its four pages: Overview, Receive, Send, History. Owns the 15-second refresh timer, runs every barkd call in a background thread, and turns results or errors into labels, tables, QR codes and dialogs. Also contains the bridge to Electrum's own Send tab. | The plugin object (settings, client); the client (through worker threads); Electrum's main window (dialogs, clipboard, Send tab) |
| `client.py` | **The only file that talks to barkd.** Wraps the `barkd_client` library into a small set of methods that return plain Python values, sets timeouts, validates amounts, and converts every failure into one of three typed errors: barkd unreachable, no wallet yet, or generic error with barkd's message. | barkd's REST API (via `barkd_client`) |
| `fake_client.py` | A stand-in with the **same methods** as the real client but entirely in memory: a simulated wallet that can be created, funded by a fake faucet, boarded (funds become spendable after a couple of refreshes), spent and listed in the history. Never touches the network. | Re-uses the error types from `client.py` |

### 12.2 Scripts (`script/`)

| File | Purpose |
|---|---|
| `run_barkd.sh` | Starts barkd for development on port 3001 with its own data directory. Keep it running in a dedicated terminal. |
| `barkd_token.sh` | Prints barkd's auth token, meant to be exported as `BARKD_TOKEN`. |
| `smoke_test.py` | Checks barkd and the client without Electrum: connects, creates the wallet if missing, prints a balance snapshot and a fresh on-chain address. First thing to run when something seems broken. |
| `dev_link.sh` | Symlinks `bark/` into an Electrum checkout and hides it from that checkout's git status, so edits apply on the next Electrum start. |
| `run_tests.sh` | Runs the whole test suite with the right environment (Electrum on the Python path, Qt in offscreen mode). |
| `build_zip.sh` | Packages the plugin as `dist/bark-<version>.zip` for Electrum's *Plugins → Add*. |

### 12.3 Tests (`tests/`)

| File | Purpose |
|---|---|
| `mock_barkd.py` | A tiny fake barkd HTTP server (standard library only) that answers with barkd-shaped JSON and can simulate "no wallet", wrong token and unknown routes. It also records every request it receives. |
| `test_client.py` | Runs the **real** `barkd_client` library against the mock server: checks parsing, error mapping, input validation, the exact request bodies sent, and that polling never creates addresses. |
| `test_fake_client.py` | Basic behaviour of the fake client. |
| `test_ui_headless.py` | Drives the real tab (real Electrum Qt widgets, no screen) through the complete user journey using the fake client and a stub Electrum window. |
| `conftest.py` | Makes the plugin and the mock importable by the tests. |

### 12.3b The demo app (`demo/`)

| File | Purpose |
|---|---|
| `ark-quest.html` | A single self-contained page (no build step, no server, no dependencies except optional web fonts) used for the presentation. It **simulates** the Electrum → barkd → Ark journey as a five-mission game. It does not talk to barkd or to the plugin; it only mirrors their behaviour and shows the real endpoint each step would call. Open it in any browser, or host it as a static file. |

### 12.4 Who depends on whom

Dependencies point one way only:

```
manifest.json ─ read by ─► Electrum
Electrum ─ loads ─► qt.py ─ inherits ─► bark.py ─ imports ─► client.py ─► barkd_client ─► barkd
                    │                      └───── imports ─► fake_client.py ─ imports ─► client.py (errors only)
                    └─ creates ─► ui.py ─ imports ─► client.py (errors), fake_client.py (one demo button)
```

* `client.py` and `fake_client.py` know nothing about Qt or Electrum. That is why they can be tested with plain `pytest`.
* `ui.py` never calls barkd directly; it only calls methods on whichever client the plugin gives it, so real and fake clients are interchangeable.
* Only `qt.py` and `ui.py` import Electrum GUI code.
* `demo/ark-quest.html` is fully independent of everything else in the repository.

### 12.5 How the pieces communicate at runtime

**A. Enabling the plugin.** Electrum reads `manifest.json`, lists the plugin in *Tools → Plugins*, and on enabling loads `qt.py` and creates its `Plugin` object. When a wallet window loads, Electrum fires the `load_wallet` hook; the plugin creates a `BarkTab`, adds it to the window's tabs and triggers a first refresh. On `close_wallet` (or when the plugin is disabled) the tab is removed and its timer stopped.

**B. Background refresh (every 15 s).** The tab's timer asks the plugin for a client and runs its balance snapshot in a worker thread. The client calls barkd (balance, connection state, on-chain balance) and returns a plain dictionary; a Qt signal carries it back to the GUI thread, which updates the labels. If an action is already running, the refresh is skipped. Refreshes are read-only and never create addresses.

**C. A user action, for example "Board all".**

```
You click ─► ui.py asks for confirmation (Electrum dialog)
          ─► ui.py disables the buttons and starts a worker thread
          ─► client.py sends the request to barkd (POST …/boards/board-all)
          ─► barkd talks to the Ark server and the chain, answers
          ─► client.py returns a plain result, or raises a typed error
          ─► Qt signal ─► GUI thread: message box, buttons re-enabled,
                          balances and history refreshed
```

**D. The Electrum bridge ("Fund barkd from this Electrum wallet").** The tab asks barkd for a fresh on-chain address, copies it to the clipboard, and pre-fills **Electrum's own Send tab** with a `bitcoin:` URI before switching to it. You then pay from your normal Electrum wallet. This is the only place where the plugin reaches into Electrum's internals, so it has a safe fallback (clipboard plus an explanatory message) if a future Electrum version changes that part.

**E. Error propagation.** Network and HTTP failures are translated once, in `client.py`, into three kinds of error. `ui.py` decides what to show: a *Create wallet* button for "no wallet", a "barkd is not reachable" status line, or an error dialog carrying barkd's own message.

**F. Changing settings.** The settings dialog (in `qt.py`) stores URL, token and the fake flag through `bark.py` into Electrum's config. The plugin discards any fake-client state, and every open tab refreshes immediately.

**G. Fake mode.** When the fake flag is on, `bark.py` hands out the same in-memory fake client object on every call, so state (balances, history) persists across clicks. Nothing else in the plugin changes, which is what makes the demo fallback trustworthy.

### 12.6 Where data and secrets live

| Data | Location |
|---|---|
| Ark keys, wallet database, auth token | barkd's data directory (default `~/.bark-signet`). The plugin never sees the keys. |
| barkd URL, optional token, fake-client flag | Electrum's config file (`bark_host`, `bark_token`, `bark_use_fake`). The token is stored in clear text there; the safer option is the `BARKD_TOKEN` environment variable. |
| Balances, history | Not stored by the plugin: always read from barkd (or from the fake client's memory). |

### 12.7 Where to add a new feature

1. New barkd capability → add a method in `client.py` (validation, timeout, plain return value) and the matching one in `fake_client.py`.
2. Add a route to `mock_barkd.py` and a test in `test_client.py`.
3. Add the button, field or table in `ui.py` using the same pattern as the existing actions: confirm, run in the background, show the result, refresh.
4. Update the mapping table in §13 and the limitations list in §18.

## 13. API mapping: plugin → barkd

| `BarkClient` method | `barkd_client` call | REST endpoint | Used by |
|---|---|---|---|
| `snapshot()` | `WalletApi.balance` | `GET /api/v1/wallet/balance` | Overview, polling |
| | `WalletApi.connected` | `GET /api/v1/wallet/connected` | status line |
| | `OnchainApi.onchain_balance` | `GET /api/v1/onchain/balance` | Overview |
| `sync()` / `snapshot(sync=True)` | `OnchainApi.onchain_sync` | `POST /api/v1/onchain/sync` | *Sync* button |
| `history()` | `HistoryApi.list` | `GET /api/v1/history` | History tab |
| `pending_boards()` | `BoardsApi.get_pending_boards` | `GET /api/v1/boards/pending` | (available, not yet shown in the UI) |
| `new_onchain_address()` | `OnchainApi.onchain_address` | `POST /api/v1/onchain/addresses/next` | *Fund barkd…* |
| `receive_uri()` | `WalletApi.bip321_uri` | `POST /api/v1/wallet/bip321` | Receive tab |
| `create_wallet()` | `WalletApi.create_wallet` | `POST /api/v1/wallet/create` | *Create barkd wallet* |
| `board_all()` | `BoardsApi.board_all` | `POST /api/v1/boards/board-all` | Overview |
| `board_amount()` | `BoardsApi.board_amount` | `POST /api/v1/boards/board-amount` | Overview |
| `send()` | `WalletApi.send` | `POST /api/v1/wallet/send` | Send tab (Ark/Lightning) |
| `send_onchain()` | `WalletApi.send_onchain` | `POST /api/v1/wallet/send-onchain` | Send tab (on-chain) |

Other endpoints you may want next (all present in `barkd-client 0.7.2`): `WalletApi.refresh_all` (renew VTXOs), `WalletApi.offboard_all`, `WalletApi.vtxos`, `LightningApi.generate_invoice` / `pay` / `get_receive_status`, `NotificationsApi.wait_notification` / `websocket_ticket`, `FeesApi` (fee estimates), `ExitsApi` (emergency exits). To discover method names and models, open a Python shell in the venv, `import barkd_client`, and list the names ending in `Api`; each API class lists its methods with `dir()`, `inspect.signature` shows what a method expects, and request/response models are pydantic classes whose `model_fields` lists their fields.

## 14. What is tested (and what is not)

### Verified

| Area | How | Result |
|---|---|---|
| `BarkClient` against barkd's REST shapes (balances, history, boards, send, BIP 321, no-wallet, 401, unreachable, validation, "polling creates no addresses") | `tests/test_client.py` runs the **real `barkd-client` library** against `tests/mock_barkd.py`, a stdlib HTTP server returning barkd-shaped JSON | 12 tests pass |
| `FakeBarkClient` | `tests/test_fake_client.py` | pass |
| Whole GUI flow: no wallet → create → fund bridge → faucet → board → board confirms → receive → send → history | `tests/test_ui_headless.py`: real `BarkTab` with real Electrum 4.8.2 Qt widgets (`QRCodeWidget` etc.) under `QT_QPA_PLATFORM=offscreen`, with a stub window and the fake client | pass |
| Plugin module imports as Electrum imports it; hook names (`load_wallet`, `close_wallet`) exist in Electrum 4.8.2; `config.set_key/get` exist | import check + source inspection | OK |
| Zip build produces `bark/manifest.json` + code | `script/build_zip.sh` | OK |

Total: **15 tests**, run with `./script/run_tests.sh`.

### NOT verified — check these yourself first

1. **A real barkd with real signet coins.** The mock reproduces response *shapes* from the client library, not barkd's behaviour. Board, send and receive have never been executed against a live server.
2. **A real Electrum window.** The GUI test uses a stub window. Not yet exercised live: the tab inside the real window, the settings dialog, and the bridge `send_tab.set_payment_identifier(...)` (its existence was checked in the source, its effect was not).
3. **BIP 321 details.** Unknown whether barkd returns a Lightning invoice when no amount is given, and what `onchain=false` omits. The UI shows whatever comes back (fields can be empty or `None`).
4. **`send_onchain` semantics.** Treated as "pay an on-chain address from the Ark balance". Read the endpoint's description in the Second API reference before relying on it.
5. **Whether public signet faucets work with Second's signet** (see §8).
6. **Python 3.10** (the author's interpreter). Tests ran on 3.12; the code uses no 3.11+ features.

Recommended first live check, in order: `smoke_test.py` → open the tab → *Fund barkd…* → faucet/transfer → board → watch *Ark, boarding (pending)* turn into spendable. Fix what breaks in that order.

### Running the tests

```bash
cd ~/hackathon/electrum-bark-plugin
source ../venv/bin/activate
./script/run_tests.sh        # sets PYTHONPATH to ../electrum and QT_QPA_PLATFORM=offscreen
```

The headless GUI test is skipped automatically if Electrum/PyQt6 are not importable. Note: the tests deliberately import the mock as `mock_barkd` (not `tests.mock_barkd`) because Electrum ships its own top-level `tests` package that would otherwise shadow ours.

## 15. Packaging and distribution

```bash
./script/build_zip.sh        # -> dist/bark-0.1.0.zip  (version from bark/manifest.json)
```

Electrum 4.8 supports external plugins as zip files: **Tools → Plugins → Add**, select the zip, and confirm with your authorization password. Electrum stores them in `<electrum data dir>/plugins`.

Important: the plugin imports `barkd_client`, which Electrum does not ship. The Python environment that **runs Electrum** must have it:

```bash
pip install barkd_client==0.7.2
```

This works when you run Electrum from source in your venv (this project). It will **not** work with Electrum's pre-built binaries (AppImage/Windows/macOS), which have no way to install extra packages. For the hackathon, present the from-source setup and the symlink workflow.

Bump the version in `bark/manifest.json` before building a release zip.

## 16. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Error: Failed to bind to address … Address already in use` (barkd) | Port taken. Find it: `sudo ss -ltnp \| grep :3000`. Use another port: `BARKD_PORT=3001 ./script/run_barkd.sh` and set the same URL in the settings. Do not kill processes you do not recognise. |
| Status: *barkd is not reachable* | barkd not running, wrong URL/port in Settings, or barkd on another datadir. Check the barkd terminal. |
| Error *Unauthorized: wrong or missing barkd token* | Token in Settings (or `BARKD_TOKEN`) differs from barkd's. Re-run `./script/barkd_token.sh` with the **same** `BARKD_DATADIR`. After `secret refresh`, restart barkd. |
| *barkd error 422 … No wallet set* | No wallet yet: press *Create barkd wallet* (or run `smoke_test.py`). |
| `create_wallet` says the wallet already exists | Fine — it exists; press *Sync*. To start over, stop barkd and use a new `--datadir` (signet only!). |
| Bark tab missing | Plugin not enabled; or enabled while a wallet was open (close and reopen the wallet); or symlink broken (`ls -l electrum/electrum/plugins/bark`); or the wallet window is not a Qt window. Launch with `./run_electrum --signet -v` and read the terminal for import errors. |
| `No module named 'barkd_client'` in Electrum's log | `pip install barkd_client==0.7.2` in the **same venv** that runs Electrum. |
| `ModuleNotFoundError: electrum_ecc` / build errors installing Electrum deps | `sudo apt install autoconf automake libtool pkg-config`, then reinstall requirements. |
| Qt error `xcb … could not load the Qt platform plugin` | `sudo apt install libxcb-cursor0`. |
| Balances stay at 0 after the faucet | Not confirmed yet, wrong address type (use `tb1p…` on-chain, not `tark1…`), or a faucet for a different signet (§8). Press *Sync*; check the address on `https://esplora.signet.2nd.dev`. |
| *Board* fails with insufficient funds | Funds must be **confirmed** on-chain in barkd (`barkd on-chain (confirmed)`), not only pending. |
| Funds disappeared after boarding | They are in *Ark, boarding (pending)* until the board confirms, then in *Ark balance (spendable)*. |
| Receive: Lightning invoice empty / error | See §14 item 3; try with an amount, or uncheck the on-chain option, and read barkd's error message. |
| UI feels slow right after clicking *Sync* | Sync can take a while (timeout 90 s); the UI stays responsive, only action buttons are disabled meanwhile. |
| Settings changes ignored | Click OK in the dialog; the tab refreshes automatically. For env-var tokens, restart Electrum from a shell where `BARKD_TOKEN` is exported. |
| Tests: `No module named tests.mock_barkd` | You are importing the wrong `tests` package; use `./script/run_tests.sh` and keep the `from mock_barkd import …` form. |

## 17. Security notes

* **Signet only.** This is hackathon code. Do not point it at mainnet funds.
* The barkd **token controls the wallet**. The plugin stores it **in clear text** in Electrum's config if you type it into Settings. Prefer leaving the field empty and exporting `BARKD_TOKEN` in the launching shell.
* Keep barkd on `127.0.0.1`. Do not expose its port to the network.
* barkd's mnemonic endpoint is disabled by default; leave it disabled.
* The mnemonic alone restores Ark funds only with the server's cooperation; a full recovery also needs the datadir/database backup (see Second's backup docs). Irrelevant on signet, worth stating in a demo.
* Never commit tokens, datadirs or mnemonics. `.gitignore` already excludes `.env`, `venv/`, `dist/`. If a token ever lands in git history, rotate it (`secret refresh`).
* The *Send* flow asks for confirmation showing destination and amount before calling barkd. Keep that.

## 18. References

* Bark SDK docs: https://second.tech/docs/bark-sdk
* Barkd docs and REST API reference: https://second.tech/docs (section *Barkd*; clients page for the Python client `barkd-client`)
* Signet guide: https://second.tech/docs/getting-started/bark-cli/signet
* Electrum source: https://github.com/spesmilo/electrum (`electrum/plugin.py`, `electrum/plugins/README`, and existing plugins such as `labels` as templates)
* Project repository: https://github.com/pietrovalese/electrum-bark-plugin
