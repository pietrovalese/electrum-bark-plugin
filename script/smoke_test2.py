import os
import barkd_client
from barkd_client import Configuration, WalletApi, OnchainApi

cfg = Configuration(host='http://localhost:3001',
                    access_token=os.environ['BARKD_TOKEN'])

with barkd_client.ApiClient(cfg) as client:
    wallet = WalletApi(client)
    onchain = OnchainApi(client)

    print("Wallet esiste:", wallet.wallet_exists())
    print("Connesso al server Ark:", wallet.connected())

    onchain.onchain_sync()                       
    print("Indirizzo on-chain:", onchain.onchain_address())
    print("Saldo on-chain:", onchain.onchain_balance())
    print("Indirizzo Ark:", wallet.address().address)
    print("Saldo Ark:", wallet.balance())
