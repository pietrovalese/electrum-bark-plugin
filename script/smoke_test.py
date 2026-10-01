"""Controlla barkd e il client Python senza Electrum.

Prerequisiti: barkd avviato (./script/run_barkd.sh) e BARKD_TOKEN esportato
(export BARKD_TOKEN=$(./script/barkd_token.sh)). Host diverso: BARKD_HOST.

Stampa l'URL di barkd e un'istantanea dei saldi (creando il wallet su signet se manca),
poi un nuovo indirizzo on-chain da usare per finanziare barkd.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bark.client import BarkClient, BarkError, BarkNoWallet, BarkUnavailable  # noqa: E402


def main() -> int:
    client = BarkClient()
    print("barkd URL:", client.host)
    try:
        try:
            snap = client.snapshot(sync=True)
        except BarkNoWallet:
            print("No wallet yet, creating one on signet...")
            client.create_wallet()
            snap = client.snapshot(sync=True)
        print("Snapshot:", json.dumps(snap, indent=2))
        print("Fresh on-chain address:", client.new_onchain_address())
    except BarkUnavailable as e:
        print(f"barkd is not reachable at {client.host}: {e}\n"
              "Is ./script/run_barkd.sh running?", file=sys.stderr)
        return 1
    except BarkError as e:
        print("Error:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
