"""
SAI Protocol — Strategy Engine Test
----------------------------------
End-to-end test for the strategy engine.

Tests:
  - Strategy initialization
  - Arbitrage strategy evaluation
  - Trend following strategy evaluation
  - Risk manager position sizing
  - Decision engine integration
"""

import os
import sys
import logging
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Import modules directly to avoid loading trading_agent which requires env vars
from agents.trading import strategy_engine
from agents.trading import risk_manager
from agents.trading import signal_processor
from agents.trading import decision_engine
from agents.trading import market_signal

ArbitrageStrategy = strategy_engine.ArbitrageStrategy
TrendFollowingStrategy = strategy_engine.TrendFollowingStrategy
StrategySelector = strategy_engine.StrategySelector
RiskManager = risk_manager.RiskManager
SignalProcessor = signal_processor.SignalProcessor
DecisionEngine = decision_engine.DecisionEngine
MarketSummary = market_signal.MarketSummary
ArbitrageOpportunity = market_signal.ArbitrageOpportunity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


def test_strategy_initialization():
    """Test strategy initialization."""
    logger.info("=" * 60)
    logger.info("TEST 1: Strategy Initialization")
    logger.info("=" * 60)
    
    try:
        # Initialize strategies
        arbitrage_strategy = ArbitrageStrategy()
        trend_strategy = TrendFollowingStrategy()
        
        logger.info("✓ Arbitrage strategy initialized")
        logger.info("✓ Trend following strategy initialized")
        
        # Check strategy types
        assert arbitrage_strategy.strategy_type.value == "arbitrage"
        assert trend_strategy.strategy_type.value == "trend_following"
        
        logger.info("✓ Strategy types verified")
        
        logger.info("✓ Strategy initialization test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Strategy initialization test FAILED: {e}", exc_info=True)
        return False


def test_arbitrage_strategy():
    """Test arbitrage strategy evaluation."""
    logger.info("=" * 60)
    logger.info("TEST 2: Arbitrage Strategy")
    logger.info("=" * 60)
    
    try:
        # Initialize strategy
        strategy = ArbitrageStrategy()
        
        # Create market summary
        summary = MarketSummary(
            symbol="BTC/USD",
            current_price=63000.0,
            volume=1000000.0,
            price_change_24h=2.5,
            volatility_24h=3.0,
            spread=0.01,
            mid_price=63000.0,
            bid_volume=500000.0,
            ask_volume=500000.0,
            timestamp=0,
            sources_used=["Coinbase"],
            confidence=0.95,
            quality_score=0.9,
            additional_data={}
        )
        
        # Create arbitrage opportunity
        opportunity = ArbitrageOpportunity(
            symbol="BTC/USD_vs_cond_123",
            opportunity_type="prediction_market",
            expected_profit=5.0,
            confidence=0.8,
            timestamp=0,
            buy_price=63000.0,
            sell_price=0.6,  # Implied probability
            buy_source="Coinbase",
            sell_source="Polymarket",
            liquidity_risk=0.3,
            execution_risk=0.2,
            time_risk=0.1,
            additional_data={
                "cex_symbol": "BTC/USD",
                "cex_price": 63000.0,
                "prediction_condition_id": "cond_123",
                "implied_probability": 0.6,
                "market_question": "Will BTC be above $65000 by end of year?",
                "requires_strategy_engine": True
            }
        )
        
        # Evaluate
        decision = strategy.evaluate(summary, [opportunity])
        
        logger.info(f"Decision: should_trade={decision.should_trade}")
        logger.info(f"Direction: {decision.direction}")
        logger.info(f"Confidence: {decision.confidence:.2f}")
        logger.info(f"Reasoning: {decision.reasoning}")
        
        if decision.should_trade:
            logger.info("✓ Arbitrage strategy generated trade decision")
        else:
            logger.info("⚠ Arbitrage strategy did not generate trade (may be expected)")
        
        logger.info("✓ Arbitrage strategy test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Arbitrage strategy test FAILED: {e}", exc_info=True)
        return False


def test_trend_strategy():
    """Test trend following strategy evaluation."""
    logger.info("=" * 60)
    logger.info("TEST 3: Trend Following Strategy")
    logger.info("=" * 60)
    
    try:
        # Initialize strategy
        strategy = TrendFollowingStrategy()
        
        # Create market summary with strong uptrend
        summary = MarketSummary(
            symbol="BTC/USD",
            current_price=63000.0,
            volume=1000000.0,
            price_change_24h=8.0,  # Strong uptrend
            volatility_24h=4.0,
            spread=0.01,
            mid_price=63000.0,
            bid_volume=500000.0,
            ask_volume=500000.0,
            timestamp=0,
            sources_used=["Coinbase"],
            confidence=0.95,
            quality_score=0.9,
            additional_data={}
        )
        
        # Evaluate
        decision = strategy.evaluate(summary, [])
        
        logger.info(f"Decision: should_trade={decision.should_trade}")
        logger.info(f"Direction: {decision.direction}")
        logger.info(f"Confidence: {decision.confidence:.2f}")
        logger.info(f"Reasoning: {decision.reasoning}")
        
        if decision.should_trade:
            logger.info("✓ Trend following strategy generated trade decision")
        else:
            logger.info("⚠ Trend following strategy did not generate trade (may be expected)")
        
        logger.info("✓ Trend following strategy test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Trend following strategy test FAILED: {e}", exc_info=True)
        return False


def test_risk_manager():
    """Test risk manager functionality."""
    logger.info("=" * 60)
    logger.info("TEST 4: Risk Manager")
    logger.info("=" * 60)
    
    try:
        # Initialize risk manager
        risk_manager = RiskManager()
        
        logger.info("✓ Risk manager initialized")
        
        # Test position sizing
        from agents.trading.strategy_engine import StrategyDecision, StrategyType
        
        decision = StrategyDecision(
            should_trade=True,
            direction="buy",
            symbol="BTC/USD",
            confidence=0.8,
            expected_price=63000.0,
            expected_return=5.0,
            strategy_type=StrategyType.ARBITRAGE,
            reasoning="Test decision",
            timestamp=0,
            stop_loss=60000.0,
            take_profit=66000.0,
            position_size=0.2
        )
        
        position_size, approved = risk_manager.calculate_position_size(decision, 0.0)
        
        logger.info(f"Position size: {position_size:.0%}, approved: {approved}")
        
        if approved:
            logger.info("✓ Position size approved")
        else:
            logger.info("⚠ Position size rejected")
        
        # Test stop loss calculation
        stop_loss = risk_manager.calculate_stop_loss(63000.0, "buy")
        logger.info(f"Stop loss for buy: {stop_loss:.2f}")
        
        # Test take profit calculation
        take_profit = risk_manager.calculate_take_profit(63000.0, "buy")
        logger.info(f"Take profit for buy: {take_profit:.2f}")
        
        # Test risk metrics
        metrics = risk_manager.get_risk_metrics()
        logger.info(f"Risk level: {metrics.risk_level.value}")
        logger.info(f"Total exposure: {metrics.total_exposure:.0%}")
        
        logger.info("✓ Risk manager test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Risk manager test FAILED: {e}", exc_info=True)
        return False


def test_decision_engine():
    """Test decision engine integration."""
    logger.info("=" * 60)
    logger.info("TEST 5: Decision Engine")
    logger.info("=" * 60)
    
    try:
        # Initialize components
        arbitrage_strategy = ArbitrageStrategy()
        trend_strategy = TrendFollowingStrategy()
        risk_manager = RiskManager()
        signal_processor = SignalProcessor()
        
        # Initialize decision engine
        decision_engine = DecisionEngine(
            strategies=[arbitrage_strategy, trend_strategy],
            risk_manager=risk_manager,
            signal_processor=signal_processor
        )
        
        logger.info("✓ Decision engine initialized")
        
        # Create market summary
        summary = MarketSummary(
            symbol="BTC/USD",
            current_price=63000.0,
            volume=1000000.0,
            price_change_24h=8.0,
            volatility_24h=4.0,
            spread=0.01,
            mid_price=63000.0,
            bid_volume=500000.0,
            ask_volume=500000.0,
            timestamp=0,
            sources_used=["Coinbase"],
            confidence=0.95,
            quality_score=0.9,
            additional_data={}
        )
        
        # Make decision
        final_decision = decision_engine.make_decision(summary, [], 63000.0)
        
        logger.info(f"Action: {final_decision.action.value}")
        logger.info(f"Symbol: {final_decision.symbol}")
        logger.info(f"Confidence: {final_decision.confidence:.2f}")
        logger.info(f"Reasoning: {final_decision.reasoning}")
        
        if final_decision.action.value in ["buy", "sell"]:
            logger.info(f"Position size: {final_decision.position_size:.0%}")
            logger.info(f"Stop loss: {final_decision.stop_loss}")
            logger.info(f"Take profit: {final_decision.take_profit}")
            logger.info("✓ Decision engine generated trade decision")
        else:
            logger.info("⚠ Decision engine generated HOLD (may be expected)")
        
        logger.info("✓ Decision engine test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Decision engine test FAILED: {e}", exc_info=True)
        return False


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("STRATEGY ENGINE TEST SUITE")
    logger.info("=" * 60)
    
    results = {}
    
    # Run tests
    results["Strategy Initialization"] = test_strategy_initialization()
    results["Arbitrage Strategy"] = test_arbitrage_strategy()
    results["Trend Following Strategy"] = test_trend_strategy()
    results["Risk Manager"] = test_risk_manager()
    results["Decision Engine"] = test_decision_engine()
    
    # Summary
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASSED" if result else "✗ FAILED"
        logger.info(f"{test_name}: {status}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("✓ ALL TESTS PASSED")
        return 0
    else:
        logger.error("✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
