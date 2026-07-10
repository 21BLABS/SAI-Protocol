from web3 import Web3
from dotenv import load_dotenv
import os

load_dotenv('.env')

w3 = Web3(Web3.HTTPProvider(os.getenv('BASE_SEPOLIA_RPC_URL')))
tx_hash = '0x85f6e4d2fd5671b30435d8c20fd8c097979fe9e7ea9ae41caf0d847352119401'

receipt = w3.eth.get_transaction_receipt(tx_hash)

print("Transaction logs:")
for i, log in enumerate(receipt['logs']):
    print(f"\nLog {i}:")
    print(f"  Address: {log['address']}")
    print(f"  Topics: {[t.hex() for t in log['topics']]}")
    print(f"  Data: {log['data'].hex()}")
    
    # Check for SoulCreated event
    if len(log['topics']) >= 4:
        # SoulCreated(address indexed soul, bytes32 indexed composeHash, address indexed owner)
        soul_address = '0x' + log['topics'][1].hex()[-40:]
        compose_hash = log['topics'][2].hex()
        owner = '0x' + log['topics'][3].hex()[-40:]
        print(f"  -> SoulCreated event detected!")
        print(f"     SoulAddress: {soul_address}")
        print(f"     ComposeHash: {compose_hash}")
        print(f"     Owner: {owner}")
