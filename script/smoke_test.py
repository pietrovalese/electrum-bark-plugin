""" 
Check barkd and the Python client without Electrum. 
Prerequisites: barkd must be running (./script/run_barkd.sh) and BARKD_TOKEN must be exported: export BARKD_TOKEN=$(./script/barkd_token.sh) 
Use BARKD_HOST to connect to a different host. 
Print the barkd URL and a balance snapshot (creating the wallet on signet if it does not exist), then generate a new on-chain address to use for funding barkd. 
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
