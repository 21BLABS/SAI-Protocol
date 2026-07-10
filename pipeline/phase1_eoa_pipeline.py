"""
SAI Protocol — Phase 1: Naked EOA 4337 Pipeline
------------------------------------------------
Purpose: Prove the full UserOperation flow works against the real Base Sepolia
EntryPoint before touching any TEE code. Uses a throwaway EOA key instead of
an enclave key — the SoulAccount doesn't care where the key came from, only
that it matches activeEnclaveKey and the signature is valid.

What this script does:
  1. Loads a throwaway EOA key and derives its address
  2. Validates the RPC endpoint is actually Base Sepolia (chain ID check)
  3. Reads on-chain state from the deployed SoulAccount
  4. Builds a minimal UserOperation (a zero-value self-call, just to prove validation)
  5. Signs it the same way the TEE will sign it (eth_sign prefix + ecrecover)
  6. Estimates gas via the bundler (with retry on transient failures)
  7. Submits to Pimlico bundler on Base Sepolia (with retry)
  8. Polls until the op lands on-chain and prints the tx hash

Success criteria: script exits with "PASS" and a tx hash you can look up on
Basescan. That means validateUserOp accepted the signature, gas was paid, and
the EntryPoint executed the operation.

Pre-requisites:
  - SoulAccount proxy deployed and its throwaway EOA registered as activeEnclaveKey
    (run rotateEnclaveKey with your throwaway key first — see README)
  - .env file filled in (copy from .env.example)
  - pip install -r requirements.txt

Changes from v1:
  - Chain ID validation: confirms RPC is Base Sepolia before doing anything
  - Retry logic: bundler_rpc retries up to 3x on transient network failures
  - Clearer error context on gas estimation failure
"""

import os
import sys
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# Load .env from project root
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env", override=True)

# Add parent directory to path for config import
sys.path.insert(0, str(project_root))
from config import (
    SOUL_ACCOUNT_ADDRESS,
    PIMLICO_RPC_URL,
    BASE_SEPOLIA_RPC_URL,
    ENTRY_POINT,
    CHAIN_ID,
    validate_config
)

# ─── Config ───────────────────────────────────────────────────────────────────

PRIVATE_KEY       = os.getenv("THROWAWAY_PRIVATE_KEY")
SOUL_ACCOUNT_ADDR = os.getenv("SOUL_ACCOUNT_ADDRESS", "")
BASE_SEPOLIA_RPC  = os.getenv("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
PIMLICO_RPC       = os.getenv("PIMLICO_RPC_URL", "")

# Bundler retry config
RPC_MAX_RETRIES = 3
RPC_RETRY_DELAY = 2  # seconds between retries

# ─── Validation ───────────────────────────────────────────────────────────────

def check_env():
    if not PRIVATE_KEY:
        print("[ERROR] THROWAWAY_PRIVATE_KEY not set in .env")
        sys.exit(1)
    if not SOUL_ACCOUNT_ADDR:
        print("[ERROR] SOUL_ACCOUNT_ADDRESS not set in .env")
        sys.exit(1)
    if not PIMLICO_RPC:
        print("[ERROR] PIMLICO_RPC_URL not set in .env")
        sys.exit(1)

def validate_chain(w3: Web3):
    """
    Confirm the RPC endpoint is actually Base Sepolia (chainId 84532).
    Catches the case where BASE_SEPOLIA_RPC_URL points at mainnet or a
    different testnet — would cause silent UserOp hash mismatches otherwise
    since CHAIN_ID is baked into the hash the contract validates.
    """
    actual = w3.eth.chain_id
    if actual != CHAIN_ID:
        print(f"[ERROR] RPC chain ID mismatch.")
        print(f"        Expected : {CHAIN_ID} (Base Sepolia)")
        print(f"        Got      : {actual}")
        print(f"        Check BASE_SEPOLIA_RPC_URL in your .env — wrong network.")
        sys.exit(1)
    print(f"      [OK] Chain ID confirmed: {actual} (Base Sepolia)")

# ─── Bundler RPC helpers ──────────────────────────────────────────────────────

def bundler_rpc(method: str, params: list) -> dict:
    """
    Send a JSON-RPC request to the Pimlico bundler with retry logic.
    Retries up to RPC_MAX_RETRIES times on network/HTTP errors.
    Does NOT retry on bundler-level errors (invalid op, bad signature etc)
    since those are deterministic and retrying won't help.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    last_error = None
    for attempt in range(1, RPC_MAX_RETRIES + 1):
        try:
            resp = requests.post(PIMLICO_RPC_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Bundler-level errors are deterministic — don't retry these,
            # surface them immediately with the full error detail.
            if "error" in data:
                raise RuntimeError(
                    f"Bundler rejected request:\n"
                    f"  method : {method}\n"
                    f"  code   : {data['error'].get('code', 'unknown')}\n"
                    f"  message: {data['error'].get('message', str(data['error']))}"
                )

            return data["result"]

        except requests.exceptions.RequestException as e:
            # Network/HTTP error — worth retrying
            last_error = e
            if attempt < RPC_MAX_RETRIES:
                print(f"      [RETRY {attempt}/{RPC_MAX_RETRIES}] Network error: {e}")
                time.sleep(RPC_RETRY_DELAY)
            else:
                raise RuntimeError(
                    f"Bundler unreachable after {RPC_MAX_RETRIES} attempts: {e}\n"
                    f"Check PIMLICO_RPC_URL and your internet connection."
                ) from e

# ─── UserOperation builder ────────────────────────────────────────────────────

def build_user_op(sender: str, nonce: int, call_data: bytes) -> dict:
    """
    Construct a UserOperation struct as a dict with hex-encoded fields.
    This layout matches ERC-4337 v0.7 schema.
    All numeric fields are hex strings — that's what bundlers and the
    EntryPoint ABI expect on the wire.
    """
    return {
        "sender":                      sender,
        "nonce":                       hex(nonce),
        "factory":                     "0x",
        "factoryData":                 "0x",
        "callData":                    call_data.hex() if isinstance(call_data, bytes) else call_data,
        "callGasLimit":                "0x5000",
        "verificationGasLimit":        "0x10000",
        "preVerificationGas":          "0xC350",
        "maxFeePerGas":                hex(Web3.to_wei(0.1, "gwei")),
        "maxPriorityFeePerGas":        hex(Web3.to_wei(0.1, "gwei")),
        "paymaster":                   "0x",
        "paymasterVerificationGasLimit": "0x",
        "paymasterPostOpGasLimit":      "0x",
        "paymasterData":               "0x",
        "signature":                   "0x",
    }

def hash_user_op(op: dict) -> bytes:
    """
    Compute the userOpHash exactly how the EntryPoint v0.7 contract does on-chain.
    """
    from eth_abi import encode

    # 1. Pack and hash factory fields
    factory_bytes = b""
    if op["factory"] not in ["0x", "0x0000000000000000000000000000000000000000", Web3.to_checksum_address("0x0000000000000000000000000000000000000000")]:
        factory_bytes = bytes.fromhex(op["factory"].lstrip("0x")) + bytes.fromhex(op["factoryData"].lstrip("0x"))
    hashed_factory = Web3.keccak(factory_bytes)

    # 2. Hash callData
    call_data_bytes = bytes.fromhex(op["callData"].lstrip("0x") or "")
    hashed_call_data = Web3.keccak(call_data_bytes)

    # 3. Pack and hash paymaster fields
    paymaster_bytes = b""
    if op["paymaster"] not in ["0x", "0x0000000000000000000000000000000000000000", Web3.to_checksum_address("0x0000000000000000000000000000000000000000")]:
        paymaster_bytes = (
            bytes.fromhex(op["paymaster"].lstrip("0x")) +
            int(op["paymasterVerificationGasLimit"], 16).to_bytes(16, 'big') +
            int(op["paymasterPostOpGasLimit"], 16).to_bytes(16, 'big') +
            bytes.fromhex(op["paymasterData"].lstrip("0x"))
        )
    hashed_paymaster = Web3.keccak(paymaster_bytes)

    # 4. Compute inner hash matching EntryPoint v0.7 abi.encode structure
    inner = Web3.keccak(encode(
        [
            'address',  # sender
            'uint256',  # nonce
            'bytes32',  # keccak256(factoryPacked)
            'bytes32',  # keccak256(callData)
            'uint256',  # callGasLimit
            'uint256',  # verificationGasLimit
            'uint256',  # preVerificationGas
            'uint256',  # maxFeePerGas
            'uint256',  # maxPriorityFeePerGas
            'bytes32'   # keccak256(paymasterPacked)
        ],
        [
            Web3.to_checksum_address(op["sender"]),
            int(op["nonce"], 16),
            hashed_factory,
            hashed_call_data,
            int(op["callGasLimit"], 16),
            int(op["verificationGasLimit"], 16),
            int(op["preVerificationGas"], 16),
            int(op["maxFeePerGas"], 16),
            int(op["maxPriorityFeePerGas"], 16),
            hashed_paymaster
        ]
    ))

    # 5. Combine inner hash with EntryPoint address and Chain ID
    user_op_hash = Web3.keccak(encode(
        ['bytes32', 'address', 'uint256'],
        [inner, Web3.to_checksum_address(ENTRY_POINT), CHAIN_ID]
    ))

    return user_op_hash

def sign_user_op(op: dict, private_key: str) -> dict:
    """
    Sign the userOpHash with the eth_sign prefix, matching what
    SoulAccount.validateUserOp does on-chain:
      bytes32 ethSignedMessageHash = userOpHash.toEthSignedMessageHash();
      address signer = ethSignedMessageHash.recover(userOp.signature);
    """
    user_op_hash = hash_user_op(op)
    signable = encode_defunct(primitive=user_op_hash)
    signed = Account.sign_message(signable, private_key=private_key)
    op = dict(op)
    op["signature"] = "0x" + signed.signature.hex()
    return op

# ─── On-chain state reads ─────────────────────────────────────────────────────

SOUL_ACCOUNT_ABI = [
    {
        "name": "activeEnclaveKey",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
    {
        "name": "enclaveKeyExpiration",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}],
    },
    {
        "name": "usedNonces",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"type": "uint256"}],
        "outputs": [{"type": "bool"}],
    },
]

def read_soul_state(w3: Web3, soul_addr: str) -> dict:
    soul = w3.eth.contract(
        address=Web3.to_checksum_address(soul_addr),
        abi=SOUL_ACCOUNT_ABI
    )
    active_key = soul.functions.activeEnclaveKey().call()
    expiration = soul.functions.enclaveKeyExpiration().call()
    return {"activeEnclaveKey": active_key, "enclaveKeyExpiration": expiration}

def find_unused_nonce(w3: Web3, soul_addr: str, start: int = 0) -> int:
    soul = w3.eth.contract(
        address=Web3.to_checksum_address(soul_addr),
        abi=SOUL_ACCOUNT_ABI
    )
    nonce = start
    while soul.functions.usedNonces(nonce).call():
        nonce += 1
    return nonce

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    check_env()
    
    if not PRIVATE_KEY:
        print("[ERROR] THROWAWAY_PRIVATE_KEY not set in .env")
        sys.exit(1)

    account = Account.from_key(PRIVATE_KEY)
    print(f"\n[1/7] Throwaway EOA address: {account.address}")

    w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))
    if not w3.is_connected():
        print("[ERROR] Cannot connect to Base Sepolia RPC")
        sys.exit(1)

    # ── Chain ID check — catches wrong network before anything else ────────
    print(f"[2/7] Validating RPC chain ID...")
    validate_chain(w3)

    # ── Read soul state ────────────────────────────────────────────────────
    print(f"[3/7] Reading SoulAccount state at {SOUL_ACCOUNT_ADDR}...")
    state = read_soul_state(w3, SOUL_ACCOUNT_ADDR)
    print(f"      activeEnclaveKey : {state['activeEnclaveKey']}")
    print(f"      expiration       : {state['enclaveKeyExpiration']}")

    if state["activeEnclaveKey"].lower() != account.address.lower():
        print(
            f"\n[ERROR] activeEnclaveKey on-chain is {state['activeEnclaveKey']}\n"
            f"        but your throwaway key is     {account.address}\n\n"
            f"        Run: python register_throwaway_key.py"
        )
        sys.exit(1)

    if state["enclaveKeyExpiration"] < int(time.time()):
        print("[ERROR] enclaveKey is expired. Run register_throwaway_key.py again.")
        sys.exit(1)

    print("      [OK] Key matches and is not expired.")

    # ── Find a fresh nonce ─────────────────────────────────────────────────
    nonce = find_unused_nonce(w3, SOUL_ACCOUNT_ADDR)
    print(f"[4/7] Using nonce: {nonce}")

    # ── Build the op ───────────────────────────────────────────────────────
    from eth_abi import encode
    
    # Encode a call to execute(address,uint256,bytes) - a no-op self-call
    # Selector for execute is bytes4(keccak256("execute(address,uint256,bytes)")) -> 0xb61d27f6
    EXECUTE_SELECTOR = bytes.fromhex("b61d27f6")
    
    encoded_params = encode(
        ['address', 'uint256', 'bytes'],
        [Web3.to_checksum_address(SOUL_ACCOUNT_ADDR), 0, b""]
    )
    
    call_data = EXECUTE_SELECTOR + encoded_params
    
    op = build_user_op(
        sender=Web3.to_checksum_address(SOUL_ACCOUNT_ADDR),
        nonce=nonce,
        call_data=call_data,
    )
    print(f"[5/7] UserOperation built.")
    print(f"      sender : {op['sender']}")
    print(f"      nonce  : {op['nonce']}")

    # ── Sign ───────────────────────────────────────────────────────────────
    # Debug: print the hash we're signing
    user_op_hash = hash_user_op(op)
    print(f"[DEBUG] userOpHash: {user_op_hash.hex()}")
    signable = encode_defunct(primitive=user_op_hash)
    print(f"[DEBUG] ethSignedMessageHash: {signable.header.hex()}{signable.body.hex()}")
    
    op = sign_user_op(op, PRIVATE_KEY)
    print(f"[6/7] Signed. Signature: {op['signature'][:20]}...")
    
    # Debug: verify signature recovery locally
    signable_msg = encode_defunct(primitive=user_op_hash)
    recovered_address = Account.recover_message(signable_msg, signature=op['signature'])
    print(f"[DEBUG] Recovered address: {recovered_address}")
    print(f"[DEBUG] Expected address: {account.address}")
    print(f"[DEBUG] Match: {recovered_address.lower() == account.address.lower()}")

    # ── Skip gas estimation - using hardcoded values ───────────────────────
    print(f"[7/7] Using hardcoded gas values (estimation skipped to avoid re-sign issues)")

    # ── Submit to bundler ──────────────────────────────────────────────────
    print(f"\n      Submitting UserOperation...")
    try:
        # Create a clean payload copy for the wire that strips empty v0.7 structural keys
        wire_op = dict(op)
        keys_to_omit = [
            "factory", "factoryData", 
            "paymaster", "paymasterVerificationGasLimit", 
            "paymasterPostOpGasLimit", "paymasterData"
        ]
        for key in keys_to_omit:
            if wire_op.get(key) in ["0x", "", "0x0000000000000000000000000000000000000000"]:
                wire_op.pop(key, None)

        op_hash = bundler_rpc("eth_sendUserOperation", [wire_op, ENTRY_POINT])
        print(f"      UserOpHash: {op_hash}")
    except RuntimeError as e:
        print(f"\n[FAIL] Bundler rejected the operation:\n       {e}")
        print("\n       Common causes:")
        print("       - activeEnclaveKey doesn't match your throwaway key")
        print("       - Signature hash mismatch (CHAIN_ID must be 84532)")
        print("       - SoulAccount has no ETH for gas — fund the proxy address")
        sys.exit(1)

    # ── Poll for receipt ───────────────────────────────────────────────────
    print("\n      Polling for on-chain confirmation (up to 3 minutes)...")
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            receipt = bundler_rpc("eth_getUserOperationReceipt", [op_hash])
            if receipt and receipt.get("success"):
                tx_hash = receipt.get("receipt", {}).get("transactionHash", "unknown")
                print(f"\n{'='*60}")
                print(f"  PASS — UserOperation landed on-chain.")
                print(f"  Tx hash : {tx_hash}")
                print(f"  Basescan: https://sepolia.basescan.org/tx/{tx_hash}")
                print(f"{'='*60}\n")
                print("Phase 1 complete. validateUserOp works in the wild.")
                print("Next: Phase 2 — swap this throwaway key for a real TEE-attested one.")
                return
            elif receipt and not receipt.get("success"):
                print(f"\n[FAIL] Op landed but reverted on-chain.")
                print(f"       Receipt: {json.dumps(receipt, indent=2)}")
                sys.exit(1)
        except RuntimeError:
            pass  # receipt not ready yet, keep polling
        print("      ...", end="\r")
        time.sleep(5)

    print("[TIMEOUT] Op not confirmed within 3 minutes. Check Pimlico dashboard.")
    print(f"          UserOpHash: {op_hash}")
    sys.exit(1)


if __name__ == "__main__":
    main()
