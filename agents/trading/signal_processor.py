"""
SAI Protocol — Signal Processor
--------------------------------
Signal processing and technical analysis for trading decisions.

Provides:
  - Technical indicators (RSI, MACD, moving averages)
  - Volume analysis
  - Liquidity assessment
  - Slippage estimation
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import statistics

from .market_data_feed import MarketData, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class TechnicalIndicators:
    """Technical indicator values."""
    rsi: Optional[float]  # Relative Strength Index
    macd: Optional[float]  # MACD line
    macd_signal: Optional[float]  # MACD signal line
    macd_histogram: Optional[float]  # MACD histogram
    sma_20: Optional[float]  # 20-period Simple Moving Average
    sma_50: Optional[float]  # 50-period Simple Moving Average
    ema_12: Optional[float]  # 12-period Exponential Moving Average
    ema_26: Optional[float]  # 26-period Exponential Moving Average
    bollinger_upper: Optional[float]  # Upper Bollinger Band
    bollinger_lower: Optional[float]  # Lower Bollinger Band
    bollinger_middle: Optional[float]  # Middle Bollinger Band (SMA)
    
    # Trend indicators
    adx: Optional[float]  # Average Directional Index
    plus_di: Optional[float]  # Plus Directional Indicator
    minus_di: Optional[float]  # Minus Directional Indicator


@dataclass
class VolumeAnalysis:
    """Volume analysis results."""
    current_volume: float
    avg_volume_20: float
    volume_ratio: float  # Current volume / average volume
    volume_trend: str  # "increasing", "decreasing", "neutral"
    volume_spike: bool  # True if volume is significantly higher than average
    liquidity_score: float  # 0.0 to 1.0


@dataclass
class LiquidityAssessment:
    """Liquidity assessment results."""
    bid_ask_spread: float
    spread_pct: float
    order_book_depth: int
    bid_volume: float
    ask_volume: float
    total_volume: float
    liquidity_score: float  # 0.0 to 1.0
    slippage_estimate: float  # Estimated slippage percentage
    execution_time_estimate: float  # Estimated execution time in seconds


class TechnicalIndicatorCalculator:
    """Calculator for technical indicators."""
    
    def __init__(self, period: int = 14):
        """
        Initialize technical indicator calculator.
        
        Args:
            period: Default period for indicators
        """
        self.period = period
        self.price_history: deque = deque(maxlen=100)
        self.volume_history: deque = deque(maxlen=100)
    
    def add_data_point(self, price: float, volume: float = 0.0):
        """
        Add a new data point.
        
        Args:
            price: Current price
            volume: Current volume
        """
        self.price_history.append(price)
        self.volume_history.append(volume)
    
    def calculate_rsi(self, period: Optional[int] = None) -> Optional[float]:
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            period: RSI period (default: 14)
            
        Returns:
            RSI value or None if insufficient data
        """
        period = period or self.period
        
        if len(self.price_history) < period + 1:
            return None
        
        prices = list(self.price_history)[-period-1:]
        
        # Calculate price changes
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        # Calculate average gains and losses
        avg_gain = statistics.mean(gains) if gains else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return rsi
    
    def calculate_macd(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line EMA period
            
        Returns:
            Tuple of (MACD, signal, histogram)
        """
        if len(self.price_history) < slow_period + signal_period:
            return None, None, None
        
        prices = list(self.price_history)
        
        # Calculate EMAs
        ema_fast = self._calculate_ema(prices, fast_period)
        ema_slow = self._calculate_ema(prices, slow_period)
        
        if ema_fast is None or ema_slow is None:
            return None, None, None
        
        macd = ema_fast - ema_slow
        
        # Calculate signal line (EMA of MACD)
        # For simplicity, we'll use the current MACD as the signal
        # In a full implementation, you'd track MACD history
        signal = macd * 0.9  # Simplified
        histogram = macd - signal
        
        return macd, signal, histogram
    
    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """
        Calculate Exponential Moving Average.
        
        Args:
            prices: List of prices
            period: EMA period
            
        Returns:
            EMA value or None if insufficient data
        """
        if len(prices) < period:
            return None
        
        multiplier = 2.0 / (period + 1.0)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1.0 - multiplier))
        
        return ema
    
    def calculate_sma(self, period: int) -> Optional[float]:
        """
        Calculate Simple Moving Average.
        
        Args:
            period: SMA period
            
        Returns:
            SMA value or None if insufficient data
        """
        if len(self.price_history) < period:
            return None
        
        prices = list(self.price_history)[-period:]
        return statistics.mean(prices)
    
    def calculate_bollinger_bands(
        self,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Calculate Bollinger Bands.
        
        Args:
            period: Period for middle band (SMA)
            std_dev: Standard deviation multiplier
            
        Returns:
            Tuple of (upper, middle, lower) bands
        """
        if len(self.price_history) < period:
            return None, None, None
        
        prices = list(self.price_history)[-period:]
        middle = statistics.mean(prices)
        std = statistics.stdev(prices) if len(prices) > 1 else 0.0
        
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        
        return upper, middle, lower
    
    def calculate_all_indicators(self) -> TechnicalIndicators:
        """
        Calculate all technical indicators.
        
        Returns:
            TechnicalIndicators object
        """
        rsi = self.calculate_rsi()
        macd, macd_signal, macd_histogram = self.calculate_macd()
        sma_20 = self.calculate_sma(20)
        sma_50 = self.calculate_sma(50)
        bollinger_upper, bollinger_middle, bollinger_lower = self.calculate_bollinger_bands()
        
        return TechnicalIndicators(
            rsi=rsi,
            macd=macd,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            sma_20=sma_20,
            sma_50=sma_50,
            ema_12=None,  # Would need separate calculation
            ema_26=None,  # Would need separate calculation
            bollinger_upper=bollinger_upper,
            bollinger_lower=bollinger_lower,
            bollinger_middle=bollinger_middle,
            adx=None,  # Requires more complex calculation
            plus_di=None,
            minus_di=None
        )


class VolumeAnalyzer:
    """Analyzer for volume data."""
    
    def __init__(self, period: int = 20):
        """
        Initialize volume analyzer.
        
        Args:
            period: Period for average volume calculation
        """
        self.period = period
        self.volume_history: deque = deque(maxlen=100)
    
    def add_volume(self, volume: float):
        """
        Add a new volume data point.
        
        Args:
            volume: Volume value
        """
        self.volume_history.append(volume)
    
    def analyze_volume(self) -> VolumeAnalysis:
        """
        Analyze current volume.
        
        Returns:
            VolumeAnalysis object
        """
        if not self.volume_history:
            return VolumeAnalysis(
                current_volume=0.0,
                avg_volume_20=0.0,
                volume_ratio=0.0,
                volume_trend="neutral",
                volume_spike=False,
                liquidity_score=0.0
            )
        
        current_volume = self.volume_history[-1]
        
        # Calculate average volume
        if len(self.volume_history) >= self.period:
            avg_volume = statistics.mean(list(self.volume_history)[-self.period:])
        else:
            avg_volume = statistics.mean(list(self.volume_history))
        
        # Calculate volume ratio
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0.0
        
        # Determine volume trend
        if len(self.volume_history) >= 5:
            recent_avg = statistics.mean(list(self.volume_history)[-5:])
            older_avg = statistics.mean(list(self.volume_history)[:-5]) if len(self.volume_history) > 5 else avg_volume
            
            if recent_avg > older_avg * 1.1:
                volume_trend = "increasing"
            elif recent_avg < older_avg * 0.9:
                volume_trend = "decreasing"
            else:
                volume_trend = "neutral"
        else:
            volume_trend = "neutral"
        
        # Check for volume spike
        volume_spike = volume_ratio > 2.0  # More than 2x average
        
        # Calculate liquidity score based on volume
        liquidity_score = min(1.0, volume_ratio / 3.0)  # Cap at 3x average
        
        return VolumeAnalysis(
            current_volume=current_volume,
            avg_volume_20=avg_volume,
            volume_ratio=volume_ratio,
            volume_trend=volume_trend,
            volume_spike=volume_spike,
            liquidity_score=liquidity_score
        )


class LiquidityAssessor:
    """Assessor for market liquidity."""
    
    def assess_liquidity(self, order_book: OrderBook) -> LiquidityAssessment:
        """
        Assess liquidity from order book.
        
        Args:
            order_book: Order book data
            
        Returns:
            LiquidityAssessment object
        """
        if not order_book.bids or not order_book.asks:
            return LiquidityAssessment(
                bid_ask_spread=0.0,
                spread_pct=0.0,
                order_book_depth=0,
                bid_volume=0.0,
                ask_volume=0.0,
                total_volume=0.0,
                liquidity_score=0.0,
                slippage_estimate=0.0,
                execution_time_estimate=0.0
            )
        
        # Calculate spread
        best_bid = order_book.bids[0][0]
        best_ask = order_book.asks[0][0]
        spread = best_ask - best_bid
        spread_pct = (spread / best_ask) * 100 if best_ask > 0 else 0.0
        
        # Calculate order book depth
        order_book_depth = len(order_book.bids) + len(order_book.asks)
        
        # Calculate volumes
        bid_volume = sum(bid[1] for bid in order_book.bids)
        ask_volume = sum(ask[1] for ask in order_book.asks)
        total_volume = bid_volume + ask_volume
        
        # Calculate liquidity score
        liquidity_score = self._calculate_liquidity_score(
            spread_pct, order_book_depth, total_volume
        )
        
        # Estimate slippage
        slippage_estimate = self._estimate_slippage(spread_pct, total_volume)
        
        # Estimate execution time
        execution_time_estimate = self._estimate_execution_time(
            order_book_depth, total_volume
        )
        
        return LiquidityAssessment(
            bid_ask_spread=spread,
            spread_pct=spread_pct,
            order_book_depth=order_book_depth,
            bid_volume=bid_volume,
            ask_volume=ask_volume,
            total_volume=total_volume,
            liquidity_score=liquidity_score,
            slippage_estimate=slippage_estimate,
            execution_time_estimate=execution_time_estimate
        )
    
    def _calculate_liquidity_score(
        self,
        spread_pct: float,
        order_book_depth: int,
        total_volume: float
    ) -> float:
        """
        Calculate overall liquidity score.
        
        Args:
            spread_pct: Bid-ask spread percentage
            order_book_depth: Order book depth
            total_volume: Total volume in order book
            
        Returns:
            Liquidity score between 0.0 and 1.0
        """
        score = 1.0
        
        # Penalize wide spreads
        if spread_pct > 0.1:  # 0.1%
            score -= 0.3
        elif spread_pct > 0.05:  # 0.05%
            score -= 0.1
        
        # Penalize shallow order books
        if order_book_depth < 10:
            score -= 0.4
        elif order_book_depth < 20:
            score -= 0.2
        
        # Penalize low volume
        if total_volume < 100:
            score -= 0.3
        elif total_volume < 1000:
            score -= 0.1
        
        return max(0.0, min(1.0, score))
    
    def _estimate_slippage(
        self,
        spread_pct: float,
        total_volume: float
    ) -> float:
        """
        Estimate slippage percentage.
        
        Args:
            spread_pct: Bid-ask spread percentage
            total_volume: Total volume in order book
            
        Returns:
            Estimated slippage percentage
        """
        # Base slippage from spread
        slippage = spread_pct / 2.0
        
        # Additional slippage for low liquidity
        if total_volume < 100:
            slippage += 0.1  # Add 0.1% for low liquidity
        elif total_volume < 1000:
            slippage += 0.05  # Add 0.05% for medium liquidity
        
        return min(1.0, slippage)  # Cap at 1%
    
    def _estimate_execution_time(
        self,
        order_book_depth: int,
        total_volume: float
    ) -> float:
        """
        Estimate execution time in seconds.
        
        Args:
            order_book_depth: Order book depth
            total_volume: Total volume in order book
            
        Returns:
            Estimated execution time in seconds
        """
        # Base time on order book depth
        base_time = 1.0  # 1 second base
        
        # Adjust for depth
        if order_book_depth < 10:
            base_time += 2.0  # Slower for shallow books
        elif order_book_depth > 50:
            base_time -= 0.5  # Faster for deep books
        
        # Adjust for volume
        if total_volume > 10000:
            base_time -= 0.5  # Faster for high volume
        
        return max(0.5, base_time)  # Minimum 0.5 seconds


class SignalProcessor:
    """
    Main signal processor combining all analysis components.
    
    Processes market data to generate technical signals for strategy decisions.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize signal processor.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.indicator_calculator = TechnicalIndicatorCalculator(period=14)
        self.volume_analyzer = VolumeAnalyzer(period=20)
        self.liquidity_assessor = LiquidityAssessor()
        
        logger.info("Signal processor initialized")
    
    def process_market_data(
        self,
        market_data: MarketData,
        order_book: Optional[OrderBook] = None
    ) -> Dict[str, Any]:
        """
        Process market data and generate signals.
        
        Args:
            market_data: Market data point
            order_book: Optional order book data
            
        Returns:
            Dictionary containing all processed signals
        """
        # Add data point to calculators
        self.indicator_calculator.add_data_point(market_data.price, market_data.volume)
        self.volume_analyzer.add_volume(market_data.volume)
        
        # Calculate technical indicators
        indicators = self.indicator_calculator.calculate_all_indicators()
        
        # Analyze volume
        volume_analysis = self.volume_analyzer.analyze_volume()
        
        # Assess liquidity if order book is available
        liquidity_assessment = None
        if order_book:
            liquidity_assessment = self.liquidity_assessor.assess_liquidity(order_book)
        
        # Generate trading signals from indicators
        signals = self._generate_signals(indicators, volume_analysis, liquidity_assessment)
        
        return {
            "indicators": indicators,
            "volume_analysis": volume_analysis,
            "liquidity_assessment": liquidity_assessment,
            "signals": signals,
            "timestamp": time.time()
        }
    
    def _generate_signals(
        self,
        indicators: TechnicalIndicators,
        volume_analysis: VolumeAnalysis,
        liquidity_assessment: Optional[LiquidityAssessment]
    ) -> Dict[str, Any]:
        """
        Generate trading signals from analysis.
        
        Args:
            indicators: Technical indicators
            volume_analysis: Volume analysis
            liquidity_assessment: Liquidity assessment
            
        Returns:
            Dictionary of trading signals
        """
        signals = {
            "overall_sentiment": "neutral",
            "trend": "neutral",
            "momentum": "neutral",
            "strength": 0.0
        }
        
        # RSI signal
        if indicators.rsi:
            if indicators.rsi > 70:
                signals["momentum"] = "overbought"
            elif indicators.rsi < 30:
                signals["momentum"] = "oversold"
        
        # MACD signal
        if indicators.macd and indicators.macd_signal:
            if indicators.macd > indicators.macd_signal:
                signals["trend"] = "bullish"
            else:
                signals["trend"] = "bearish"
        
        # Moving average signal
        if indicators.sma_20 and indicators.sma_50:
            if indicators.sma_20 > indicators.sma_50:
                signals["trend"] = "bullish"
            else:
                signals["trend"] = "bearish"
        
        # Volume confirmation
        if volume_analysis.volume_spike:
            signals["strength"] = 0.8
        else:
            signals["strength"] = 0.5
        
        # Liquidity adjustment
        if liquidity_assessment:
            if liquidity_assessment.liquidity_score < 0.3:
                signals["strength"] *= 0.5  # Reduce strength for low liquidity
        
        # Overall sentiment
        bullish_signals = sum(
            1 for s in [signals["trend"], signals["momentum"]]
            if s in ["bullish", "oversold"]
        )
        bearish_signals = sum(
            1 for s in [signals["trend"], signals["momentum"]]
            if s in ["bearish", "overbought"]
        )
        
        if bullish_signals > bearish_signals:
            signals["overall_sentiment"] = "bullish"
        elif bearish_signals > bullish_signals:
            signals["overall_sentiment"] = "bearish"
        
        return signals
    
    def reset(self):
        """Reset all calculators."""
        self.indicator_calculator = TechnicalIndicatorCalculator(period=14)
        self.volume_analyzer = VolumeAnalyzer(period=20)
        logger.info("Signal processor reset")
