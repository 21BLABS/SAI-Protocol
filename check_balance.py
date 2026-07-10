from web3 import Web3
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv('.env')

w3 = Web3(Web3.HTTPProvider(os.getenv('BASE_SEPOLIA_RPC_URL')))
soul_addr = os.getenv('SOUL_ACCOUNT_ADDRESS')
balance = w3.eth.get_balance(soul_addr)
print(f'SoulAccount ({soul_addr}) balance: {w3.from_wei(balance, "ether")} ETH')
print(f'Wei balance: {balance}')
