"""
SAI Protocol — Market Signal Generation
----------------------------------------
Aggregates market data and generates trading signals.

Provides:
  - Data aggregation from multiple sources
  - Market summary generation
  - Volatility metrics calculation
  - Arbitrage opportunity detection
  - Signal quality assessment
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
import statistics

from .market_data_feed import MarketData, OrderBook
from .data_normalizer import NormalizedMarketData, NormalizedOrderBook, DataNormalizer

logger = logging.getLogger(__name__)


@dataclass
class MarketSummary:
    """Comprehensive market summary for a symbol."""
    symbol: str
    current_price: float
    volume: float
    price_change_24h: Optional[float]
    volatility_24h: Optional[float]
    timestamp: float
    
    # Order book metrics
    spread: Optional[float]
    mid_price: Optional[float]
    bid_volume: Optional[float]
    ask_volume: Optional[float]
    
    # Data quality
    sources_used: List[str]
    confidence: float
    quality_score: float
    
    # Additional context
    additional_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArbitrageOpportunity:
    """Detected arbitrage opportunity."""
    symbol: str
    opportunity_type: str  # "price", "cross_exchange", "prediction_market"
    expected_profit: float
    confidence: float
    timestamp: float
    
    # Details
    buy_price: float
    sell_price: float
    buy_source: str
    sell_source: str
    
    # Risk factors
    liquidity_risk: float
    execution_risk: float
    time_risk: float
    
    additional_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradingSignal:
    """Generated trading signal."""
    symbol: str
    signal_type: str  # "buy", "sell", "hold"
    confidence: float
    timestamp: float
    
    # Signal rationale
    reason: str
    indicators: Dict[str, Any]
    
    # Risk metrics
    risk_level: str  # "low", "medium", "high"
    expected_return: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    
    additional_data: Dict[str, Any] = field(default_factory=dict)


class MarketSignalGenerator:
    """
    Generates market signals from aggregated data.
    
    Aggregates data from multiple sources, calculates metrics,
    detects opportunities, and generates trading signals.
    """
    
    def __init__(self, normalizer: DataNormalizer):
        """
        Initialize the market signal generator.
        
        Args:
            normalizer: DataNormalizer instance for data normalization
        """
        self.normalizer = normalizer
        self._price_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        self._max_history_length = 1000
        
        # Signal generation parameters
        self.volatility_threshold = 2.0  # 2% volatility threshold
        self.spread_threshold = 0.01  # 1% spread threshold
        self.min_confidence = 0.6  # Minimum confidence for signals
        
    def generate_market_summary(
        self,
        market_data_list: List[MarketData],
        order_book: Optional[OrderBook] = None
    ) -> Optional[MarketSummary]:
        """
        Generate a comprehensive market summary.
        
        Args:
            market_data_list: List of market data from different sources
            order_book: Optional order book data
            
        Returns:
            MarketSummary or None if insufficient data
        """
        if not market_data_list:
            logger.warning("No market data provided for summary generation")
            return None
        
        # Normalize and merge data
        normalized_data = self.normalizer.merge_multiple_sources(market_data_list)
        if not normalized_data:
            logger.warning("Failed to normalize market data")
            return None
        
        # Normalize order book if provided
        normalized_order_book = None
        if order_book:
            normalized_order_book = self.normalizer.normalize_order_book(order_book)
        
        # Build summary
        summary = MarketSummary(
            symbol=normalized_data.normalized_symbol,
            current_price=normalized_data.price,
            volume=normalized_data.volume,
            price_change_24h=normalized_data.price_change_24h,
            volatility_24h=normalized_data.volatility_24h,
            timestamp=normalized_data.normalized_timestamp,
            spread=normalized_order_book.spread if normalized_order_book else None,
            mid_price=normalized_order_book.mid_price if normalized_order_book else None,
            bid_volume=normalized_order_book.bid_volume if normalized_order_book else None,
            ask_volume=normalized_order_book.ask_volume if normalized_order_book else None,
            sources_used=normalized_data.additional_data.get("sources_used", [normalized_data.source]),
            confidence=normalized_data.confidence,
            quality_score=normalized_data.quality_score,
            additional_data=normalized_data.additional_data
        )
        
        change_str = f"change_24h={summary.price_change_24h:.2f}%," if summary.price_change_24h is not None else "change_24h=N/A,"
        logger.info(
            f"Generated market summary for {summary.symbol}: "
            f"price={summary.current_price:.4f}, "
            f"{change_str} "
            f"confidence={summary.confidence:.2f}"
        )
        
        return summary
    
    def detect_arbitrage_opportunities(
        self,
        market_data_list: List[MarketData],
        order_books: Optional[List[OrderBook]] = None
    ) -> List[ArbitrageOpportunity]:
        """
        Detect arbitrage opportunities across sources.
        
        Separates CEX spot prices from prediction market probabilities.
        CEX vs CEX comparisons are filtered out (noise, not arbitrage).
        Only CEX vs prediction market comparisons are flagged for Sprint B strategy engine.
        
        Args:
            market_data_list: List of market data from different sources
            order_books: Optional list of order books
            
        Returns:
            List of detected arbitrage opportunities
        """
        opportunities = []
        
        # Normalize all data
        normalized_data_list = [
            self.normalizer.normalize_market_data(data)
            for data in market_data_list
        ]
        
        # Separate CEX data from prediction market data
        cex_data = []
        prediction_data = []
        
        for data in normalized_data_list:
            # Check if this is prediction market data (Polymarket)
            is_prediction = (
                data.source == "Polymarket" or
                data.additional_data.get("market_type") == "prediction" or
                data.additional_data.get("implied_probability") is not None
            )
            
            if is_prediction:
                prediction_data.append(data)
            else:
                cex_data.append(data)
        
        # Skip CEX vs CEX comparisons (noise, not arbitrage)
        if len(cex_data) >= 2:
            logger.debug(
                f"Skipping CEX vs CEX comparison ({len(cex_data)} CEX sources). "
                "This is noise, not arbitrage signal."
            )
        
        # Only compare CEX vs prediction markets
        # The actual arbitrage logic (implied probability model) is Sprint B's job
        # Here we just flag the data for the strategy engine to consume
        if cex_data and prediction_data:
            for cex_point in cex_data:
                for pred_point in prediction_data:
                    # Group by underlying asset if possible
                    # For now, flag as potential arbitrage for strategy engine
                    opportunity = ArbitrageOpportunity(
                        symbol=f"{cex_point.normalized_symbol}_vs_{pred_point.symbol}",
                        opportunity_type="prediction_market",
                        expected_profit=0.0,  # Sprint B will calculate this
                        confidence=min(cex_point.confidence, pred_point.confidence),
                        timestamp=time.time(),
                        buy_price=cex_point.price,
                        sell_price=pred_point.price,
                        buy_source=cex_point.source,
                        sell_source=pred_point.source,
                        liquidity_risk=0.5,  # Medium risk for prediction markets
                        execution_risk=0.4,
                        time_risk=0.3,
                        additional_data={
                            "cex_symbol": cex_point.normalized_symbol,
                            "cex_price": cex_point.price,
                            "prediction_condition_id": pred_point.symbol,
                            "implied_probability": pred_point.price,
                            "market_question": pred_point.additional_data.get("question", "N/A"),
                            "requires_strategy_engine": True  # Flag for Sprint B
                        }
                    )
                    
                    opportunities.append(opportunity)
                    logger.info(
                        f"Flagged CEX vs prediction market data for strategy engine: "
                        f"CEX={cex_point.normalized_symbol} @ {cex_point.price:.4f}, "
                        f"Prediction={pred_point.symbol} @ {pred_point.price:.4f} (implied prob)"
                    )
        
        # Check order book arbitrage (still valid for single source)
        if order_books:
            for order_book in order_books:
                normalized_ob = self.normalizer.normalize_order_book(order_book)
                if normalized_ob.spread and normalized_ob.spread > 0:
                    spread_pct = (normalized_ob.spread / normalized_ob.mid_price) * 100 if normalized_ob.mid_price else 0
                    
                    if spread_pct > self.spread_threshold * 100:
                        opportunity = ArbitrageOpportunity(
                            symbol=normalized_ob.normalized_symbol,
                            opportunity_type="order_book",
                            expected_profit=spread_pct,
                            confidence=0.8,  # Order book data is generally reliable
                            timestamp=time.time(),
                            buy_price=normalized_ob.bids[0][0] if normalized_ob.bids else 0,
                            sell_price=normalized_ob.asks[0][0] if normalized_ob.asks else 0,
                            buy_source=normalized_ob.source,
                            sell_source=normalized_ob.source,
                            liquidity_risk=0.3,  # Lower risk for order book arbitrage
                            execution_risk=0.2,
                            time_risk=0.1,
                            additional_data={
                                "spread": normalized_ob.spread,
                                "mid_price": normalized_ob.mid_price
                            }
                        )
                        
                        opportunities.append(opportunity)
                        logger.info(
                            f"Detected order book arbitrage for {normalized_ob.symbol}: "
                            f"spread={spread_pct:.2f}%"
                        )
        
        return opportunities
    
    def generate_trading_signal(
        self,
        summary: MarketSummary,
        opportunities: List[ArbitrageOpportunity]
    ) -> Optional[TradingSignal]:
        """
        Generate a trading signal based on market summary and opportunities.
        
        Args:
            summary: Market summary
            opportunities: List of arbitrage opportunities
            
        Returns:
            TradingSignal or None if no signal generated
        """
        # Check if we have sufficient confidence
        if summary.confidence < self.min_confidence:
            logger.debug(
                f"Insufficient confidence for signal: {summary.confidence:.2f} < {self.min_confidence}"
            )
            return None
        
        # Check for arbitrage opportunities first (highest priority)
        if opportunities:
            best_opportunity = max(opportunities, key=lambda x: x.confidence * x.expected_profit)
            
            if best_opportunity.expected_profit > 0.5:  # 0.5% minimum profit
                signal = TradingSignal(
                    symbol=summary.symbol,
                    signal_type="buy",
                    confidence=best_opportunity.confidence,
                    timestamp=time.time(),
                    reason=f"Arbitrage opportunity detected: {best_opportunity.opportunity_type}",
                    indicators={
                        "expected_profit": best_opportunity.expected_profit,
                        "opportunity_type": best_opportunity.opportunity_type
                    },
                    risk_level=self._assess_risk_level(best_opportunity),
                    expected_return=best_opportunity.expected_profit,
                    stop_loss=best_opportunity.buy_price * 0.99,  # 1% stop loss
                    take_profit=best_opportunity.sell_price,
                    additional_data={
                        "opportunity_id": id(best_opportunity)
                    }
                )
                
                logger.info(
                    f"Generated BUY signal for {signal.symbol}: "
                    f"confidence={signal.confidence:.2f}, "
                    f"expected_return={signal.expected_return:.2f}%"
                )
                
                return signal
        
        # If no arbitrage, check for trend-based signals
        if summary.price_change_24h is not None:
            if summary.price_change_24h > 5.0:  # Strong upward trend
                signal = TradingSignal(
                    symbol=summary.symbol,
                    signal_type="buy",
                    confidence=min(0.9, summary.confidence),
                    timestamp=time.time(),
                    reason=f"Strong upward trend: {summary.price_change_24h:.2f}% change",
                    indicators={
                        "price_change_24h": summary.price_change_24h,
                        "volatility_24h": summary.volatility_24h
                    },
                    risk_level="medium",
                    expected_return=summary.price_change_24h,
                    stop_loss=summary.current_price * 0.95,
                    take_profit=summary.current_price * 1.10,
                    additional_data={}
                )
                
                logger.info(
                    f"Generated BUY signal for {signal.symbol} based on trend: "
                    f"change={summary.price_change_24h:.2f}%"
                )
                
                return signal
            
            elif summary.price_change_24h < -5.0:  # Strong downward trend
                signal = TradingSignal(
                    symbol=summary.symbol,
                    signal_type="sell",
                    confidence=min(0.9, summary.confidence),
                    timestamp=time.time(),
                    reason=f"Strong downward trend: {summary.price_change_24h:.2f}% change",
                    indicators={
                        "price_change_24h": summary.price_change_24h,
                        "volatility_24h": summary.volatility_24h
                    },
                    risk_level="medium",
                    expected_return=abs(summary.price_change_24h),
                    stop_loss=summary.current_price * 1.05,
                    take_profit=summary.current_price * 0.90,
                    additional_data={}
                )
                
                logger.info(
                    f"Generated SELL signal for {signal.symbol} based on trend: "
                    f"change={summary.price_change_24h:.2f}%"
                )
                
                return signal
        
        # No clear signal
        return None
    
    def _calculate_liquidity_risk(self, data_points: List[NormalizedMarketData]) -> float:
        """
        Calculate liquidity risk based on volume data.
        
        Args:
            data_points: List of normalized market data
            
        Returns:
            Liquidity risk score (0.0 to 1.0)
        """
        avg_volume = sum(data.volume for data in data_points) / len(data_points)
        
        if avg_volume < 100:
            return 0.8  # High risk
        elif avg_volume < 1000:
            return 0.5  # Medium risk
        else:
            return 0.2  # Low risk
    
    def _calculate_execution_risk(self, data_points: List[NormalizedMarketData]) -> float:
        """
        Calculate execution risk based on spread and volatility.
        
        Args:
            data_points: List of normalized market data
            
        Returns:
            Execution risk score (0.0 to 1.0)
        """
        avg_volatility = 0
        volatility_count = 0
        
        for data in data_points:
            if data.volatility_24h is not None:
                avg_volatility += data.volatility_24h
                volatility_count += 1
        
        if volatility_count > 0:
            avg_volatility /= volatility_count
        
        if avg_volatility > 10:
            return 0.7  # High risk
        elif avg_volatility > 5:
            return 0.4  # Medium risk
        else:
            return 0.2  # Low risk
    
    def _calculate_time_risk(self, data_points: List[NormalizedMarketData]) -> float:
        """
        Calculate time risk based on data freshness.
        
        Args:
            data_points: List of normalized market data
            
        Returns:
            Time risk score (0.0 to 1.0)
        """
        current_time = time.time()
        avg_age = sum(current_time - data.normalized_timestamp for data in data_points) / len(data_points)
        
        if avg_age > 60:
            return 0.6  # High risk
        elif avg_age > 30:
            return 0.3  # Medium risk
        else:
            return 0.1  # Low risk
    
    def _assess_risk_level(self, opportunity: ArbitrageOpportunity) -> str:
        """
        Assess overall risk level for an opportunity.
        
        Args:
            opportunity: Arbitrage opportunity
            
        Returns:
            Risk level: "low", "medium", or "high"
        """
        avg_risk = (
            opportunity.liquidity_risk +
            opportunity.execution_risk +
            opportunity.time_risk
        ) / 3
        
        if avg_risk < 0.3:
            return "low"
        elif avg_risk < 0.6:
            return "medium"
        else:
            return "high"
    
    def store_price_point(self, symbol: str, price: float, timestamp: float):
        """
        Store a price point for historical analysis.
        
        Args:
            symbol: Normalized symbol
            price: Price
            timestamp: Timestamp
        """
        self._price_history[symbol].append((timestamp, price))
        
        # Keep only recent history
        if len(self._price_history[symbol]) > self._max_history_length:
            self._price_history[symbol].pop(0)
    
    def get_price_history(self, symbol: str, limit: int = 100) -> List[Tuple[float, float]]:
        """
        Get price history for a symbol.
        
        Args:
            symbol: Normalized symbol
            limit: Maximum number of points to return
            
        Returns:
            List of (timestamp, price) tuples
        """
        history = self._price_history.get(symbol, [])
        return history[-limit:] if history else []
