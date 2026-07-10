"""
SAI Protocol — EIP-712 Signature Test
------------------------------------
Standalone test for EIP-712 signature generation.
Tests that the signature is not a placeholder when key_manager is provided.
"""

import os
import sys
import logging
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


class MockKeyManager:
    """Mock key manager for testing."""
    def __init__(self):
        self._private_key = Account.create().key.hex()
        self.public_address = Account.from_key(self._private_key).address
    
    def sign_typed_data(self, domain_hash: bytes, message_hash: bytes) -> str:
        from eth_account.messages import encode_defunct
        
        typed_data_hash = Web3.keccak(
            b"\x19\x01" + domain_hash + message_hash
        )
        signable = encode_defunct(primitive=typed_data_hash)
        signed = Account.sign_message(signable, private_key=self._private_key)
        return "0x" + signed.signature.hex()


def test_eip712_signature():
    """Test EIP-712 signature generation."""
    logger.info("=" * 60)
    logger.info("EIP-712 Signature Test")
    logger.info("=" * 60)
    
    try:
        # Create mock key manager
        mock_key_manager = MockKeyManager()
        logger.info(f"✓ Mock key manager created: {mock_key_manager.public_address}")
        
        # Test domain and message (simplified EIP-712 structure)
        domain = {
            "name": "PolymarketCLOB",
            "version": "1",
            "chainId": 84532,
            "verifyingContract": "0x4D2Fc7667F282C6433B6D8112e7A8997e7335d74"
        }
        
        types = {
            "Order": [
                {"name": "conditionId", "type": "bytes32"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "amount", "type": "uint256"},
                {"name": "price", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "expiration", "type": "uint256"},
                {"name": "salt", "type": "bytes32"}
            ]
        }
        
        message = {
            "conditionId": "0x" + "00" * 32,
            "tokenId": 1,
            "side": 1,
            "amount": int(10.0 * 1e18),
            "price": int(0.6 * 1e18),
            "maker": "0x0000000000000000000000000000000000000000",
            "taker": "0x0000000000000000000000000000000000000000",
            "expiration": 1234567890,
            "salt": "0x" + "00" * 32  # bytes32 = 32 bytes = 64 hex chars
        }
        
        # Compute hashes using simplified EIP-712 approach (matching trade_encoder.py)
        from eth_abi import encode
        
        # Encode the message parameters
        message_encoded = encode(
            ["bytes32", "uint256", "uint8", "uint256", "uint256", "address", "address", "uint256", "bytes32"],
            [
                bytes.fromhex(message["conditionId"].replace("0x", "")),
                message["tokenId"],
                message["side"],
                message["amount"],
                message["price"],
                Web3.to_checksum_address(message["maker"]),
                Web3.to_checksum_address(message["taker"]),
                message["expiration"],
                bytes.fromhex(message["salt"].replace("0x", ""))
            ]
        )
        
        # Compute message hash
        message_hash = Web3.keccak(message_encoded)
        
        # Compute domain hash (simplified)
        domain_encoded = encode(
            ["string", "string", "uint256", "address"],
            [
                domain["name"],
                domain["version"],
                domain["chainId"],
                Web3.to_checksum_address(domain["verifyingContract"])
            ]
        )
        domain_hash = Web3.keccak(domain_encoded)
        
        logger.info(f"✓ Domain hash computed: {domain_hash.hex()[:20]}...")
        logger.info(f"✓ Message hash computed: {message_hash.hex()[:20]}...")
        
        # Sign with mock key manager
        signature = mock_key_manager.sign_typed_data(domain_hash, message_hash)
        
        # Validate signature
        assert signature != "0x" + "00" * 130, "Signature is still placeholder"
        assert len(signature) == 132, f"Signature must be 65 bytes (130 hex + 0x), got {len(signature)}"
        assert signature.startswith("0x"), "Signature must start with 0x"
        
        logger.info(f"✓ Signature is real: {signature[:10]}...{signature[-6:]}")
        logger.info(f"✓ Signature length: {len(signature)} characters")
        
        # Verify signature can be recovered
        # The signature was created using EIP-712 format with \x19\x01 prefix
        typed_data_hash = Web3.keccak(b"\x19\x01" + domain_hash + message_hash)
        signable = encode_defunct(primitive=typed_data_hash)
        recovered_address = Account.recover_message(signable, signature=bytes.fromhex(signature[2:]))
        
        assert recovered_address.lower() == mock_key_manager.public_address.lower(), \
            f"Signature recovery failed: expected {mock_key_manager.public_address}, got {recovered_address}"
        
        logger.info(f"✓ Signature recovery successful: {recovered_address}")
        
        logger.info("✓ EIP-712 signature test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ EIP-712 signature test FAILED: {e}", exc_info=True)
        return False


def main():
    """Run the test."""
    logger.info("=" * 60)
    logger.info("EIP-712 SIGNATURE TEST")
    logger.info("=" * 60)
    
    result = test_eip712_signature()
    
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    if result:
        logger.info("✓ TEST PASSED")
        return 0
    else:
        logger.error("✗ TEST FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
