"""
SAI Protocol — Decision Engine
-------------------------------
Decision engine for combining strategy signals and making final trade decisions.

Provides:
  - Multi-strategy signal combination
  - Weight-based decision making
  - Conflict resolution
  - Final trade execution decisions
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .strategy_engine import BaseStrategy, StrategyDecision, StrategySelector, StrategyType
from .risk_manager import RiskManager, RiskMetrics
from .signal_processor import SignalProcessor, TechnicalIndicators, VolumeAnalysis, LiquidityAssessment
from .market_signal import MarketSummary, ArbitrageOpportunity

logger = logging.getLogger(__name__)


class DecisionAction(Enum):
    """Decision action enumeration."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


@dataclass
class FinalDecision:
    """Final trading decision after all processing."""
    action: DecisionAction
    symbol: str
    confidence: float  # 0.0 to 1.0
    reasoning: str
    timestamp: float
    
    # Trade parameters
    entry_price: Optional[float]
    exit_price: Optional[float]
    position_size: float  # Percentage of portfolio
    stop_loss: Optional[float]
    take_profit: Optional[float]
    
    # Risk metrics
    risk_level: str
    expected_return: Optional[float]
    max_loss: Optional[float]
    
    # Source information
    primary_strategy: Optional[str]
    supporting_strategies: List[str] = field(default_factory=list)
    
    # Additional context
    additional_data: Dict[str, Any] = field(default_factory=dict)


class DecisionEngine:
    """
    Decision engine for combining strategy signals and making final trade decisions.
    
    Integrates strategies, risk management, and signal processing to produce
    final execution decisions with documented logic and risk guardrails.
    """
    
    def __init__(
        self,
        strategies: List[BaseStrategy],
        risk_manager: RiskManager,
        signal_processor: SignalProcessor,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize decision engine.
        
        Args:
            strategies: List of trading strategies
            risk_manager: Risk manager instance
            signal_processor: Signal processor instance
            config: Configuration dictionary
                - min_confidence: Minimum confidence to execute (default: 0.6)
                - strategy_weights: Weights for each strategy type (default: arbitrage=0.7, trend=0.3)
                - conflict_resolution: How to resolve conflicts (default: "weighted")
        """
        self.strategies = strategies
        self.risk_manager = risk_manager
        self.signal_processor = signal_processor
        self.config = config or {}
        
        self.min_confidence = self.config.get("min_confidence", 0.6)
        self.conflict_resolution = self.config.get("conflict_resolution", "weighted")
        
        # Strategy weights for decision making
        self.strategy_weights = self.config.get("strategy_weights", {
            StrategyType.ARBITRAGE: 0.7,
            StrategyType.TREND_FOLLOWING: 0.3,
            StrategyType.MEAN_REVERSION: 0.2,
            StrategyType.MARKET_MAKING: 0.1
        })
        
        # Strategy selector
        self.strategy_selector = StrategySelector(strategies, config)
        
        logger.info(
            f"Decision engine initialized with {len(strategies)} strategies, "
            f"min_confidence={self.min_confidence}"
        )
    
    def make_decision(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity],
        current_price: float
    ) -> FinalDecision:
        """
        Make a final trading decision.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities
            current_price: Current market price
            
        Returns:
            FinalDecision object
        """
        logger.info("=" * 60)
        logger.info("DECISION ENGINE: Making trading decision")
        logger.info("=" * 60)
        
        # Step 1: Check if trading is allowed by risk manager
        if not self.risk_manager.is_trading_allowed():
            logger.warning("Trading not allowed by risk manager")
            return self._create_hold_decision(
                "Trading halted by risk manager (drawdown limit or critical risk level)"
            )
        
        # Step 2: Get decisions from all strategies
        strategy_decisions = self._get_strategy_decisions(summary, opportunities)
        
        if not strategy_decisions:
            logger.info("No strategies recommend trading")
            return self._create_hold_decision("No strategies recommend trading")
        
        # Step 3: Combine signals using weighted approach
        combined_decision = self._combine_signals(strategy_decisions, summary)
        
        if not combined_decision.should_trade:
            logger.info(f"Combined decision: HOLD - {combined_decision.reasoning}")
            return self._create_hold_decision(combined_decision.reasoning)
        
        # Step 4: Apply risk management
        risk_adjusted_decision = self._apply_risk_management(combined_decision, current_price)
        
        if not risk_adjusted_decision.should_trade:
            logger.warning(f"Risk management rejected trade: {risk_adjusted_decision.reasoning}")
            return self._create_hold_decision(risk_adjusted_decision.reasoning)
        
        # Step 5: Check confidence threshold
        if risk_adjusted_decision.confidence < self.min_confidence:
            logger.warning(
                f"Confidence {risk_adjusted_decision.confidence:.2f} below threshold {self.min_confidence}"
            )
            return self._create_hold_decision(
                f"Confidence {risk_adjusted_decision.confidence:.2f} below threshold {self.min_confidence}"
            )
        
        # Step 6: Create final decision
        final_decision = self._create_final_decision(
            risk_adjusted_decision,
            strategy_decisions,
            current_price
        )
        
        logger.info(
            f"FINAL DECISION: {final_decision.action.value.upper()} {final_decision.symbol} "
            f"with confidence {final_decision.confidence:.2f}, "
            f"position_size={final_decision.position_size:.0%}"
        )
        
        return final_decision
    
    def _get_strategy_decisions(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> List[StrategyDecision]:
        """
        Get decisions from all strategies.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities
            
        Returns:
            List of strategy decisions
        """
        decisions = []
        
        for strategy in self.strategies:
            try:
                decision = strategy.evaluate(summary, opportunities)
                decisions.append(decision)
                
                if decision.should_trade:
                    logger.info(
                        f"Strategy {strategy.name}: {decision.direction.upper()} "
                        f"with confidence {decision.confidence:.2f}"
                    )
            except Exception as e:
                logger.error(f"Strategy {strategy.name} evaluation failed: {e}", exc_info=True)
        
        return decisions
    
    def _combine_signals(
        self,
        decisions: List[StrategyDecision],
        summary: MarketSummary
    ) -> StrategyDecision:
        """
        Combine signals from multiple strategies.
        
        Args:
            decisions: List of strategy decisions
            summary: Market summary
            
        Returns:
            Combined strategy decision
        """
        # Filter to only decisions that recommend trading
        trading_decisions = [d for d in decisions if d.should_trade]
        
        if not trading_decisions:
            return StrategyDecision(
                should_trade=False,
                direction="hold",
                symbol=summary.symbol,
                confidence=0.0,
                expected_price=None,
                expected_return=None,
                strategy_type=StrategyType.ARBITRAGE,
                reasoning="No strategies recommend trading",
                timestamp=time.time(),
                stop_loss=None,
                take_profit=None,
                position_size=None
            )
        
        # Group by direction
        buy_decisions = [d for d in trading_decisions if d.direction == "buy"]
        sell_decisions = [d for d in trading_decisions if d.direction == "sell"]
        
        # Calculate weighted scores for each direction
        buy_score = self._calculate_direction_score(buy_decisions)
        sell_score = self._calculate_direction_score(sell_decisions)
        
        # Select direction with higher score
        if buy_score > sell_score:
            selected_decisions = buy_decisions
            direction = "buy"
        elif sell_score > buy_score:
            selected_decisions = sell_decisions
            direction = "sell"
        else:
            # Tie - use the decision with highest individual confidence
            selected_decisions = [max(trading_decisions, key=lambda d: d.confidence)]
            direction = selected_decisions[0].direction
        
        # Combine the selected decisions
        combined = self._merge_decisions(selected_decisions, direction)
        
        logger.info(
            f"Signal combination: {direction.upper()} selected "
            f"(buy_score={buy_score:.2f}, sell_score={sell_score:.2f})"
        )
        
        return combined
    
    def _calculate_direction_score(self, decisions: List[StrategyDecision]) -> float:
        """
        Calculate weighted score for a direction.
        
        Args:
            decisions: List of decisions for this direction
            
        Returns:
            Weighted score
        """
        if not decisions:
            return 0.0
        
        total_score = 0.0
        for decision in decisions:
            weight = self.strategy_weights.get(decision.strategy_type, 0.5)
            score = decision.confidence * weight
            total_score += score
        
        return total_score
    
    def _merge_decisions(
        self,
        decisions: List[StrategyDecision],
        direction: str
    ) -> StrategyDecision:
        """
        Merge multiple decisions into one.
        
        Args:
            decisions: List of decisions to merge
            direction: Final direction
            
        Returns:
            Merged decision
        """
        if not decisions:
            raise ValueError("Cannot merge empty decisions list")
        
        # Use the highest confidence decision as base
        base_decision = max(decisions, key=lambda d: d.confidence)
        
        # Average position sizes
        avg_position_size = sum(d.position_size or 0.1 for d in decisions) / len(decisions)
        
        # Average expected returns
        expected_returns = [d.expected_return for d in decisions if d.expected_return is not None]
        avg_expected_return = sum(expected_returns) / len(expected_returns) if expected_returns else None
        
        # Combine reasoning
        reasoning_parts = [base_decision.reasoning]
        if len(decisions) > 1:
            reasoning_parts.append(f"Supported by {len(decisions) - 1} other strategies")
        
        # Create merged decision
        merged = StrategyDecision(
            should_trade=True,
            direction=direction,
            symbol=base_decision.symbol,
            confidence=min(1.0, base_decision.confidence * (1.0 + 0.1 * (len(decisions) - 1))),  # Boost for agreement
            expected_price=base_decision.expected_price,
            expected_return=avg_expected_return,
            strategy_type=base_decision.strategy_type,
            reasoning=". ".join(reasoning_parts),
            timestamp=time.time(),
            stop_loss=base_decision.stop_loss,
            take_profit=base_decision.take_profit,
            position_size=avg_position_size,
            additional_data=base_decision.additional_data
        )
        
        return merged
    
    def _apply_risk_management(
        self,
        decision: StrategyDecision,
        current_price: float
    ) -> StrategyDecision:
        """
        Apply risk management to the decision.
        
        Args:
            decision: Strategy decision
            current_price: Current market price
            
        Returns:
            Risk-adjusted decision
        """
        # Calculate position size with risk manager
        current_exposure = sum(pos.size for pos in self.risk_manager.positions.values())
        position_size, approved = self.risk_manager.calculate_position_size(
            decision, current_exposure
        )
        
        if not approved:
            return StrategyDecision(
                should_trade=False,
                direction="hold",
                symbol=decision.symbol,
                confidence=0.0,
                expected_price=None,
                expected_return=None,
                strategy_type=decision.strategy_type,
                reasoning="Position size rejected by risk manager (exposure limit)",
                timestamp=time.time(),
                stop_loss=None,
                take_profit=None,
                position_size=None
            )
        
        # Update decision with risk-adjusted position size
        decision.position_size = position_size
        
        # Calculate stop loss and take profit if not provided
        if not decision.stop_loss:
            decision.stop_loss = self.risk_manager.calculate_stop_loss(
                current_price, decision.direction
            )
        
        if not decision.take_profit:
            decision.take_profit = self.risk_manager.calculate_take_profit(
                current_price, decision.direction
            )
        
        # Adjust confidence based on risk metrics
        risk_metrics = self.risk_manager.get_risk_metrics()
        if risk_metrics.risk_level.value in ["high", "critical"]:
            decision.confidence *= 0.5  # Reduce confidence for high risk
        
        return decision
    
    def _create_final_decision(
        self,
        decision: StrategyDecision,
        all_decisions: List[StrategyDecision],
        current_price: float
    ) -> FinalDecision:
        """
        Create final decision from strategy decision.
        
        Args:
            decision: Risk-adjusted strategy decision
            all_decisions: All strategy decisions
            current_price: Current market price
            
        Returns:
            FinalDecision object
        """
        # Determine action
        if decision.direction == "buy":
            action = DecisionAction.BUY
        elif decision.direction == "sell":
            action = DecisionAction.SELL
        else:
            action = DecisionAction.HOLD
        
        # Get supporting strategies
        supporting_strategies = [
            d.strategy_type.value for d in all_decisions
            if d.should_trade and d.direction == decision.direction
        ]
        
        # Calculate max loss
        max_loss = None
        if decision.stop_loss and decision.position_size:
            if decision.direction == "buy":
                max_loss = (current_price - decision.stop_loss) / current_price * decision.position_size
            else:
                max_loss = (decision.stop_loss - current_price) / current_price * decision.position_size
        
        # Get risk level
        risk_metrics = self.risk_manager.get_risk_metrics()
        
        return FinalDecision(
            action=action,
            symbol=decision.symbol,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            timestamp=time.time(),
            entry_price=current_price,
            exit_price=decision.take_profit,
            position_size=decision.position_size,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            risk_level=risk_metrics.risk_level.value,
            expected_return=decision.expected_return,
            max_loss=max_loss,
            primary_strategy=decision.strategy_type.value,
            supporting_strategies=supporting_strategies,
            additional_data={
                "strategy_count": len(all_decisions),
                "agreement_count": len(supporting_strategies),
                "risk_metrics": {
                    "total_exposure": risk_metrics.total_exposure,
                    "current_drawdown": risk_metrics.current_drawdown,
                    "num_positions": risk_metrics.num_positions
                }
            }
        )
    
    def _create_hold_decision(self, reasoning: str) -> FinalDecision:
        """
        Create a hold decision.
        
        Args:
            reasoning: Reason for holding
            
        Returns:
            FinalDecision object
        """
        return FinalDecision(
            action=DecisionAction.HOLD,
            symbol="N/A",
            confidence=0.0,
            reasoning=reasoning,
            timestamp=time.time(),
            entry_price=None,
            exit_price=None,
            position_size=0.0,
            stop_loss=None,
            take_profit=None,
            risk_level="N/A",
            expected_return=None,
            max_loss=None,
            primary_strategy=None,
            supporting_strategies=[],
            additional_data={}
        )
    
    def resolve_conflicts(
        self,
        decisions: List[StrategyDecision]
    ) -> StrategyDecision:
        """
        Resolve conflicts between strategy decisions.
        
        Args:
            decisions: List of conflicting decisions
            
        Returns:
            Resolved decision
        """
        if self.conflict_resolution == "weighted":
            return self._weighted_conflict_resolution(decisions)
        elif self.conflict_resolution == "majority":
            return self._majority_conflict_resolution(decisions)
        elif self.conflict_resolution == "highest_confidence":
            return self._highest_confidence_resolution(decisions)
        else:
            return self._weighted_conflict_resolution(decisions)  # Default
    
    def _weighted_conflict_resolution(self, decisions: List[StrategyDecision]) -> StrategyDecision:
        """Resolve conflicts using weighted voting."""
        # Group by direction
        buy_score = self._calculate_direction_score([d for d in decisions if d.direction == "buy"])
        sell_score = self._calculate_direction_score([d for d in decisions if d.direction == "sell"])
        
        if buy_score > sell_score:
            selected = [d for d in decisions if d.direction == "buy"]
        elif sell_score > buy_score:
            selected = [d for d in decisions if d.direction == "sell"]
        else:
            selected = [max(decisions, key=lambda d: d.confidence)]
        
        return self._merge_decisions(selected, selected[0].direction)
    
    def _majority_conflict_resolution(self, decisions: List[StrategyDecision]) -> StrategyDecision:
        """Resolve conflicts using majority voting."""
        buy_count = sum(1 for d in decisions if d.direction == "buy")
        sell_count = sum(1 for d in decisions if d.direction == "sell")
        
        if buy_count > sell_count:
            selected = [d for d in decisions if d.direction == "buy"]
        elif sell_count > buy_count:
            selected = [d for d in decisions if d.direction == "sell"]
        else:
            selected = [max(decisions, key=lambda d: d.confidence)]
        
        return self._merge_decisions(selected, selected[0].direction)
    
    def _highest_confidence_resolution(self, decisions: List[StrategyDecision]) -> StrategyDecision:
        """Resolve conflicts by selecting highest confidence."""
        return max(decisions, key=lambda d: d.confidence)
