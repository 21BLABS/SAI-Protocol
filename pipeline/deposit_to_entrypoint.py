"""
Deposit ETH to EntryPoint for SoulAccount gas payments
This is required for ERC-4337 v0.6 accounts
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env", override=True)

sys.path.insert(0, str(project_root))
from config import CHAIN_ID, ENTRY_POINT

PRIVATE_KEY = os.getenv("THROWAWAY_PRIVATE_KEY")
SOUL_ACCOUNT_ADDR = os.getenv("SOUL_ACCOUNT_ADDRESS")
BASE_SEPOLIA_RPC = os.getenv("BASE_SEPOLIA_RPC_URL")

account = Account.from_key(PRIVATE_KEY)
w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))

# EntryPoint ABI for depositTo function
ENTRYPOINT_ABI = [
    {
        "name": "depositTo",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"type": "uint256"}],
    }
]

entrypoint = w3.eth.contract(
    address=Web3.to_checksum_address(ENTRY_POINT),
    abi=ENTRYPOINT_ABI
)

print(f"Depositing to EntryPoint for: {SOUL_ACCOUNT_ADDR}")
print(f"Deposit amount: 0.001 ETH")

# Check current balance
current_balance = entrypoint.functions.balanceOf(SOUL_ACCOUNT_ADDR).call()
print(f"Current deposit balance: {w3.from_wei(current_balance, 'ether')} ETH")

# Deposit 0.01 ETH
tx = entrypoint.functions.depositTo(
    Web3.to_checksum_address(SOUL_ACCOUNT_ADDR)
).build_transaction({
    "from": account.address,
    "value": Web3.to_wei(0.001, "ether"),
    "nonce": w3.eth.get_transaction_count(account.address),
    "gas": 200_000,
    "gasPrice": w3.eth.gas_price,
    "chainId": CHAIN_ID,
})

signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"\nTx submitted: {tx_hash.hex()}")
print("Waiting for confirmation...")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
if receipt["status"] == 1:
    new_balance = entrypoint.functions.balanceOf(SOUL_ACCOUNT_ADDR).call()
    print(f"\n[OK] Deposit confirmed.")
    print(f"     New deposit balance: {w3.from_wei(new_balance, 'ether')} ETH")
    print(f"     Basescan: https://sepolia.basescan.org/tx/{tx_hash.hex()}")
    print("\nNow run: python pipeline/phase1_eoa_pipeline.py")
else:
    print(f"\n[FAIL] Transaction reverted.")
    sys.exit(1)
