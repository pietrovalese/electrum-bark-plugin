import os
import barkd_client
from barkd_client import (
    Configuration, WalletApi, CreateWalletRequest,
    ChainSourceConfig, ChainSourceConfigOneOf1,
    ChainSourceConfigOneOf1Esplora, BarkNetwork,
)
from barkd_client.exceptions import ApiException

cfg = Configuration(host='http://localhost:3001',
                    access_token=os.environ['BARKD_TOKEN'])

with barkd_client.ApiClient(cfg) as client:
    wallet = WalletApi(client)

    try:
        addr = wallet.address().address
    except ApiException as e:
        if "No wallet set" not in str(e.body):
            raise
        print("Wallet assente, lo creo...")
        wallet.create_wallet(CreateWalletRequest(
            ark_server='https://ark.signet.2nd.dev',
            chain_source=ChainSourceConfig(actual_instance=ChainSourceConfigOneOf1(
                esplora=ChainSourceConfigOneOf1Esplora(url='https://esplora.signet.2nd.dev'))),
            network=BarkNetwork.SIGNET,
        ))
        addr = wallet.address().address

    print("Indirizzo Ark:", addr)
    print("Saldo:", wallet.balance())
