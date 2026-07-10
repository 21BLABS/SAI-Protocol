"""
SAI Protocol — Risk Manager
---------------------------
Risk management and position sizing for trading strategies.

Provides:
  - Position sizing logic (Kelly criterion, fixed fraction)
  - Stop-loss mechanisms
  - Portfolio exposure limits
  - Maximum drawdown protection
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .strategy_engine import StrategyDecision

import sys
from pathlib import Path
# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import Config

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Position:
    """Position tracking."""
    symbol: str
    direction: str  # "buy" or "sell"
    entry_price: float
    current_price: float
    size: float  # Position size in portfolio percentage
    timestamp: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


@dataclass
class RiskMetrics:
    """Portfolio risk metrics."""
    total_exposure: float  # Total exposure as percentage of portfolio
    max_position_size: float  # Maximum single position size
    num_positions: int  # Number of open positions
    unrealized_pnl: float  # Total unrealized P&L
    unrealized_pnl_pct: float  # Total unrealized P&L percentage
    max_drawdown: float  # Maximum drawdown from peak
    current_drawdown: float  # Current drawdown from peak
    risk_level: RiskLevel


class RiskManager:
    """
    Risk manager for trading operations.
    
    Enforces risk limits, calculates position sizes, and monitors portfolio health.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize risk manager.
        
        Args:
            config: Configuration dictionary
                - max_position_size: Maximum single position size (default: 0.2 = 20%)
                - max_total_exposure: Maximum total exposure (default: 0.8 = 80%)
                - max_drawdown: Maximum allowed drawdown (default: 0.10 = 10%)
                - stop_loss_pct: Default stop loss percentage (default: 0.05 = 5%)
                - take_profit_pct: Default take profit percentage (default: 0.10 = 10%)
                - position_sizing_method: "kelly" or "fixed_fraction" (default: "fixed_fraction")
                - kelly_fraction: Kelly criterion fraction (default: 0.25)
                - fixed_fraction: Fixed fraction sizing (default: 0.1 = 10%)
        """
        self.config = config or {}
        
        # Risk limits - from centralized config
        self.max_position_size = self.config.get("max_position_size", Config.MAX_POSITION_SIZE)
        self.max_total_exposure = self.config.get("max_total_exposure", Config.MAX_TOTAL_EXPOSURE)
        self.max_drawdown = self.config.get("max_drawdown", Config.MAX_DRAWDOWN)
        
        # Default risk parameters - from centralized config
        self.default_stop_loss_pct = self.config.get("stop_loss_pct", Config.DEFAULT_STOP_LOSS_PCT)
        self.default_take_profit_pct = self.config.get("take_profit_pct", Config.DEFAULT_TAKE_PROFIT_PCT)
        
        # Position sizing - from centralized config
        self.position_sizing_method = self.config.get("position_sizing_method", Config.POSITION_SIZING_METHOD)
        self.kelly_fraction = self.config.get("kelly_fraction", Config.KELLY_FRACTION)
        self.fixed_fraction = self.config.get("fixed_fraction", Config.FIXED_FRACTION)
        
        # Portfolio state
        self.positions: Dict[str, Position] = {}
        self.peak_portfolio_value = 1.0  # Normalized to 1.0
        self.current_portfolio_value = 1.0
        self.initial_portfolio_value = 1.0
        
        logger.info(
            f"RiskManager initialized: max_position={self.max_position_size:.0%}, "
            f"max_exposure={self.max_total_exposure:.0%}, max_drawdown={self.max_drawdown:.0%}"
        )
    
    def calculate_position_size(
        self,
        decision: StrategyDecision,
        current_exposure: float
    ) -> Tuple[float, bool]:
        """
        Calculate position size based on risk parameters.
        
        Args:
            decision: Strategy decision
            current_exposure: Current total exposure
            
        Returns:
            Tuple of (position_size, approved)
        """
        # Base position size from decision
        base_size = decision.position_size or 0.1
        
        # Apply position sizing method
        if self.position_sizing_method == "kelly":
            position_size = self._kelly_criterion_sizing(decision, base_size)
        else:
            position_size = self._fixed_fraction_sizing(decision, base_size)
        
        # Enforce maximum position size
        position_size = min(position_size, self.max_position_size)
        
        # Check if adding this position would exceed total exposure
        if current_exposure + position_size > self.max_total_exposure:
            logger.warning(
                f"Position size {position_size:.0%} would exceed max exposure "
                f"{self.max_total_exposure:.0%} (current: {current_exposure:.0%})"
            )
            position_size = self.max_total_exposure - current_exposure
        
        # Minimum position size
        if position_size < 0.01:  # 1%
            logger.warning(f"Position size {position_size:.0%} below minimum 1%")
            return 0.0, False
        
        return position_size, True
    
    def _kelly_criterion_sizing(self, decision: StrategyDecision, base_size: float) -> float:
        """
        Calculate position size using Kelly criterion.
        
        Args:
            decision: Strategy decision
            base_size: Base position size from strategy
            
        Returns:
            Kelly-adjusted position size
        """
        if decision.expected_return is None:
            return base_size
        
        # Kelly formula: f = (bp - q) / b
        # where b = odds, p = win probability, q = loss probability
        # Simplified: use confidence as win probability
        win_prob = decision.confidence
        loss_prob = 1.0 - win_prob
        
        if decision.expected_return > 0:
            odds = decision.expected_return / 100.0  # Convert percentage to decimal
            kelly_fraction = (odds * win_prob - loss_prob) / odds if odds > 0 else 0
        else:
            kelly_fraction = 0
        
        # Apply Kelly fraction (fractional Kelly to reduce risk)
        position_size = abs(kelly_fraction) * self.kelly_fraction
        
        # Ensure position size is reasonable
        return max(0.01, min(0.3, position_size))
    
    def _fixed_fraction_sizing(self, decision: StrategyDecision, base_size: float) -> float:
        """
        Calculate position size using fixed fraction method.
        
        Args:
            decision: Strategy decision
            base_size: Base position size from strategy
            
        Returns:
            Fixed fraction position size
        """
        # Adjust base size by confidence
        adjusted_size = base_size * decision.confidence
        
        # Apply fixed fraction
        position_size = adjusted_size * self.fixed_fraction
        
        # Ensure position size is reasonable
        return max(0.01, min(0.3, position_size))
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        direction: str,
        custom_stop_loss_pct: Optional[float] = None
    ) -> float:
        """
        Calculate stop loss price.
        
        Args:
            entry_price: Entry price
            direction: Trade direction ("buy" or "sell")
            custom_stop_loss_pct: Custom stop loss percentage
            
        Returns:
            Stop loss price
        """
        stop_loss_pct = custom_stop_loss_pct or self.default_stop_loss_pct
        
        if direction == "buy":
            stop_loss = entry_price * (1.0 - stop_loss_pct)
        else:  # sell
            stop_loss = entry_price * (1.0 + stop_loss_pct)
        
        return stop_loss
    
    def calculate_take_profit(
        self,
        entry_price: float,
        direction: str,
        custom_take_profit_pct: Optional[float] = None
    ) -> float:
        """
        Calculate take profit price.
        
        Args:
            entry_price: Entry price
            direction: Trade direction ("buy" or "sell")
            custom_take_profit_pct: Custom take profit percentage
            
        Returns:
            Take profit price
        """
        take_profit_pct = custom_take_profit_pct or self.default_take_profit_pct
        
        if direction == "buy":
            take_profit = entry_price * (1.0 + take_profit_pct)
        else:  # sell
            take_profit = entry_price * (1.0 - take_profit_pct)
        
        return take_profit
    
    def check_exposure_limit(self, new_position_size: float) -> bool:
        """
        Check if adding a new position would exceed exposure limits.
        
        Args:
            new_position_size: Size of new position
            
        Returns:
            True if within limits, False otherwise
        """
        current_exposure = sum(pos.size for pos in self.positions.values())
        total_exposure = current_exposure + new_position_size
        
        if total_exposure > self.max_total_exposure:
            logger.warning(
                f"Total exposure {total_exposure:.0%} would exceed limit {self.max_total_exposure:.0%}"
            )
            return False
        
        return True
    
    def check_drawdown_limit(self) -> bool:
        """
        Check if current drawdown exceeds maximum allowed.
        
        Returns:
            True if within limits, False otherwise
        """
        current_drawdown = self._calculate_current_drawdown()
        
        if current_drawdown > self.max_drawdown:
            logger.error(
                f"Current drawdown {current_drawdown:.0%} exceeds limit {self.max_drawdown:.0%}. "
                "TRADING HALTED."
            )
            return False
        
        return True
    
    def _calculate_current_drawdown(self) -> float:
        """
        Calculate current drawdown from peak.
        
        Returns:
            Current drawdown as percentage
        """
        if self.peak_portfolio_value <= 0:
            return 0.0
        
        drawdown = (self.peak_portfolio_value - self.current_portfolio_value) / self.peak_portfolio_value
        return max(0.0, drawdown)
    
    def add_position(self, decision: StrategyDecision, current_price: float) -> bool:
        """
        Add a new position to the portfolio.
        
        Args:
            decision: Strategy decision
            current_price: Current market price
            
        Returns:
            True if position added, False otherwise
        """
        # Check exposure limit
        if not self.check_exposure_limit(decision.position_size or 0.1):
            return False
        
        # Check drawdown limit
        if not self.check_drawdown_limit():
            return False
        
        # Calculate stop loss and take profit if not provided
        stop_loss = decision.stop_loss or self.calculate_stop_loss(
            current_price, decision.direction
        )
        take_profit = decision.take_profit or self.calculate_take_profit(
            current_price, decision.direction
        )
        
        # Create position
        position = Position(
            symbol=decision.symbol,
            direction=decision.direction,
            entry_price=current_price,
            current_price=current_price,
            size=decision.position_size or 0.1,
            timestamp=time.time(),
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        self.positions[decision.symbol] = position
        
        logger.info(
            f"Position added: {decision.direction} {decision.symbol} "
            f"@ {current_price:.4f}, size={position.size:.0%}, "
            f"SL={stop_loss:.4f}, TP={take_profit:.4f}"
        )
        
        return True
    
    def update_position(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Update position with current price and check for stop loss/take profit.
        
        Args:
            symbol: Position symbol
            current_price: Current market price
            
        Returns:
            Action to take: "close", "hold", or None if position not found
        """
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        position.current_price = current_price
        
        # Calculate unrealized P&L
        if position.direction == "buy":
            position.unrealized_pnl_pct = (current_price - position.entry_price) / position.entry_price
        else:  # sell
            position.unrealized_pnl_pct = (position.entry_price - current_price) / position.entry_price
        
        position.unrealized_pnl = position.size * position.unrealized_pnl_pct
        
        # Check stop loss
        if position.stop_loss:
            if position.direction == "buy" and current_price <= position.stop_loss:
                logger.warning(f"Stop loss triggered for {symbol}: {current_price:.4f} <= {position.stop_loss:.4f}")
                return "close"
            elif position.direction == "sell" and current_price >= position.stop_loss:
                logger.warning(f"Stop loss triggered for {symbol}: {current_price:.4f} >= {position.stop_loss:.4f}")
                return "close"
        
        # Check take profit
        if position.take_profit:
            if position.direction == "buy" and current_price >= position.take_profit:
                logger.info(f"Take profit triggered for {symbol}: {current_price:.4f} >= {position.take_profit:.4f}")
                return "close"
            elif position.direction == "sell" and current_price <= position.take_profit:
                logger.info(f"Take profit triggered for {symbol}: {current_price:.4f} <= {position.take_profit:.4f}")
                return "close"
        
        return "hold"
    
    def close_position(self, symbol: str, exit_price: float) -> float:
        """
        Close a position and return realized P&L.
        
        Args:
            symbol: Position symbol
            exit_price: Exit price
            
        Returns:
            Realized P&L as percentage of portfolio
        """
        if symbol not in self.positions:
            logger.warning(f"Position {symbol} not found")
            return 0.0
        
        position = self.positions[symbol]
        
        # Calculate realized P&L
        if position.direction == "buy":
            pnl_pct = (exit_price - position.entry_price) / position.entry_price
        else:  # sell
            pnl_pct = (position.entry_price - exit_price) / position.entry_price
        
        realized_pnl = position.size * pnl_pct
        
        # Update portfolio value
        self.current_portfolio_value += realized_pnl
        
        # Update peak if we're at a new high
        if self.current_portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = self.current_portfolio_value
        
        logger.info(
            f"Position closed: {symbol}, P&L={realized_pnl:.2%}, "
            f"exit_price={exit_price:.4f}, portfolio_value={self.current_portfolio_value:.4f}"
        )
        
        # Remove position
        del self.positions[symbol]
        
        return realized_pnl
    
    def get_risk_metrics(self) -> RiskMetrics:
        """
        Get current risk metrics.
        
        Returns:
            RiskMetrics object
        """
        total_exposure = sum(pos.size for pos in self.positions.values())
        max_position_size = max((pos.size for pos in self.positions.values()), default=0.0)
        num_positions = len(self.positions)
        
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        total_unrealized_pnl_pct = total_unrealized_pnl / self.current_portfolio_value if self.current_portfolio_value > 0 else 0.0
        
        current_drawdown = self._calculate_current_drawdown()
        
        # Determine risk level
        if current_drawdown < 0.02:
            risk_level = RiskLevel.LOW
        elif current_drawdown < 0.05:
            risk_level = RiskLevel.MEDIUM
        elif current_drawdown < 0.08:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.CRITICAL
        
        return RiskMetrics(
            total_exposure=total_exposure,
            max_position_size=max_position_size,
            num_positions=num_positions,
            unrealized_pnl=total_unrealized_pnl,
            unrealized_pnl_pct=total_unrealized_pnl_pct,
            max_drawdown=self.max_drawdown,
            current_drawdown=current_drawdown,
            risk_level=risk_level
        )
    
    def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed based on risk limits.
        
        Returns:
            True if trading allowed, False otherwise
        """
        # Check drawdown limit
        if not self.check_drawdown_limit():
            return False
        
        # Check if we're at critical risk level
        if self.get_risk_metrics().risk_level == RiskLevel.CRITICAL:
            logger.warning("Trading halted: Risk level is CRITICAL")
            return False
        
        return True
    
    def reset(self):
        """Reset risk manager state."""
        self.positions.clear()
        self.peak_portfolio_value = 1.0
        self.current_portfolio_value = 1.0
        logger.info("Risk manager reset")
