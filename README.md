# electrum-bark-plugin

An [Electrum](https://electrum.org) (Qt) plugin for **barkd**, the wallet daemon of Bark
(Second's implementation of the Ark protocol). Signet only: this is hackathon code.

Full documentation (setup, usage, architecture, what is and is not tested, troubleshooting):
**[documentation.md](documentation.md)**.

## Expected workspace

```
hackathon/
  electrum/  barkd/  electrum-bark-plugin/  venv/
```

## Development quick start

```bash
cd ~/hackathon/electrum-bark-plugin
pip install -r requirements-dev.txt          # barkd-client + pytest
./script/dev_link.sh ../electrum             # symlink bark/ into the Electrum checkout

./script/run_barkd.sh                        # terminal 1: barkd on port 3001
export BARKD_TOKEN=$(./script/barkd_token.sh)
cd ../electrum && ./run_electrum --signet    # terminal 2
```

In Electrum: **Tools -> Plugins -> Bark (Ark)** -> enable, then *Settings* (barkd URL and
token, or tick "Use fake client" to try it without barkd). If you enable the plugin while a
wallet is open and the Bark tab does not appear, close and reopen the wallet.

## Tests

```bash
./script/run_tests.sh        # sets PYTHONPATH (Electrum) and Qt offscreen mode
```

## Demo web app

`Ark Quest.html` is a gamified walkthrough of the Electrum -> barkd -> Ark journey. Open it
directly in a browser for the simulation, or run `python script/bridge.py --fake`
(or without `--fake` for a real barkd) and open http://127.0.0.1:8765/ for live mode.
