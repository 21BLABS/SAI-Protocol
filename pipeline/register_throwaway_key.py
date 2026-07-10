"""
SAI Protocol — Phase 1 Pre-requisite: Register Throwaway Key
-------------------------------------------------------------
Calls rotateEnclaveKey() on your deployed SoulAccount, passing the throwaway
EOA address as the new enclave key.

IMPORTANT: This only works if your SoulAccount was deployed pointing at the
real Phala dStack verifier on Base Sepolia AND that verifier actually accepts
your proof. For Phase 1 testing, you have two options:

Option A (recommended for Phase 1): Deploy a fresh SoulAccount that points
at a MockDstackVerifier you also deploy — then any proof passes. This is
exactly what the Foundry test does. Use option B only once you have the real
Phala verifier address confirmed.

Option B: If Phala's verifier is live on Base Sepolia and you have a real
attestation report from a TEE, pass it as --proof-file.

This script uses Option A by default (empty proof bytes, mock verifier).
Switch MOCK_MODE = False and provide a real proof for Option B.
"""

import os
import sys
import time
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
from config import (
    SOUL_ACCOUNT_ADDRESS,
    BASE_SEPOLIA_RPC_URL,
    CHAIN_ID,
    validate_config
)

PRIVATE_KEY        = os.getenv("THROWAWAY_PRIVATE_KEY")
SOUL_ACCOUNT_ADDR  = os.getenv("SOUL_ACCOUNT_ADDRESS", "")
BASE_SEPOLIA_RPC   = os.getenv("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")

ROTATE_ABI = [
    {
        "name": "rotateEnclaveKey",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "newEnclaveKey",   "type": "address"},
            {"name": "validityDuration","type": "uint256"},
            {"name": "hardwareProof",   "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "activeEnclaveKey",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
]

def main():
    parser = argparse.ArgumentParser(description="Register throwaway EOA as SoulAccount enclave key")
    parser.add_argument("--proof-file", default=None, help="Path to raw hardware proof bytes (hex). Omit for empty proof (mock verifier).")
    parser.add_argument("--duration",   default=86400, type=int, help="Key validity in seconds (default: 86400 = 24h)")
    args = parser.parse_args()
    
    if not PRIVATE_KEY:
        print("[ERROR] THROWAWAY_PRIVATE_KEY not set in .env")
        sys.exit(1)
    
    if not SOUL_ACCOUNT_ADDR:
        print("[ERROR] SOUL_ACCOUNT_ADDRESS not set in .env")
        print("Please set SOUL_ACCOUNT_ADDRESS to your deployed SoulAccount contract address")
        sys.exit(1)

    account = Account.from_key(PRIVATE_KEY)
    w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))

    if not w3.is_connected():
        print("[ERROR] Cannot connect to Base Sepolia RPC")
        sys.exit(1)

    print(f"Throwaway EOA   : {account.address}")
    print(f"SoulAccount     : {SOUL_ACCOUNT_ADDR}")
    print(f"Validity        : {args.duration}s ({args.duration // 3600}h)")

    # Load proof bytes
    if args.proof_file:
        with open(args.proof_file, "r") as f:
            proof_hex = f.read().strip().lstrip("0x")
        proof_bytes = bytes.fromhex(proof_hex)
        print(f"Hardware proof  : {len(proof_bytes)} bytes from {args.proof_file}")
    else:
        proof_bytes = b""
        print(f"Hardware proof  : empty (mock verifier mode)")

    soul = w3.eth.contract(
        address=Web3.to_checksum_address(SOUL_ACCOUNT_ADDR),
        abi=ROTATE_ABI
    )

    # Check current state
    current_key = soul.functions.activeEnclaveKey().call()
    print(f"Current key     : {current_key}")

    # Build and send the transaction
    tx = soul.functions.rotateEnclaveKey(
        account.address,
        args.duration,
        proof_bytes,
    ).build_transaction({
        "from":     account.address,
        "nonce":    w3.eth.get_transaction_count(account.address),
        "gas":      200_000,
        "gasPrice": w3.eth.gas_price,
        "chainId":  CHAIN_ID,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\nTx submitted: {tx_hash.hex()}")
    print("Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] == 1:
        new_key = soul.functions.activeEnclaveKey().call()
        print(f"\n[OK] rotateEnclaveKey confirmed.")
        print(f"     activeEnclaveKey is now: {new_key}")
        print(f"     Basescan: https://sepolia.basescan.org/tx/{tx_hash.hex()}")
        print(f"\nYou can now run: python phase1_eoa_pipeline.py")
    else:
        print(f"\n[FAIL] Transaction reverted. Receipt:")
        print(receipt)
        print("\nCommon causes:")
        print("  - Verifier rejected the proof (use a mock verifier for Phase 1)")
        print("  - Rotation cooldown is active (wait 5 minutes and retry)")
        sys.exit(1)


if __name__ == "__main__":
    main()
