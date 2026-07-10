"""
SAI Protocol — Strategy Engine
------------------------------
Trading strategy implementation for decision-making.

Provides:
  - Abstract base class for trading strategies
  - Arbitrage strategy (prediction market vs CEX)
  - Trend following strategy
  - Strategy selection framework
  - Confidence scoring
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .market_signal import MarketSummary, ArbitrageOpportunity

import sys
from pathlib import Path
# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import Config

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Enumeration of strategy types."""
    ARBITRAGE = "arbitrage"
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    MARKET_MAKING = "market_making"


@dataclass
class StrategyDecision:
    """Decision output from a strategy."""
    should_trade: bool
    direction: str  # "buy", "sell", "hold"
    symbol: str
    confidence: float  # 0.0 to 1.0
    expected_price: Optional[float]
    expected_return: Optional[float]
    strategy_type: StrategyType
    reasoning: str
    timestamp: float
    
    # Risk parameters
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: Optional[float]
    
    # Additional context
    additional_data: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.
    
    All strategies must implement the evaluate method to generate
    trading decisions based on market data.
    """
    
    def __init__(self, name: str, strategy_type: StrategyType, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the strategy.
        
        Args:
            name: Strategy name
            strategy_type: Type of strategy
            config: Optional configuration dictionary
        """
        self.name = name
        self.strategy_type = strategy_type
        self.config = config or {}
        self._last_decision_time = 0
        self._decision_count = 0
    
    @abstractmethod
    def evaluate(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> StrategyDecision:
        """
        Evaluate market conditions and generate a trading decision.
        
        Args:
            summary: Market summary with current conditions
            opportunities: List of arbitrage opportunities
            
        Returns:
            StrategyDecision object
        """
        pass
    
    def calculate_confidence(
        self,
        summary: MarketSummary,
        additional_factors: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Calculate confidence score for the decision.
        
        Args:
            summary: Market summary
            additional_factors: Optional additional confidence factors
            
        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = 1.0
        
        # Factor in data quality
        confidence *= summary.confidence
        confidence *= summary.quality_score
        
        # Factor in additional factors if provided
        if additional_factors:
            for factor_name, factor_value in additional_factors.items():
                confidence *= factor_value
        
        # Ensure confidence is between 0 and 1
        return max(0.0, min(1.0, confidence))
    
    def record_decision(self, decision: StrategyDecision):
        """Record a decision for tracking."""
        self._last_decision_time = decision.timestamp
        self._decision_count += 1


class ArbitrageStrategy(BaseStrategy):
    """
    Arbitrage strategy for prediction market vs CEX opportunities.
    
    Compares implied probabilities from Polymarket against
    CEX spot prices to identify mispricings.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize arbitrage strategy.
        
        Args:
            config: Configuration dictionary
                - min_profit_threshold: Minimum profit threshold (default: 0.5%)
                - max_implied_prob: Maximum implied probability to consider (default: 0.95)
                - min_implied_prob: Minimum implied probability to consider (default: 0.05)
        """
        super().__init__("Arbitrage", StrategyType.ARBITRAGE, config)
        self.min_profit_threshold = (config or {}).get("min_profit_threshold", 0.5)  # 0.5%
        self.max_implied_prob = (config or {}).get("max_implied_prob", 0.95)
        self.min_implied_prob = (config or {}).get("min_implied_prob", 0.05)
    
    def evaluate(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> StrategyDecision:
        """
        Evaluate arbitrage opportunities.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities
            
        Returns:
            StrategyDecision object
        """
        # Filter for prediction market opportunities
        prediction_opps = [
            opp for opp in opportunities
            if opp.opportunity_type == "prediction_market" and
            opp.additional_data.get("requires_strategy_engine", False)
        ]
        
        if not prediction_opps:
            return self._no_trade_decision("No prediction market opportunities available")
        
        # Find the best opportunity
        best_opp = max(
            prediction_opps,
            key=lambda x: x.confidence * (1.0 - x.liquidity_risk)
        )
        
        # Calculate expected profit using implied probability model
        expected_profit = self._calculate_expected_profit(best_opp, summary)
        
        # Check if profit threshold is met
        if expected_profit < self.min_profit_threshold:
            return self._no_trade_decision(
                f"Expected profit {expected_profit:.2f}% below threshold {self.min_profit_threshold}%"
            )
        
        # Calculate confidence
        confidence = self.calculate_confidence(
            summary,
            additional_factors={
                "liquidity_factor": 1.0 - best_opp.liquidity_risk,
                "execution_factor": 1.0 - best_opp.execution_risk,
                "time_factor": 1.0 - best_opp.time_risk
            }
        )
        
        # Determine direction based on implied probability
        implied_prob = best_opp.additional_data.get("implied_probability", 0.5)
        
        if implied_prob > 0.5:
            direction = "buy"  # Market thinks event is likely
            expected_price = best_opp.buy_price
        else:
            direction = "sell"  # Market thinks event is unlikely
            expected_price = best_opp.sell_price
        
        # Calculate risk parameters
        stop_loss = expected_price * 0.95  # 5% stop loss
        take_profit = expected_price * (1.0 + expected_profit / 100.0)
        
        decision = StrategyDecision(
            should_trade=True,
            direction=direction,
            symbol=best_opp.symbol,
            confidence=confidence,
            expected_price=expected_price,
            expected_return=expected_profit,
            strategy_type=self.strategy_type,
            reasoning=f"Arbitrage opportunity: {best_opp.additional_data.get('market_question', 'N/A')}. "
                      f"Implied prob: {implied_prob:.2f}, Expected profit: {expected_profit:.2f}%",
            timestamp=time.time(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=self._calculate_position_size(confidence, summary),
            additional_data={
                "condition_id": best_opp.additional_data.get("prediction_condition_id"),
                "market_question": best_opp.additional_data.get("market_question"),
                "implied_probability": implied_prob,
                "cex_price": best_opp.additional_data.get("cex_price"),
                "cex_symbol": best_opp.additional_data.get("cex_symbol")
            }
        )
        
        self.record_decision(decision)
        logger.info(
            f"Arbitrage strategy decision: {direction} {best_opp.symbol} "
            f"with confidence {confidence:.2f}, expected return {expected_profit:.2f}%"
        )
        
        return decision
    
    def _calculate_expected_profit(
        self,
        opportunity: ArbitrageOpportunity,
        summary: MarketSummary
    ) -> float:
        """
        Calculate expected profit for an arbitrage opportunity.
        
        Args:
            opportunity: Arbitrage opportunity
            summary: Market summary
            
        Returns:
            Expected profit percentage
        """
        # This is a simplified model - Sprint B acceptance criteria is documented logic, not backtesting
        # The actual arbitrage calculation would require:
        # 1. Understanding the prediction market structure (YES/NO tokens)
        # 2. Calculating the fair implied probability from CEX spot price
        # 3. Comparing to market implied probability
        
        implied_prob = opportunity.additional_data.get("implied_probability", 0.5)
        cex_price = opportunity.additional_data.get("cex_price", 0)
        
        if cex_price == 0:
            return 0.0
        
        # Simplified: if implied probability is far from 0.5, there may be arbitrage
        # This is a placeholder for the actual model
        deviation = abs(implied_prob - 0.5) * 100  # Convert to percentage
        expected_profit = deviation * 0.5  # Conservative estimate
        
        # Adjust for risk factors
        risk_adjustment = (
            opportunity.liquidity_risk +
            opportunity.execution_risk +
            opportunity.time_risk
        ) / 3.0
        
        expected_profit *= (1.0 - risk_adjustment)
        
        return max(0.0, expected_profit)
    
    def _calculate_position_size(self, confidence: float, summary: MarketSummary) -> float:
        """
        Calculate position size based on confidence and market conditions.
        
        Args:
            confidence: Decision confidence
            summary: Market summary
            
        Returns:
            Position size (percentage of portfolio)
        """
        # Base position size on confidence
        base_size = confidence * 0.5  # Max 50% of portfolio
        
        # Reduce if volatility is high
        if summary.volatility_24h and summary.volatility_24h > 5.0:
            base_size *= 0.5
        
        # Reduce if liquidity is low
        if summary.volume and summary.volume < 1000:
            base_size *= 0.5
        
        return max(0.01, min(0.5, base_size))  # Between 1% and 50%
    
    def _no_trade_decision(self, reason: str) -> StrategyDecision:
        """Create a no-trade decision with reasoning."""
        return StrategyDecision(
            should_trade=False,
            direction="hold",
            symbol="N/A",
            confidence=0.0,
            expected_price=None,
            expected_return=None,
            strategy_type=self.strategy_type,
            reasoning=reason,
            timestamp=time.time(),
            stop_loss=None,
            take_profit=None,
            position_size=None
        )


class TrendFollowingStrategy(BaseStrategy):
    """
    Trend following strategy based on price momentum.
    
    Identifies upward or downward trends and trades in the direction of the trend.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize trend following strategy.
        
        Args:
            config: Configuration dictionary
                - trend_threshold: Minimum price change to consider a trend (default: 5%)
                - momentum_period: Period for momentum calculation (default: 24h)
        """
        super().__init__("Trend Following", StrategyType.TREND_FOLLOWING, config)
        self.trend_threshold = (config or {}).get("trend_threshold", 5.0)  # 5%
        self.momentum_period = (config or {}).get("momentum_period", 24)  # 24 hours
    
    def evaluate(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> StrategyDecision:
        """
        Evaluate trend following opportunities.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities (unused)
            
        Returns:
            StrategyDecision object
        """
        # Check if we have 24h price change data
        if summary.price_change_24h is None:
            return self._no_trade_decision("No 24h price change data available")
        
        price_change = summary.price_change_24h
        
        # Check if trend meets threshold
        if abs(price_change) < self.trend_threshold:
            return self._no_trade_decision(
                f"Price change {price_change:.2f}% below trend threshold {self.trend_threshold}%"
            )
        
        # Determine direction
        if price_change > 0:
            direction = "buy"
            reasoning = f"Strong upward trend: {price_change:.2f}% change in 24h"
        else:
            direction = "sell"
            reasoning = f"Strong downward trend: {price_change:.2f}% change in 24h"
        
        # Calculate confidence
        confidence = self.calculate_confidence(
            summary,
            additional_factors={
                "trend_strength": min(1.0, abs(price_change) / 10.0)  # Stronger trend = higher confidence
            }
        )
        
        # Expected return is the trend continuation
        expected_return = abs(price_change) * 0.5  # Conservative estimate
        
        # Risk parameters
        current_price = summary.current_price
        stop_loss = current_price * 0.95 if direction == "buy" else current_price * 1.05
        take_profit = current_price * 1.10 if direction == "buy" else current_price * 0.90
        
        decision = StrategyDecision(
            should_trade=True,
            direction=direction,
            symbol=summary.symbol,
            confidence=confidence,
            expected_price=current_price,
            expected_return=expected_return,
            strategy_type=self.strategy_type,
            reasoning=reasoning,
            timestamp=time.time(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=self._calculate_position_size(confidence, summary, price_change),
            additional_data={
                "price_change_24h": price_change,
                "volatility_24h": summary.volatility_24h
            }
        )
        
        self.record_decision(decision)
        logger.info(
            f"Trend following decision: {direction} {summary.symbol} "
            f"with confidence {confidence:.2f}, expected return {expected_return:.2f}%"
        )
        
        return decision
    
    def _calculate_position_size(
        self,
        confidence: float,
        summary: MarketSummary,
        price_change: float
    ) -> float:
        """
        Calculate position size based on confidence and trend strength.
        
        Args:
            confidence: Decision confidence
            summary: Market summary
            price_change: 24h price change
            
        Returns:
            Position size (percentage of portfolio)
        """
        # Base position size on confidence
        base_size = confidence * 0.4  # Max 40% for trend following
        
        # Increase with trend strength
        trend_strength = min(1.0, abs(price_change) / 10.0)
        base_size *= (0.5 + 0.5 * trend_strength)
        
        # Reduce if volatility is very high
        if summary.volatility_24h and summary.volatility_24h > 10.0:
            base_size *= 0.5
        
        return max(0.01, min(0.4, base_size))  # Between 1% and 40%
    
    def _no_trade_decision(self, reason: str) -> StrategyDecision:
        """Create a no-trade decision with reasoning."""
        return StrategyDecision(
            should_trade=False,
            direction="hold",
            symbol="N/A",
            confidence=0.0,
            expected_price=None,
            expected_return=None,
            strategy_type=self.strategy_type,
            reasoning=reason,
            timestamp=time.time(),
            stop_loss=None,
            take_profit=None,
            position_size=None
        )


class StrategySelector:
    """
    Strategy selection framework.
    
    Selects the best strategy based on market conditions
    and combines signals from multiple strategies.
    """
    
    def __init__(self, strategies: List[BaseStrategy], config: Optional[Dict[str, Any]] = None):
        """
        Initialize strategy selector.
        
        Args:
            strategies: List of available strategies
            config: Configuration dictionary
                - primary_strategy: Strategy type to prioritize (default: arbitrage)
                - min_confidence: Minimum confidence to execute (default: 0.6)
        """
        self.strategies = strategies
        self.config = config or {}
        self.primary_strategy = StrategyType(
            self.config.get("primary_strategy", Config.PRIMARY_STRATEGY)
        )
        self.min_confidence = self.config.get("min_confidence", Config.MIN_CONFIDENCE)
        
        # Strategy weights for combination - from centralized config
        self.base_strategy_weights = {
            StrategyType.ARBITRAGE: Config.STRATEGY_WEIGHT_ARBITRAGE,
            StrategyType.TREND_FOLLOWING: Config.STRATEGY_WEIGHT_TREND_FOLLOWING
        }
        self.strategy_weights = self.base_strategy_weights.copy()
    
    def adjust_strategy_weights(self, summary: MarketSummary) -> None:
        """
        Dynamically adjust strategy weights based on market regime.
        
        Args:
            summary: Market summary with current conditions
        """
        # Detect market regime based on volatility and price change
        volatility = summary.volatility_24h or 0
        price_change = abs(summary.price_change_24h or 0)
        
        # High volatility regime: reduce trend following, increase arbitrage
        if volatility > 10.0:
            logger.info(f"High volatility regime detected ({volatility:.2f}%), adjusting weights")
            self.strategy_weights[StrategyType.ARBITRAGE] = 0.8
            self.strategy_weights[StrategyType.TREND_FOLLOWING] = 0.2
        # Low volatility regime: increase trend following
        elif volatility < 2.0:
            logger.info(f"Low volatility regime detected ({volatility:.2f}%), adjusting weights")
            self.strategy_weights[StrategyType.ARBITRAGE] = 0.5
            self.strategy_weights[StrategyType.TREND_FOLLOWING] = 0.5
        # Strong trend regime: increase trend following
        elif price_change > 5.0:
            logger.info(f"Strong trend regime detected ({price_change:.2f}% change), adjusting weights")
            self.strategy_weights[StrategyType.ARBITRAGE] = 0.4
            self.strategy_weights[StrategyType.TREND_FOLLOWING] = 0.6
        # Normal regime: use base weights
        else:
            self.strategy_weights = self.base_strategy_weights.copy()
            logger.debug("Normal market regime, using base strategy weights")
    
    def select_strategy(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> Optional[BaseStrategy]:
        """
        Select the best strategy for current market conditions.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities
            
        Returns:
            Selected strategy or None if no strategy is suitable
        """
        # Adjust strategy weights based on market regime
        self.adjust_strategy_weights(summary)
        
        # Prioritize primary strategy if opportunities exist
        if self.primary_strategy == StrategyType.ARBITRAGE:
            prediction_opps = [
                opp for opp in opportunities
                if opp.opportunity_type == "prediction_market"
            ]
            if prediction_opps:
                arbitrage_strategy = self._get_strategy(StrategyType.ARBITRAGE)
                if arbitrage_strategy:
                    return arbitrage_strategy
        
        # Evaluate all strategies
        strategy_scores = {}
        for strategy in self.strategies:
            decision = strategy.evaluate(summary, opportunities)
            score = decision.confidence * self.strategy_weights.get(strategy.strategy_type, 0.5)
            strategy_scores[strategy] = score
        
        # Select strategy with highest score
        if strategy_scores:
            best_strategy = max(strategy_scores, key=strategy_scores.get)
            best_score = strategy_scores[best_strategy]
            
            if best_score >= self.min_confidence:
                logger.info(
                    f"Selected strategy: {best_strategy.name} with score {best_score:.2f}"
                )
                return best_strategy
        
        logger.info("No strategy meets minimum confidence threshold")
        return None
    
    def combine_signals(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> StrategyDecision:
        """
        Combine signals from multiple strategies.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities
            
        Returns:
            Combined strategy decision
        """
        # Adjust strategy weights based on market regime
        self.adjust_strategy_weights(summary)
        
        decisions = []
        
        # Get decisions from all strategies
        for strategy in self.strategies:
            decision = strategy.evaluate(summary, opportunities)
            if decision.should_trade:
                decisions.append(decision)
        
        if not decisions:
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
        
        # Weight decisions by strategy type and confidence
        weighted_decisions = []
        for decision in decisions:
            weight = self.strategy_weights.get(decision.strategy_type, 0.5) * decision.confidence
            weighted_decisions.append((decision, weight))
        
        # Select highest weighted decision
        best_decision, best_weight = max(weighted_decisions, key=lambda x: x[1])
        
        # Adjust confidence based on agreement
        if len(decisions) > 1:
            agreement = sum(1 for d in decisions if d.direction == best_decision.direction) / len(decisions)
            best_decision.confidence *= (0.5 + 0.5 * agreement)
            best_decision.reasoning += f" (Agreement: {agreement:.0%})"
        
        logger.info(
            f"Combined decision: {best_decision.direction} with confidence {best_decision.confidence:.2f}"
        )
        
        return best_decision
    
    def _get_strategy(self, strategy_type: StrategyType) -> Optional[BaseStrategy]:
        """Get strategy by type."""
        for strategy in self.strategies:
            if strategy.strategy_type == strategy_type:
                return strategy
        return None
