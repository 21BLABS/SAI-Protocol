"""
SAI Protocol — Trade Monitor
----------------------------
Trade monitoring and confirmation for Polymarket CLOB trades.

Provides:
  - Transaction status tracking
  - Trade confirmation logic
  - Error handling and rollback
  - Position tracking
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from .trade_executor import ExecutionResult, ExecutionStatus, BundlerClient

logger = logging.getLogger(__name__)


class TradeStatus(Enum):
    """Enumeration of trade statuses."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ROLLED_BACK = "rolled_back"


@dataclass
class TradeRecord:
    """Record of a trade."""
    trade_id: str
    user_op_hash: Optional[str]
    transaction_hash: Optional[str]
    status: TradeStatus
    timestamp: float
    encoded_trade: Optional[Dict[str, Any]] = None
    execution_result: Optional[ExecutionResult] = None
    confirmation_timestamp: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    additional_data: Dict[str, Any] = field(default_factory=dict)


class TradeMonitor:
    """
    Monitor for tracking trade execution status.
    
    Tracks submitted trades, monitors confirmation status,
    and handles error recovery.
    """
    
    def __init__(
        self,
        bundler_client: BundlerClient,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize trade monitor.
        
        Args:
            bundler_client: Bundler client for status checks
            config: Configuration dictionary
                - confirmation_timeout: Timeout for confirmation in seconds (default: 300)
                - poll_interval: Polling interval in seconds (default: 5)
                - max_tracked_trades: Maximum trades to track (default: 100)
        """
        self.bundler_client = bundler_client
        self.config = config or {}
        
        self.confirmation_timeout = self.config.get("confirmation_timeout", 300)  # 5 minutes
        self.poll_interval = self.config.get("poll_interval", 5)  # 5 seconds
        self.max_tracked_trades = self.config.get("max_tracked_trades", 100)
        
        # Trade tracking
        self.trades: Dict[str, TradeRecord] = {}
        self.pending_trades: deque = deque(maxlen=self.max_tracked_trades)
        
        logger.info(
            f"TradeMonitor initialized: confirmation_timeout={self.confirmation_timeout}s, "
            f"poll_interval={self.poll_interval}s"
        )
    
    def add_trade(
        self,
        trade_id: str,
        execution_result: ExecutionResult,
        encoded_trade: Optional[Dict[str, Any]] = None
    ) -> TradeRecord:
        """
        Add a trade to monitoring.
        
        Args:
            trade_id: Unique trade identifier
            execution_result: Execution result
            encoded_trade: Optional encoded trade data
            
        Returns:
            TradeRecord object
        """
        trade_record = TradeRecord(
            trade_id=trade_id,
            user_op_hash=execution_result.user_op_hash,
            transaction_hash=execution_result.transaction_hash,
            status=TradeStatus.SUBMITTED if execution_result.status == ExecutionStatus.SUBMITTED else TradeStatus.FAILED,
            timestamp=time.time(),
            encoded_trade=encoded_trade,
            execution_result=execution_result,
            error=execution_result.error,
            retry_count=execution_result.retry_count
        )
        
        self.trades[trade_id] = trade_record
        self.pending_trades.append(trade_id)
        
        logger.info(
            f"Trade added to monitoring: {trade_id}, "
            f"status={trade_record.status.value}, "
            f"user_op_hash={trade_record.user_op_hash}"
        )
        
        return trade_record
    
    def monitor_trade(self, trade_id: str) -> TradeStatus:
        """
        Monitor a single trade for confirmation.
        
        Args:
            trade_id: Trade identifier
            
        Returns:
            Final trade status
        """
        if trade_id not in self.trades:
            logger.error(f"Trade {trade_id} not found in monitoring")
            return TradeStatus.FAILED
        
        trade_record = self.trades[trade_id]
        
        if trade_record.status != TradeStatus.SUBMITTED:
            logger.info(f"Trade {trade_id} already in final state: {trade_record.status.value}")
            return trade_record.status
        
        logger.info(f"Monitoring trade {trade_id} for confirmation")
        
        start_time = time.time()
        
        while time.time() - start_time < self.confirmation_timeout:
            # Check status
            status = self._check_trade_status(trade_record)
            
            if status in [TradeStatus.CONFIRMED, TradeStatus.REJECTED, TradeStatus.FAILED]:
                trade_record.status = status
                trade_record.confirmation_timestamp = time.time()
                
                # Remove from pending
                if trade_id in self.pending_trades:
                    self.pending_trades.remove(trade_id)
                
                logger.info(
                    f"Trade {trade_id} reached final state: {status.value}"
                )
                return status
            
            # Wait before next poll
            time.sleep(self.poll_interval)
        
        # Timeout
        trade_record.status = TradeStatus.TIMEOUT
        trade_record.confirmation_timestamp = time.time()
        
        if trade_id in self.pending_trades:
            self.pending_trades.remove(trade_id)
        
        logger.warning(f"Trade {trade_id} timed out after {self.confirmation_timeout}s")
        
        return TradeStatus.TIMEOUT
    
    def monitor_all_pending(self) -> Dict[str, TradeStatus]:
        """
        Monitor all pending trades.
        
        Returns:
            Dictionary mapping trade IDs to final statuses
        """
        logger.info(f"Monitoring {len(self.pending_trades)} pending trades")
        
        results = {}
        
        for trade_id in list(self.pending_trades):
            status = self.monitor_trade(trade_id)
            results[trade_id] = status
        
        return results
    
    def _check_trade_status(self, trade_record: TradeRecord) -> TradeStatus:
        """
        Check current status of a trade.
        
        Args:
            trade_record: Trade record
            
        Returns:
            Current trade status
        """
        if not trade_record.user_op_hash:
            return TradeStatus.FAILED
        
        # Get UserOperation status from bundler
        status_info = self.bundler_client.get_user_operation_status(
            trade_record.user_op_hash
        )
        
        if status_info["status"] == "error":
            logger.error(f"Error checking status for trade {trade_record.trade_id}")
            return TradeStatus.FAILED
        
        user_op = status_info.get("user_operation", {})
        
        # Check if transaction is confirmed
        if user_op.get("transactionHash"):
            trade_record.transaction_hash = user_op["transactionHash"]
            return TradeStatus.CONFIRMED
        
        # Check if UserOperation was rejected
        if user_op.get("success") == False:
            return TradeStatus.REJECTED
        
        # Still pending
        return TradeStatus.SUBMITTED
    
    def get_trade_record(self, trade_id: str) -> Optional[TradeRecord]:
        """
        Get trade record by ID.
        
        Args:
            trade_id: Trade identifier
            
        Returns:
            TradeRecord or None if not found
        """
        return self.trades.get(trade_id)
    
    def get_pending_trades(self) -> List[TradeRecord]:
        """
        Get all pending trades.
        
        Returns:
            List of pending trade records
        """
        return [
            self.trades[trade_id]
            for trade_id in self.pending_trades
            if trade_id in self.trades
        ]
    
    def get_trade_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about monitored trades.
        
        Returns:
            Statistics dictionary
        """
        total_trades = len(self.trades)
        pending_trades = len(self.pending_trades)
        
        status_counts = {}
        for trade in self.trades.values():
            status = trade.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "total_trades": total_trades,
            "pending_trades": pending_trades,
            "status_counts": status_counts,
            "timestamp": time.time()
        }


class TradeErrorHandler:
    """
    Error handler for trade execution failures.
    
    Provides error analysis, rollback logic, and recovery strategies.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize error handler.
        
        Args:
            config: Configuration dictionary
                - auto_rollback: Automatically rollback failed trades (default: false)
                - max_rollback_attempts: Maximum rollback attempts (default: 3)
        """
        self.config = config or {}
        self.auto_rollback = self.config.get("auto_rollback", False)
        self.max_rollback_attempts = self.config.get("max_rollback_attempts", 3)
        
        logger.info(
            f"TradeErrorHandler initialized: auto_rollback={self.auto_rollback}"
        )
    
    def analyze_error(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """
        Analyze execution error to determine cause and recovery strategy.
        
        Args:
            execution_result: Execution result with error
            
        Returns:
            Error analysis dictionary
        """
        error_msg = execution_result.error or "Unknown error"
        
        analysis = {
            "error_type": "unknown",
            "recoverable": False,
            "retry_recommended": False,
            "rollback_required": False,
            "suggested_action": "manual_review"
        }
        
        # Analyze error type
        error_lower = error_msg.lower()
        
        if "insufficient funds" in error_lower:
            analysis["error_type"] = "insufficient_funds"
            analysis["recoverable"] = False
            analysis["suggested_action"] = "add_funds"
        
        elif "nonce" in error_lower:
            analysis["error_type"] = "nonce_error"
            analysis["recoverable"] = True
            analysis["retry_recommended"] = True
            analysis["suggested_action"] = "retry_with_correct_nonce"
        
        elif "gas" in error_lower:
            analysis["error_type"] = "gas_error"
            analysis["recoverable"] = True
            analysis["retry_recommended"] = True
            analysis["suggested_action"] = "increase_gas_limit"
        
        elif "timeout" in error_lower:
            analysis["error_type"] = "timeout"
            analysis["recoverable"] = True
            analysis["retry_recommended"] = True
            analysis["suggested_action"] = "retry_with_longer_timeout"
        
        elif "network" in error_lower:
            analysis["error_type"] = "network_error"
            analysis["recoverable"] = True
            analysis["retry_recommended"] = True
            analysis["suggested_action"] = "retry_after_backoff"
        
        elif "rejected" in error_lower:
            analysis["error_type"] = "rejection"
            analysis["recoverable"] = False
            analysis["suggested_action"] = "review_trade_params"
        
        elif "slippage" in error_lower:
            analysis["error_type"] = "slippage"
            analysis["recoverable"] = True
            analysis["retry_recommended"] = True
            analysis["suggested_action"] = "adjust_price_tolerance"
        
        logger.info(
            f"Error analysis: type={analysis['error_type']}, "
            f"recoverable={analysis['recoverable']}, "
            f"action={analysis['suggested_action']}"
        )
        
        return analysis
    
    def should_rollback(self, execution_result: ExecutionResult) -> bool:
        """
        Determine if a failed trade should be rolled back.
        
        Args:
            execution_result: Execution result
            
        Returns:
            True if rollback should be performed
        """
        if not self.auto_rollback:
            return False
        
        analysis = self.analyze_error(execution_result)
        
        # Rollback on certain error types
        rollback_errors = [
            "insufficient_funds",
            "gas_error",
            "network_error"
        ]
        
        return analysis["error_type"] in rollback_errors
    
    def execute_rollback(
        self,
        trade_record: TradeRecord,
        rollback_callback: Optional[callable] = None
    ) -> bool:
        """
        Execute rollback for a failed trade.
        
        Args:
            trade_record: Trade record to rollback
            rollback_callback: Optional callback for rollback logic
            
        Returns:
            True if rollback successful
        """
        logger.info(f"Executing rollback for trade {trade_record.trade_id}")
        
        try:
            if rollback_callback:
                success = rollback_callback(trade_record)
            else:
                # Default rollback logic: mark as rolled back
                trade_record.status = TradeStatus.ROLLED_BACK
                success = True
            
            if success:
                logger.info(f"Rollback successful for trade {trade_record.trade_id}")
            else:
                logger.error(f"Rollback failed for trade {trade_record.trade_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Rollback exception for trade {trade_record.trade_id}: {e}", exc_info=True)
            return False
    
    def suggest_recovery(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """
        Suggest recovery strategy for failed trade.
        
        Args:
            execution_result: Execution result
            
        Returns:
            Recovery strategy dictionary
        """
        analysis = self.analyze_error(execution_result)
        
        recovery = {
            "strategy": analysis["suggested_action"],
            "parameters": {},
            "estimated_success_rate": 0.5
        }
        
        # Add specific parameters based on error type
        if analysis["error_type"] == "gas_error":
            recovery["parameters"] = {
                "gas_increase_factor": 1.5,
                "max_fee_per_gas": "2000000000"  # 2 gwei
            }
            recovery["estimated_success_rate"] = 0.8
        
        elif analysis["error_type"] == "nonce_error":
            recovery["parameters"] = {
                "nonce_source": "onchain",
                "retry_immediately": True
            }
            recovery["estimated_success_rate"] = 0.9
        
        elif analysis["error_type"] == "timeout":
            recovery["parameters"] = {
                "timeout_multiplier": 2.0,
                "max_retries": 5
            }
            recovery["estimated_success_rate"] = 0.7
        
        elif analysis["error_type"] == "network_error":
            recovery["parameters"] = {
                "backoff_seconds": 10,
                "max_retries": 3
            }
            recovery["estimated_success_rate"] = 0.6
        
        return recovery


class PositionTracker:
    """
    Tracker for open positions from executed trades.
    
    Tracks positions, calculates P&L, and manages position lifecycle.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize position tracker.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.positions: Dict[str, Dict[str, Any]] = {}
        
        logger.info("PositionTracker initialized")
    
    def add_position(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        timestamp: float,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add a new position.
        
        Args:
            position_id: Unique position identifier
            symbol: Trading symbol
            side: Position side (buy/sell)
            entry_price: Entry price
            size: Position size
            timestamp: Entry timestamp
            additional_data: Optional additional data
        """
        self.positions[position_id] = {
            "position_id": position_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "current_price": entry_price,
            "size": size,
            "entry_timestamp": timestamp,
            "exit_timestamp": None,
            "exit_price": None,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "status": "open",
            "additional_data": additional_data or {}
        }
        
        logger.info(
            f"Position added: {position_id}, {side} {size} {symbol} @ {entry_price}"
        )
    
    def update_position(
        self,
        position_id: str,
        current_price: float
    ) -> Optional[Dict[str, Any]]:
        """
        Update position with current price.
        
        Args:
            position_id: Position identifier
            current_price: Current market price
            
        Returns:
            Updated position or None if not found
        """
        if position_id not in self.positions:
            logger.warning(f"Position {position_id} not found")
            return None
        
        position = self.positions[position_id]
        position["current_price"] = current_price
        
        # Calculate unrealized P&L
        if position["side"] == "buy":
            position["pnl"] = (current_price - position["entry_price"]) * position["size"]
            position["pnl_pct"] = (current_price - position["entry_price"]) / position["entry_price"]
        else:  # sell
            position["pnl"] = (position["entry_price"] - current_price) * position["size"]
            position["pnl_pct"] = (position["entry_price"] - current_price) / position["entry_price"]
        
        return position
    
    def close_position(
        self,
        position_id: str,
        exit_price: float,
        timestamp: float
    ) -> Optional[Dict[str, Any]]:
        """
        Close a position.
        
        Args:
            position_id: Position identifier
            exit_price: Exit price
            timestamp: Exit timestamp
            
        Returns:
            Closed position or None if not found
        """
        if position_id not in self.positions:
            logger.warning(f"Position {position_id} not found")
            return None
        
        position = self.positions[position_id]
        position["exit_price"] = exit_price
        position["exit_timestamp"] = timestamp
        position["status"] = "closed"
        
        # Calculate final P&L
        if position["side"] == "buy":
            position["pnl"] = (exit_price - position["entry_price"]) * position["size"]
            position["pnl_pct"] = (exit_price - position["entry_price"]) / position["entry_price"]
        else:  # sell
            position["pnl"] = (position["entry_price"] - exit_price) * position["size"]
            position["pnl_pct"] = (position["entry_price"] - exit_price) / position["entry_price"]
        
        logger.info(
            f"Position closed: {position_id}, P&L={position['pnl']:.2f} "
            f"({position['pnl_pct']:.2%})"
        )
        
        return position
    
    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions.
        
        Returns:
            List of open positions
        """
        return [
            pos for pos in self.positions.values()
            if pos["status"] == "open"
        ]
    
    def get_position_summary(self) -> Dict[str, Any]:
        """
        Get summary of all positions.
        
        Returns:
            Position summary dictionary
        """
        open_positions = self.get_open_positions()
        closed_positions = [
            pos for pos in self.positions.values()
            if pos["status"] == "closed"
        ]
        
        total_pnl = sum(pos["pnl"] for pos in closed_positions)
        total_pnl_pct = sum(pos["pnl_pct"] for pos in closed_positions)
        
        return {
            "total_positions": len(self.positions),
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "total_realized_pnl": total_pnl,
            "total_realized_pnl_pct": total_pnl_pct,
            "unrealized_pnl": sum(pos["pnl"] for pos in open_positions),
            "timestamp": time.time()
        }
