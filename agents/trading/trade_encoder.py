"""
SAI Protocol — Trade Encoder
----------------------------
Trade encoding for Polymarket CLOB execution.

Provides:
  - YES/NO token trade encoding
  - Order book encoding
  - Signature encoding
  - ABI encoding for UserOperations
"""

import logging
import time
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    from eth_abi import encode
    from eth_utils import to_checksum_address, keccak
    from web3 import Web3
    ETH_ABI_AVAILABLE = True
except ImportError:
    ETH_ABI_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("eth_abi or eth_utils not available - trade encoding will be limited")

logger = logging.getLogger(__name__)


class TokenType(Enum):
    """Enumeration of token types."""
    YES = "yes"
    NO = "no"


class OrderSide(Enum):
    """Enumeration of order sides."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class TradeParams:
    """Parameters for a trade."""
    condition_id: str  # Polymarket condition ID
    token_id: str  # Token ID (YES or NO)
    side: OrderSide  # Buy or sell
    amount: float  # Amount in tokens
    price: float  # Price per token (0-1 for binary options)
    maker: str  # Maker address
    taker: str  # Taker address
    expiration: int  # Expiration timestamp
    salt: str  # Salt for uniqueness
    signature: Optional[str] = None  # EIP-712 signature


@dataclass
class EncodedTrade:
    """Encoded trade data."""
    calldata: bytes  # ABI-encoded calldata
    target_address: str  # Target contract address
    value: int  # ETH value to send
    gas_limit: int  # Gas limit
    trade_params: TradeParams
    timestamp: float


class PolymarketTradeEncoder:
    """
    Encoder for Polymarket CLOB trades.
    
    Encodes trades for YES/NO tokens on the Polymarket CLOB,
    including EIP-712 signature generation and ABI encoding.
    """
    
    # Polymarket CLOB contract addresses (Base Sepolia)
    CLOB_CONTRACT = "0x4D2Fc7667F282C6433B6D8112e7A8997e7335d74"  # Example address
    ERC20_ABI = [
        {
            "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        },
        {
            "inputs": [{"name": "account", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        }
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, key_manager=None):
        """
        Initialize trade encoder.
        
        Args:
            config: Configuration dictionary
                - clob_contract: CLOB contract address
                - chain_id: Chain ID (default: 84532 for Base Sepolia)
            key_manager: EnclaveKeyManager instance for signing trades
        """
        self.config = config or {}
        self.clob_contract = self.config.get(
            "clob_contract",
            self.CLOB_CONTRACT
        )
        self.chain_id = self.config.get("chain_id", 84532)  # Base Sepolia
        self._key_manager = key_manager
        
        logger.info(
            f"PolymarketTradeEncoder initialized: "
            f"clob_contract={self.clob_contract}, chain_id={self.chain_id}"
        )
    
    def encode_trade(
        self,
        trade_params: TradeParams,
        w3: Web3
    ) -> EncodedTrade:
        """
        Encode a trade for execution.
        
        Args:
            trade_params: Trade parameters
            w3: Web3 instance
            
        Returns:
            EncodedTrade object
        """
        logger.info(
            f"Encoding trade: {trade_params.side.value} {trade_params.amount} "
            f"{trade_params.token_id} @ {trade_params.price}"
        )
        
        # Generate signature if not provided
        if not trade_params.signature:
            trade_params.signature = self._generate_signature(trade_params, w3)
        
        # Encode the trade calldata
        calldata = self._encode_trade_calldata(trade_params)
        
        # Calculate gas limit
        gas_limit = self._estimate_gas_limit(trade_params)
        
        encoded_trade = EncodedTrade(
            calldata=calldata,
            target_address=self.clob_contract,
            value=0,  # No ETH value for token trades
            gas_limit=gas_limit,
            trade_params=trade_params,
            timestamp=time.time()
        )
        
        logger.info(
            f"Trade encoded: target={encoded_trade.target_address}, "
            f"gas_limit={gas_limit}"
        )
        
        return encoded_trade
    
    def _encode_trade_calldata(self, trade_params: TradeParams) -> bytes:
        """
        Encode trade calldata for the CLOB contract.
        
        Args:
            trade_params: Trade parameters
            
        Returns:
            ABI-encoded calldata
        """
        # This is a simplified encoding for the Polymarket CLOB
        # In production, this would use the actual CLOB contract ABI
        
        # Encode the order parameters
        # Format: (condition_id, token_id, side, amount, price, maker, taker, expiration, salt)
        
        # Convert parameters to appropriate types
        condition_id_bytes = bytes.fromhex(trade_params.condition_id.replace("0x", ""))
        token_id_int = int(trade_params.token_id)
        side_int = 1 if trade_params.side == OrderSide.BUY else 2
        amount_int = int(trade_params.amount * 1e18)  # Convert to wei
        price_int = int(trade_params.price * 1e18)  # Convert to wei
        maker_address = to_checksum_address(trade_params.maker)
        taker_address = to_checksum_address(trade_params.taker)
        expiration_int = trade_params.expiration
        salt_bytes = bytes.fromhex(trade_params.salt.replace("0x", ""))
        
        # Encode using eth_abi
        try:
            calldata = encode(
                [
                    "(bytes32,uint256,uint8,uint256,uint256,address,address,uint256,bytes32)"
                ],
                [[
                    condition_id_bytes,
                    token_id_int,
                    side_int,
                    amount_int,
                    price_int,
                    maker_address,
                    taker_address,
                    expiration_int,
                    salt_bytes
                ]]
            )
            
            # Add function selector (simplified)
            function_selector = keccak(text="executeOrder(bytes32,uint256,uint8,uint256,uint256,address,address,uint256,bytes32)")[:4]
            calldata = function_selector + calldata
            
            return calldata
            
        except Exception as e:
            logger.error(f"Failed to encode trade calldata: {e}", exc_info=True)
            raise
    
    def _generate_signature(
        self,
        trade_params: TradeParams,
        w3: Web3
    ) -> str:
        """
        Generate EIP-712 signature for the trade.
        
        Args:
            trade_params: Trade parameters
            w3: Web3 instance
            
        Returns:
            Signature string
        """
        logger.info("Generating EIP-712 signature for trade")
        
        # EIP-712 domain separator
        domain = {
            "name": "PolymarketCLOB",
            "version": "1",
            "chainId": self.chain_id,
            "verifyingContract": self.clob_contract
        }
        
        # EIP-712 message types
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
        
        # Message value
        message = {
            "conditionId": trade_params.condition_id,
            "tokenId": int(trade_params.token_id),
            "side": 1 if trade_params.side == OrderSide.BUY else 2,
            "amount": int(trade_params.amount * 1e18),
            "price": int(trade_params.price * 1e18),
            "maker": to_checksum_address(trade_params.maker),
            "taker": to_checksum_address(trade_params.taker),
            "expiration": trade_params.expiration,
            "salt": trade_params.salt
        }
        
        # Note: This prepares the EIP-712 structured data
        # The actual signing should be done by the enclave key manager
        # This method returns the structured data hash for signing
        
        try:
            # Encode the EIP-712 data
            # In production, this would be passed to key_manager.sign_typed_data
            # For now, we return a placeholder with the correct structure
            
            from eth_abi import encode
            from web3 import Web3
            
            # Check if key_manager is available
            if self._key_manager is None:
                logger.warning(
                    "EIP-712 structured data prepared. "
                    "No key_manager provided - returning placeholder signature."
                )
                # Return placeholder signature (65 bytes = 130 hex chars)
                signature = "0x" + "00" * 130
                return signature
            
            # Simplified EIP-712 approach: compute a hash of the trade parameters
            # This is a placeholder for proper EIP-712 encoding
            # In production, this should use the full EIP-712 structured data
            
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
            
            # Sign with enclave key manager
            signature = self._key_manager.sign_typed_data(domain_hash, message_hash)
            
            logger.info("EIP-712 signature generated successfully")
            return signature
            
        except Exception as e:
            logger.error(f"Failed to generate EIP-712 signature: {e}", exc_info=True)
            raise
    
    def _estimate_gas_limit(self, trade_params: TradeParams) -> int:
        """
        Estimate gas limit for the trade.
        
        Args:
            trade_params: Trade parameters
            
        Returns:
            Estimated gas limit
        """
        # Base gas for CLOB trade
        base_gas = 100000
        
        # Additional gas for token transfers
        additional_gas = 50000
        
        # Total gas estimate
        gas_limit = base_gas + additional_gas
        
        # Add buffer
        gas_limit = int(gas_limit * 1.2)
        
        return gas_limit
    
    def encode_order_book_quote(
        self,
        condition_id: str,
        token_id: str,
        side: OrderSide,
        amount: float,
        order_book: Dict[str, Any]
    ) -> EncodedTrade:
        """
        Encode a trade based on order book quote.
        
        Args:
            condition_id: Condition ID
            token_id: Token ID
            side: Order side
            amount: Amount to trade
            order_book: Order book data
            
        Returns:
            EncodedTrade object
        """
        # Get best price from order book
        if side == OrderSide.BUY:
            orders = order_book.get("asks", [])
            if not orders:
                raise ValueError("No asks available for buy order")
            best_price = orders[0][0]  # Best ask price
        else:
            orders = order_book.get("bids", [])
            if not orders:
                raise ValueError("No bids available for sell order")
            best_price = orders[0][0]  # Best bid price
        
        # Create trade parameters
        trade_params = TradeParams(
            condition_id=condition_id,
            token_id=token_id,
            side=side,
            amount=amount,
            price=best_price,
            maker="0x0000000000000000000000000000000000000000",  # Taker order
            taker="0x0000000000000000000000000000000000000000",
            expiration=int(time.time()) + 3600,  # 1 hour expiration
            salt="0x" + "00" * 64  # Random salt
        )
        
        logger.info(
            f"Order book quote: {side.value} {amount} @ {best_price}"
        )
        
        # Encode the trade (signature will be generated later)
        return EncodedTrade(
            calldata=b"",  # Will be filled when signature is available
            target_address=self.clob_contract,
            value=0,
            gas_limit=self._estimate_gas_limit(trade_params),
            trade_params=trade_params,
            timestamp=time.time()
        )
    
    def encode_token_approval(
        self,
        token_address: str,
        spender_address: str,
        amount: int
    ) -> EncodedTrade:
        """
        Encode a token approval transaction.
        
        Args:
            token_address: Token contract address
            spender_address: Spender address (CLOB contract)
            amount: Amount to approve (uint256 max for unlimited)
            
        Returns:
            EncodedTrade object
        """
        logger.info(
            f"Encoding token approval: token={token_address}, "
            f"spender={spender_address}, amount={amount}"
        )
        
        # Encode approve function call
        try:
            calldata = encode(
                ["address", "uint256"],
                [to_checksum_address(spender_address), amount]
            )
            
            # Add function selector for approve(address,uint256)
            function_selector = keccak(text="approve(address,uint256)")[:4]
            calldata = function_selector + calldata
            
            return EncodedTrade(
                calldata=calldata,
                target_address=to_checksum_address(token_address),
                value=0,
                gas_limit=50000,  # Standard approval gas
                trade_params=None,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error(f"Failed to encode token approval: {e}", exc_info=True)
            raise


class UserOperationEncoder:
    """
    Encoder for ERC-4337 UserOperations.
    
    Encodes trades as UserOperations for account abstraction.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize UserOperation encoder.
        
        Args:
            config: Configuration dictionary
                - entry_point: EntryPoint contract address
                - chain_id: Chain ID
        """
        self.config = config or {}
        self.entry_point = self.config.get(
            "entry_point",
            "0x5FF137D4b0FDCD49DcA30c7CF6E7283B40A5d85B"  # Standard EntryPoint v0.6
        )
        self.chain_id = self.config.get("chain_id", 84532)
        
        logger.info(
            f"UserOperationEncoder initialized: "
            f"entry_point={self.entry_point}, chain_id={self.chain_id}"
        )
    
    def encode_user_operation(
        self,
        encoded_trade: EncodedTrade,
        sender: str,
        nonce: int,
        call_data: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """
        Encode a UserOperation from an encoded trade.
        
        Args:
            encoded_trade: Encoded trade
            sender: Sender address (Soul Account)
            nonce: Account nonce
            call_data: Optional custom call data
            
        Returns:
            UserOperation dictionary
        """
        logger.info(
            f"Encoding UserOperation: sender={sender}, nonce={nonce}"
        )
        
        # Use provided call data or trade calldata
        if call_data:
            final_call_data = call_data
        elif encoded_trade:
            final_call_data = encoded_trade.calldata
        else:
            final_call_data = b""
        
        # Build UserOperation
        gas_limit = str(encoded_trade.gas_limit) if encoded_trade else str(100000)
        
        user_op = {
            "sender": to_checksum_address(sender),
            "nonce": nonce,
            "initCode": b"",  # No init code for existing account
            "callData": final_call_data.hex() if isinstance(final_call_data, bytes) else final_call_data,
            "callGasLimit": gas_limit,
            "verificationGasLimit": str(100000),  # Standard verification gas
            "preVerificationGas": str(50000),  # Standard pre-verification gas
            "maxFeePerGas": str(1000000000),  # 1 gwei
            "maxPriorityFeePerGas": str(1000000000),  # 1 gwei
            "paymasterAndData": "0x",  # No paymaster
            "signature": "0x" + "00" * 130  # Placeholder signature
        }
        
        logger.info(
            f"UserOperation encoded: callGasLimit={user_op['callGasLimit']}"
        )
        
        return user_op
    
    def encode_batch_user_operations(
        self,
        encoded_trades: List[EncodedTrade],
        sender: str,
        nonce: int
    ) -> Dict[str, Any]:
        """
        Encode a batch of trades as a single UserOperation.
        
        Args:
            encoded_trades: List of encoded trades
            sender: Sender address
            nonce: Account nonce
            
        Returns:
            UserOperation dictionary with batched call data
        """
        logger.info(
            f"Encoding batch UserOperation: {len(encoded_trades)} trades"
        )
        
        # Encode batch call data using multicall pattern
        call_data = self._encode_multicall(encoded_trades)
        
        # Calculate total gas limit
        total_gas = sum(trade.gas_limit for trade in encoded_trades)
        
        # Build UserOperation
        user_op = {
            "sender": to_checksum_address(sender),
            "nonce": nonce,
            "initCode": b"",
            "callData": call_data.hex() if isinstance(call_data, bytes) else call_data,
            "callGasLimit": str(total_gas),
            "verificationGasLimit": str(150000),  # Higher for batch
            "preVerificationGas": str(75000),
            "maxFeePerGas": str(1000000000),
            "maxPriorityFeePerGas": str(1000000000),
            "paymasterAndData": "0x",
            "signature": "0x" + "00" * 130
        }
        
        logger.info(
            f"Batch UserOperation encoded: total_gas={total_gas}"
        )
        
        return user_op
    
    def _encode_multicall(self, encoded_trades: List[EncodedTrade]) -> bytes:
        """
        Encode multiple trades using multicall pattern.
        
        Args:
            encoded_trades: List of encoded trades
            
        Returns:
            Multicall calldata
        """
        # This is a simplified multicall encoding
        # In production, this would use a proper multicall contract
        
        # For now, just concatenate the calldatas
        # This is not production-ready but demonstrates the concept
        
        concatenated = b""
        for trade in encoded_trades:
            concatenated += trade.calldata
        
        return concatenated
