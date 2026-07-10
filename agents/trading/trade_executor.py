"""
SAI Protocol — Trade Executor
-----------------------------
Trade execution for Polymarket CLOB trades.

Provides:
  - UserOperation building
  - Bundler submission
  - Retry logic with exponential backoff
  - Dry run support
"""

import logging
import time
import json
import requests
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from web3 import Web3

from .trade_encoder import EncodedTrade, UserOperationEncoder

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """Enumeration of execution statuses."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class ExecutionResult:
    """Result of a trade execution."""
    status: ExecutionStatus
    user_op_hash: Optional[str]
    transaction_hash: Optional[str]
    timestamp: float
    error: Optional[str] = None
    retry_count: int = 0
    additional_data: Dict[str, Any] = field(default_factory=dict)


class TradeExecutor:
    """
    Executor for Polymarket CLOB trades.
    
    Handles UserOperation building, bundler submission,
    and retry logic with exponential backoff.
    """
    
    def __init__(
        self,
        bundler_url: str,
        user_op_encoder: UserOperationEncoder,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize trade executor.
        
        Args:
            bundler_url: Bundler RPC URL
            user_op_encoder: UserOperation encoder
            config: Configuration dictionary
                - max_retries: Maximum retry attempts (default: 3)
                - initial_backoff: Initial backoff in seconds (default: 1)
                - backoff_multiplier: Backoff multiplier (default: 2)
                - dry_run: Dry run mode (default: false)
        """
        self.bundler_url = bundler_url
        self.user_op_encoder = user_op_encoder
        self.config = config or {}
        
        self.max_retries = self.config.get("max_retries", 3)
        self.initial_backoff = self.config.get("initial_backoff", 1)
        self.backoff_multiplier = self.config.get("backoff_multiplier", 2)
        self.dry_run = self.config.get("dry_run", False)
        
        logger.info(
            f"TradeExecutor initialized: bundler={bundler_url}, "
            f"max_retries={self.max_retries}, dry_run={self.dry_run}"
        )
    
    def execute_trade(
        self,
        encoded_trade: EncodedTrade,
        sender: str,
        nonce: int,
        signature: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute a trade via UserOperation.
        
        Args:
            encoded_trade: Encoded trade
            sender: Sender address
            nonce: Account nonce
            signature: Optional signature for UserOperation
            
        Returns:
            ExecutionResult object
        """
        logger.info(
            f"Executing trade: sender={sender}, nonce={nonce}, "
            f"target={encoded_trade.target_address}"
        )
        
        # Build UserOperation
        user_op = self.user_op_encoder.encode_user_operation(
            encoded_trade,
            sender,
            nonce
        )
        
        # Add signature if provided
        if signature:
            user_op["signature"] = signature
        
        # Submit to bundler
        result = self._submit_to_bundler(user_op)
        
        return result
    
    def execute_batch_trades(
        self,
        encoded_trades: List[EncodedTrade],
        sender: str,
        nonce: int,
        signature: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute a batch of trades via single UserOperation.
        
        Args:
            encoded_trades: List of encoded trades
            sender: Sender address
            nonce: Account nonce
            signature: Optional signature for UserOperation
            
        Returns:
            ExecutionResult object
        """
        logger.info(
            f"Executing batch trades: {len(encoded_trades)} trades, "
            f"sender={sender}, nonce={nonce}"
        )
        
        # Build batch UserOperation
        user_op = self.user_op_encoder.encode_batch_user_operations(
            encoded_trades,
            sender,
            nonce
        )
        
        # Add signature if provided
        if signature:
            user_op["signature"] = signature
        
        # Submit to bundler
        result = self._submit_to_bundler(user_op)
        
        return result
    
    def _submit_to_bundler(
        self,
        user_op: Dict[str, Any],
        retry_count: int = 0
    ) -> ExecutionResult:
        """
        Submit UserOperation to bundler with retry logic.
        
        Args:
            user_op: UserOperation dictionary
            retry_count: Current retry attempt
            
        Returns:
            ExecutionResult object
        """
        if self.dry_run:
            return self._dry_run_submit(user_op)
        
        logger.info(
            f"Submitting UserOperation to bundler (attempt {retry_count + 1}/{self.max_retries})"
        )
        
        try:
            # Prepare JSON-RPC request
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_sendUserOperation",
                "params": [user_op, self.user_op_encoder.entry_point]
            }
            
            # Submit to bundler
            response = requests.post(
                self.bundler_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            # Check for errors
            if "error" in result:
                error_msg = result["error"].get("message", "Unknown error")
                logger.error(f"Bundler returned error: {error_msg}")
                
                # Retry on certain errors
                if self._should_retry(error_msg) and retry_count < self.max_retries:
                    backoff = self._calculate_backoff(retry_count)
                    logger.info(f"Retrying in {backoff}s...")
                    time.sleep(backoff)
                    return self._submit_to_bundler(user_op, retry_count + 1)
                
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    user_op_hash=None,
                    transaction_hash=None,
                    timestamp=time.time(),
                    error=error_msg,
                    retry_count=retry_count
                )
            
            # Success
            user_op_hash = result.get("result")
            logger.info(f"UserOperation submitted: {user_op_hash}")
            
            return ExecutionResult(
                status=ExecutionStatus.SUBMITTED,
                user_op_hash=user_op_hash,
                transaction_hash=None,
                timestamp=time.time(),
                retry_count=retry_count,
                additional_data={"bundler_response": result}
            )
            
        except requests.exceptions.Timeout:
            logger.error("Bundler request timed out")
            
            if retry_count < self.max_retries:
                backoff = self._calculate_backoff(retry_count)
                logger.info(f"Retrying in {backoff}s...")
                time.sleep(backoff)
                return self._submit_to_bundler(user_op, retry_count + 1)
            
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                user_op_hash=None,
                transaction_hash=None,
                timestamp=time.time(),
                error="Request timeout",
                retry_count=retry_count
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Bundler request failed: {e}")
            
            if retry_count < self.max_retries:
                backoff = self._calculate_backoff(retry_count)
                logger.info(f"Retrying in {backoff}s...")
                time.sleep(backoff)
                return self._submit_to_bundler(user_op, retry_count + 1)
            
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                user_op_hash=None,
                transaction_hash=None,
                timestamp=time.time(),
                error=str(e),
                retry_count=retry_count
            )
            
        except Exception as e:
            logger.error(f"Unexpected error during submission: {e}", exc_info=True)
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                user_op_hash=None,
                transaction_hash=None,
                timestamp=time.time(),
                error=str(e),
                retry_count=retry_count
            )
    
    def _dry_run_submit(self, user_op: Dict[str, Any]) -> ExecutionResult:
        """
        Simulate bundler submission in dry run mode.
        
        Args:
            user_op: UserOperation dictionary
            
        Returns:
            ExecutionResult object
        """
        logger.info("DRY RUN: Simulating UserOperation submission")
        
        # Generate mock user op hash
        user_op_hash = "0x" + "00" * 32
        
        logger.info(f"DRY RUN: UserOperation would be submitted: {user_op_hash}")
        
        # Log the UserOperation for inspection
        logger.info(f"DRY RUN: UserOperation details: {json.dumps(user_op, indent=2)}")
        
        return ExecutionResult(
            status=ExecutionStatus.SUBMITTED,
            user_op_hash=user_op_hash,
            transaction_hash=None,
            timestamp=time.time(),
            retry_count=0,
            additional_data={"dry_run": True, "user_op": user_op}
        )
    
    def _should_retry(self, error_msg: str) -> bool:
        """
        Determine if an error should trigger a retry.
        
        Args:
            error_msg: Error message
            
        Returns:
            True if should retry, False otherwise
        """
        # Retry on transient errors
        retryable_errors = [
            "timeout",
            "network",
            "temporarily",
            "rate limit",
            "too many requests"
        ]
        
        error_msg_lower = error_msg.lower()
        return any(err in error_msg_lower for err in retryable_errors)
    
    def _calculate_backoff(self, retry_count: int) -> float:
        """
        Calculate exponential backoff delay.
        
        Args:
            retry_count: Current retry attempt
            
        Returns:
            Backoff delay in seconds
        """
        return self.initial_backoff * (self.backoff_multiplier ** retry_count)
    
    def estimate_gas_cost(
        self,
        encoded_trade: EncodedTrade,
        gas_price: float
    ) -> float:
        """
        Estimate gas cost for a trade.
        
        Args:
            encoded_trade: Encoded trade
            gas_price: Gas price in gwei
            
        Returns:
            Estimated gas cost in ETH
        """
        gas_limit = encoded_trade.gas_limit
        gas_cost_wei = gas_limit * int(gas_price * 1e9)
        gas_cost_eth = gas_cost_wei / 1e18
        
        return gas_cost_eth
    
    def simulate_execution(
        self,
        encoded_trade: EncodedTrade,
        sender: str,
        nonce: int
    ) -> Dict[str, Any]:
        """
        Simulate trade execution without submitting.
        
        Args:
            encoded_trade: Encoded trade
            sender: Sender address
            nonce: Account nonce
            
        Returns:
            Simulation results
        """
        logger.info("Simulating trade execution")
        
        # Build UserOperation
        user_op = self.user_op_encoder.encode_user_operation(
            encoded_trade,
            sender,
            nonce
        )
        
        # Return simulation details
        return {
            "user_operation": user_op,
            "gas_limit": encoded_trade.gas_limit,
            "target_address": encoded_trade.target_address,
            "calldata_length": len(encoded_trade.calldata),
            "timestamp": time.time()
        }


class BundlerClient:
    """
    Client for interacting with ERC-4337 bundlers.
    
    Provides methods for UserOperation submission and status checking.
    """
    
    def __init__(self, bundler_url: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize bundler client.
        
        Args:
            bundler_url: Bundler RPC URL
            config: Configuration dictionary
                - timeout: Request timeout in seconds (default: 30)
        """
        self.bundler_url = bundler_url
        self.config = config or {}
        self.timeout = self.config.get("timeout", 30)
        
        logger.info(f"BundlerClient initialized: {bundler_url}")
    
    def get_user_operation_status(self, user_op_hash: str) -> Dict[str, Any]:
        """
        Get status of a submitted UserOperation.
        
        Args:
            user_op_hash: UserOperation hash
            
        Returns:
            Status information
        """
        logger.info(f"Checking UserOperation status: {user_op_hash}")
        
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getUserOperationByHash",
                "params": [user_op_hash]
            }
            
            response = requests.post(
                self.bundler_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            if "error" in result:
                logger.error(f"Error getting status: {result['error']}")
                return {"status": "error", "error": result["error"]}
            
            user_op_result = result.get("result", {})
            
            return {
                "status": "success",
                "user_operation": user_op_result,
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"Failed to get UserOperation status: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    def get_user_operation_receipt(self, user_op_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get receipt for a UserOperation.
        
        Args:
            user_op_hash: UserOperation hash
            
        Returns:
            Receipt information or None if not found
        """
        logger.info(f"Getting UserOperation receipt: {user_op_hash}")
        
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getUserOperationReceipt",
                "params": [user_op_hash]
            }
            
            response = requests.post(
                self.bundler_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            if "error" in result:
                logger.error(f"Error getting receipt: {result['error']}")
                return None
            
            receipt = result.get("result")
            
            if receipt:
                logger.info(f"Receipt found: {receipt.get('transactionHash')}")
            
            return receipt
            
        except Exception as e:
            logger.error(f"Failed to get UserOperation receipt: {e}", exc_info=True)
            return None
    
    def get_supported_entry_points(self) -> List[str]:
        """
        Get list of supported EntryPoint contracts.
        
        Returns:
            List of EntryPoint addresses
        """
        logger.info("Getting supported entry points")
        
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_supportedEntryPoints",
                "params": []
            }
            
            response = requests.post(
                self.bundler_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            if "error" in result:
                logger.error(f"Error getting entry points: {result['error']}")
                return []
            
            entry_points = result.get("result", [])
            
            logger.info(f"Supported entry points: {entry_points}")
            
            return entry_points
            
        except Exception as e:
            logger.error(f"Failed to get supported entry points: {e}", exc_info=True)
            return []
