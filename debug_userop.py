"""
Debug UserOperation to understand why prefund is failing
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
from eth_abi import encode

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env", override=True)

sys.path.insert(0, str(project_root))
from config import CHAIN_ID, ENTRY_POINT

PRIVATE_KEY = os.getenv("THROWAWAY_PRIVATE_KEY")
SOUL_ACCOUNT_ADDR = os.getenv("SOUL_ACCOUNT_ADDRESS")
BASE_SEPOLIA_RPC = os.getenv("BASE_SEPOLIA_RPC_URL")

account = Account.from_key(PRIVATE_KEY)
w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))

print(f"Throwaway EOA: {account.address}")
print(f"SoulAccount: {SOUL_ACCOUNT_ADDR}")
print(f"EntryPoint: {ENTRY_POINT}")

# Check SoulAccount balance
soul_balance = w3.eth.get_balance(SOUL_ACCOUNT_ADDR)
print(f"SoulAccount balance: {w3.from_wei(soul_balance, 'ether')} ETH")

# Check EntryPoint balance
entry_balance = w3.eth.get_balance(ENTRY_POINT)
print(f"EntryPoint balance: {w3.from_wei(entry_balance, 'ether')} ETH")

# Build a minimal UserOp
EXECUTE_SELECTOR = bytes.fromhex("b61d27f6")
encoded_params = encode(['address', 'uint256', 'bytes'], [Web3.to_checksum_address(SOUL_ACCOUNT_ADDR), 0, b""])
call_data = EXECUTE_SELECTOR + encoded_params

user_op = {
    "sender": SOUL_ACCOUNT_ADDR,
    "nonce": hex(0),
    "initCode": "0x",
    "callData": call_data.hex(),
    "callGasLimit": hex(200_000),
    "verificationGasLimit": hex(500_000),
    "preVerificationGas": hex(100_000),
    "maxFeePerGas": hex(Web3.to_wei(2, "gwei")),
    "maxPriorityFeePerGas": hex(Web3.to_wei(2, "gwei")),
    "paymasterAndData": "0x",
    "signature": "0x",
}

print(f"\nUserOperation:")
print(f"  sender: {user_op['sender']}")
print(f"  callGasLimit: {int(user_op['callGasLimit'], 16)}")
print(f"  verificationGasLimit: {int(user_op['verificationGasLimit'], 16)}")
print(f"  preVerificationGas: {int(user_op['preVerificationGas'], 16)}")

# Calculate estimated prefund
# prefund = (callGasLimit + verificationGasLimit) * maxFeePerGas
call_gas = int(user_op['callGasLimit'], 16)
ver_gas = int(user_op['verificationGasLimit'], 16)
prefund_gas = call_gas + ver_gas
max_fee = int(user_op['maxFeePerGas'], 16)
estimated_prefund = prefund_gas * max_fee

print(f"\nEstimated prefund: {w3.from_wei(estimated_prefund, 'ether')} ETH")
print(f"SoulAccount has enough: {soul_balance >= estimated_prefund}")
