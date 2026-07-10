"""
SAI Protocol — Spawn SoulAccount Proxy
---------------------------------------
Calls spawnSoul() on the deployed SoulFactory to create a new SoulAccount proxy.
This proxy will be the address used for Phase 1 testing.
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

# Load .env from project root
project_root = Path(__file__).parent.parent
env_file = project_root / ".env"
load_dotenv(env_file, override=True)

# Add parent directory to path for config import
sys.path.insert(0, str(project_root))
from config import CHAIN_ID

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
FACTORY_ADDRESS = "0xD0738384453Bc2c4C0723160bbe38783605323ea"
BASE_SEPOLIA_RPC = os.getenv("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")

# Compose hash for the agent (can be any bytes32)
COMPOSE_HASH = Web3.keccak(text="sai-agent-trader:v1.0").hex()

SPAWN_ABI = [
    {
        "name": "spawnSoul",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "composeHash", "type": "bytes32"},
            {"name": "owner", "type": "address"}
        ],
        "outputs": [{"name": "soul", "type": "address"}]
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "soul", "type": "address"},
            {"indexed": True, "name": "composeHash", "type": "bytes32"},
            {"indexed": True, "name": "owner", "type": "address"}
        ],
        "name": "SoulCreated",
        "type": "event"
    }
]

def main():
    if not PRIVATE_KEY:
        print("[ERROR] PRIVATE_KEY not set in .env")
        sys.exit(1)

    account = Account.from_key(PRIVATE_KEY)
    w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))

    if not w3.is_connected():
        print("[ERROR] Cannot connect to Base Sepolia RPC")
        sys.exit(1)

    print(f"Deployer address: {account.address}")
    print(f"Factory address: {FACTORY_ADDRESS}")
    print(f"Compose hash: {COMPOSE_HASH}")

    factory = w3.eth.contract(
        address=Web3.to_checksum_address(FACTORY_ADDRESS),
        abi=SPAWN_ABI
    )

    # Build and send the transaction
    tx = factory.functions.spawnSoul(
        bytes.fromhex(COMPOSE_HASH),
        account.address  # Set deployer as owner
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 500_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAIN_ID,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\nTx submitted: {tx_hash.hex()}")
    print("Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] == 1:
        # Parse the SoulCreated event to get the proxy address
        soul_address = None
        for log in receipt["logs"]:
            # Check if this is a SoulCreated event
            if log.get("topics") and len(log["topics"]) >= 1:
                # SoulCreated event signature: keccak256("SoulCreated(address,bytes32,address)")
                event_signature = Web3.keccak(text="SoulCreated(address,bytes32,address)").hex()
                if log["topics"][0].hex() == event_signature:
                    # soul address is the first indexed parameter (topics[1])
                    soul_address = "0x" + log["topics"][1].hex()[-40:]
                    print(f"\n[OK] spawnSoul confirmed.")
                    print(f"     Tx hash: {tx_hash.hex()}")
                    print(f"     Basescan: https://sepolia.basescan.org/tx/{tx_hash.hex()}")
                    print(f"\n     SoulAccount proxy address: {soul_address}")
                    print("\nIMPORTANT: Update your .env with:")
                    print(f"SOUL_ACCOUNT_ADDRESS={soul_address}")
                    break
        
        if not soul_address:
            print(f"\n[OK] spawnSoul confirmed but couldn't extract proxy address from logs.")
            print(f"     Tx hash: {tx_hash.hex()}")
            print(f"     Basescan: https://sepolia.basescan.org/tx/{tx_hash.hex()}")
            print("\nPlease check the transaction logs on Basescan to find the proxy address.")
    else:
        print(f"\n[FAIL] Transaction reverted. Receipt:")
        print(receipt)
        sys.exit(1)

if __name__ == "__main__":
    main()
