"""
SAI Protocol — Data Normalization Layer
---------------------------------------
Normalizes market data from multiple sources into a consistent format.

Provides:
  - Data format standardization
  - Decimal precision handling
  - Timestamp synchronization
  - Data quality scoring
  - Cross-source validation
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

from .market_data_feed import MarketData, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class NormalizedMarketData:
    """Fully normalized market data structure."""
    symbol: str
    normalized_symbol: str  # Standardized symbol format
    price: float
    volume: float
    timestamp: float
    normalized_timestamp: float  # Synchronized timestamp
    source: str
    quality_score: float
    confidence: float  # Overall confidence in the data
    additional_data: Dict[str, Any] = field(default_factory=dict)
    sources_used: List[str] = field(default_factory=list)  # For merged data
    
    # Derived metrics
    price_change_24h: Optional[float] = None
    volume_change_24h: Optional[float] = None
    volatility_24h: Optional[float] = None


@dataclass
class NormalizedOrderBook:
    """Fully normalized order book structure."""
    symbol: str
    normalized_symbol: str
    bids: List[Tuple[float, float]]  # (price, quantity)
    asks: List[Tuple[float, float]]  # (price, quantity)
    timestamp: float
    normalized_timestamp: float
    source: str
    quality_score: float
    
    # Derived metrics
    spread: Optional[float] = None
    mid_price: Optional[float] = None
    bid_volume: Optional[float] = None
    ask_volume: Optional[float] = None


class DataNormalizer:
    """
    Normalizes market data from multiple sources.
    
    Ensures consistent formatting, handles precision differences,
    synchronizes timestamps, and calculates quality scores.
    """
    
    # Symbol mapping for different exchanges
    SYMBOL_MAPPINGS = {
        # Coinbase -> Standard
        "BTC-USD": "BTC/USD",
        "ETH-USD": "ETH/USD",
        "SOL-USD": "SOL/USD",
        
        # Binance -> Standard
        "BTCUSDT": "BTC/USDT",
        "ETHUSDT": "ETH/USDT",
        "SOLUSDT": "SOL/USDT",
        
        # Polymarket -> Standard
        # Polymarket uses token IDs, mapping would be dynamic
    }
    
    # Decimal precision for different asset classes
    PRICE_PRECISION = {
        "BTC": 2,  # Bitcoin: 2 decimal places
        "ETH": 2,  # Ethereum: 2 decimal places
        "SOL": 4,  # Solana: 4 decimal places
        "default": 8  # Default: 8 decimal places
    }
    
    def __init__(self, max_timestamp_drift: float = 5.0):
        """
        Initialize the data normalizer.
        
        Args:
            max_timestamp_drift: Maximum allowed timestamp drift in seconds
        """
        self.max_timestamp_drift = max_timestamp_drift
        self._price_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        self._max_history_length = 1000  # Keep last 1000 price points
        
    def normalize_market_data(self, data: MarketData) -> NormalizedMarketData:
        """
        Normalize market data from a single source.
        
        Args:
            data: Raw market data from a feed
            
        Returns:
            NormalizedMarketData object
        """
        # Normalize symbol
        normalized_symbol = self._normalize_symbol(data.symbol)
        
        # Normalize price precision
        normalized_price = self._normalize_price_precision(data.price, normalized_symbol)
        
        # Normalize volume
        normalized_volume = self._normalize_volume(data.volume)
        
        # Synchronize timestamp
        normalized_timestamp = self._synchronize_timestamp(data.timestamp)
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(data, normalized_timestamp)
        
        # Store in history for derived metrics
        self._store_price_history(normalized_symbol, normalized_price, normalized_timestamp)
        
        # Calculate derived metrics
        derived_metrics = self._calculate_derived_metrics(normalized_symbol)
        
        normalized_data = NormalizedMarketData(
            symbol=data.symbol,
            normalized_symbol=normalized_symbol,
            price=normalized_price,
            volume=normalized_volume,
            timestamp=data.timestamp,
            normalized_timestamp=normalized_timestamp,
            source=data.source,
            quality_score=data.quality_score,
            confidence=confidence,
            additional_data=data.additional_data,
            **derived_metrics
        )
        
        logger.debug(
            f"Normalized {data.symbol} -> {normalized_symbol}: "
            f"price={normalized_price}, confidence={confidence:.2f}"
        )
        
        return normalized_data
    
    def normalize_order_book(self, order_book: OrderBook) -> NormalizedOrderBook:
        """
        Normalize order book data.
        
        Args:
            order_book: Raw order book from a feed
            
        Returns:
            NormalizedOrderBook object
        """
        # Normalize symbol
        normalized_symbol = self._normalize_symbol(order_book.symbol)
        
        # Normalize precision for bids and asks
        normalized_bids = [
            (self._normalize_price_precision(price, normalized_symbol), quantity)
            for price, quantity in order_book.bids
        ]
        normalized_asks = [
            (self._normalize_price_precision(price, normalized_symbol), quantity)
            for price, quantity in order_book.asks
        ]
        
        # Synchronize timestamp
        normalized_timestamp = self._synchronize_timestamp(order_book.timestamp)
        
        # Calculate derived metrics
        spread, mid_price = self._calculate_spread(normalized_bids, normalized_asks)
        bid_volume = sum(quantity for _, quantity in normalized_bids)
        ask_volume = sum(quantity for _, quantity in normalized_asks)
        
        normalized_order_book = NormalizedOrderBook(
            symbol=order_book.symbol,
            normalized_symbol=normalized_symbol,
            bids=normalized_bids,
            asks=normalized_asks,
            timestamp=order_book.timestamp,
            normalized_timestamp=normalized_timestamp,
            source=order_book.source,
            quality_score=0.9,  # Order books are generally high quality
            spread=spread,
            mid_price=mid_price,
            bid_volume=bid_volume,
            ask_volume=ask_volume
        )
        
        logger.debug(
            f"Normalized order book for {order_book.symbol}: "
            f"spread={spread}, mid_price={mid_price}"
        )
        
        return normalized_order_book
    
    def merge_multiple_sources(
        self,
        data_list: List[MarketData]
    ) -> Optional[NormalizedMarketData]:
        """
        Merge and normalize data from multiple sources.
        
        Args:
            data_list: List of market data from different sources
            
        Returns:
            Merged NormalizedMarketData or None if no valid data
        """
        if not data_list:
            return None
        
        # Normalize all data points
        normalized_list = [self.normalize_market_data(data) for data in data_list]
        
        # Filter by quality and confidence
        valid_data = [
            data for data in normalized_list
            if data.quality_score >= 0.5 and data.confidence >= 0.5
        ]
        
        if not valid_data:
            logger.warning("No valid data points after quality filtering")
            return None
        
        # Group by normalized symbol
        symbol_groups = defaultdict(list)
        for data in valid_data:
            symbol_groups[data.normalized_symbol].append(data)
        
        # For now, assume we're dealing with a single symbol
        # In production, this would handle multiple symbols
        if len(symbol_groups) != 1:
            logger.warning(f"Expected single symbol, got {len(symbol_groups)}")
        
        # Merge data for the primary symbol
        primary_symbol = list(symbol_groups.keys())[0]
        symbol_data = symbol_groups[primary_symbol]
        
        # Weighted average by confidence
        total_weight = sum(data.confidence for data in symbol_data)
        if total_weight == 0:
            return None
        
        weighted_price = sum(
            data.price * data.confidence for data in symbol_data
        ) / total_weight
        
        weighted_volume = sum(
            data.volume * data.confidence for data in symbol_data
        ) / total_weight
        
        # Use the most recent timestamp
        latest_timestamp = max(data.normalized_timestamp for data in symbol_data)
        
        # Average quality score
        avg_quality = sum(data.quality_score for data in symbol_data) / len(symbol_data)
        
        # Combined confidence
        combined_confidence = min(1.0, total_weight / len(symbol_data))
        
        # Merge additional data
        merged_additional = {}
        for data in symbol_data:
            merged_additional.update(data.additional_data)
        
        merged_data = NormalizedMarketData(
            symbol=symbol_data[0].symbol,
            normalized_symbol=primary_symbol,
            price=weighted_price,
            volume=weighted_volume,
            timestamp=symbol_data[0].timestamp,
            normalized_timestamp=latest_timestamp,
            source="merged",
            quality_score=avg_quality,
            confidence=combined_confidence,
            additional_data=merged_additional,
            sources_used=[data.source for data in symbol_data]
        )
        
        logger.info(
            f"Merged data from {len(symbol_data)} sources for {primary_symbol}: "
            f"price={weighted_price:.4f}, confidence={combined_confidence:.2f}"
        )
        
        return merged_data
    
    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to standard format.
        
        Args:
            symbol: Raw symbol from source
            
        Returns:
            Normalized symbol
        """
        # Check if we have a mapping
        if symbol in self.SYMBOL_MAPPINGS:
            return self.SYMBOL_MAPPINGS[symbol]
        
        # If no mapping, try to infer the format
        # Convert common formats to standard
        if "-" in symbol:
            # Coinbase format: BTC-USD -> BTC/USD
            return symbol.replace("-", "/")
        elif symbol.endswith("USDT"):
            # Binance format: BTCUSDT -> BTC/USDT
            base = symbol[:-4]
            return f"{base}/USDT"
        elif symbol.endswith("USD"):
            # Binance format: BTCUSD -> BTC/USD
            base = symbol[:-3]
            return f"{base}/USD"
        
        # Return as-is if no pattern matches
        return symbol
    
    def _normalize_price_precision(self, price: float, symbol: str) -> float:
        """
        Normalize price to appropriate decimal precision.
        
        Args:
            price: Raw price
            symbol: Normalized symbol
            
        Returns:
            Price with normalized precision
        """
        # Extract base asset from symbol
        base_asset = symbol.split("/")[0] if "/" in symbol else symbol.split("-")[0]
        
        # Get precision for this asset
        precision = self.PRICE_PRECISION.get(base_asset, self.PRICE_PRECISION["default"])
        
        # Round to appropriate precision
        return round(price, precision)
    
    def _normalize_volume(self, volume: float) -> float:
        """
        Normalize volume to standard units.
        
        Args:
            volume: Raw volume
            
        Returns:
            Normalized volume
        """
        # For now, assume volume is already in base units
        # In production, this would handle different volume units
        return round(volume, 4)
    
    def _synchronize_timestamp(self, timestamp: float) -> float:
        """
        Synchronize timestamp to current time if drift is too high.
        
        Args:
            timestamp: Raw timestamp
            
        Returns:
            Synchronized timestamp
        """
        current_time = time.time()
        drift = abs(current_time - timestamp)
        
        if drift > self.max_timestamp_drift:
            logger.warning(
                f"Timestamp drift too high: {drift:.2f}s (max: {self.max_timestamp_drift}s). "
                f"Using current time instead."
            )
            return current_time
        
        return timestamp
    
    def _calculate_confidence(
        self,
        data: MarketData,
        normalized_timestamp: float
    ) -> float:
        """
        Calculate overall confidence in the data.
        
        Args:
            data: Market data
            normalized_timestamp: Synchronized timestamp
            
        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = 1.0
        
        # Factor in quality score
        confidence *= data.quality_score
        
        # Factor in timestamp freshness
        age = time.time() - normalized_timestamp
        if age > 30:  # More than 30 seconds old
            confidence *= 0.9
        if age > 60:  # More than 1 minute old
            confidence *= 0.8
        if age > 300:  # More than 5 minutes old
            confidence *= 0.5
        
        # Factor in volume (low volume = lower confidence)
        if data.volume > 0 and data.volume < 100:
            confidence *= 0.7
        
        return max(0.0, min(1.0, confidence))
    
    def _store_price_history(self, symbol: str, price: float, timestamp: float):
        """
        Store price point in history for derived metrics.
        
        Args:
            symbol: Normalized symbol
            price: Normalized price
            timestamp: Normalized timestamp
        """
        history = self._price_history[symbol]
        history.append((timestamp, price))
        
        # Keep only recent history
        if len(history) > self._max_history_length:
            history.pop(0)
    
    def _calculate_derived_metrics(self, symbol: str) -> Dict[str, Optional[float]]:
        """
        Calculate derived metrics from price history.
        
        Args:
            symbol: Normalized symbol
            
        Returns:
            Dict of derived metrics
        """
        history = self._price_history[symbol]
        
        if len(history) < 2:
            return {
                "price_change_24h": None,
                "volume_change_24h": None,
                "volatility_24h": None
            }
        
        # Calculate 24h change (using available data)
        current_time = time.time()
        twenty_four_hours_ago = current_time - 86400
        
        # Find price 24h ago
        price_24h_ago = None
        for timestamp, price in history:
            if timestamp <= twenty_four_hours_ago:
                price_24h_ago = price
                break
        
        if price_24h_ago is None:
            # Not enough history for 24h metrics
            return {
                "price_change_24h": None,
                "volume_change_24h": None,
                "volatility_24h": None
            }
        
        current_price = history[-1][1]
        price_change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
        
        # Calculate volatility (standard deviation of returns)
        if len(history) >= 10:
            returns = []
            for i in range(1, len(history)):
                prev_price = history[i-1][1]
                curr_price = history[i][1]
                if prev_price > 0:
                    returns.append((curr_price - prev_price) / prev_price)
            
            if returns:
                import statistics
                volatility_24h = statistics.stdev(returns) * 100
            else:
                volatility_24h = None
        else:
            volatility_24h = None
        
        return {
            "price_change_24h": price_change_24h,
            "volume_change_24h": None,  # Would need volume history
            "volatility_24h": volatility_24h
        }
    
    def _calculate_spread(
        self,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]]
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate spread and mid price from order book.
        
        Args:
            bids: List of (price, quantity) bids
            asks: List of (price, quantity) asks
            
        Returns:
            Tuple of (spread, mid_price)
        """
        if not bids or not bids[0] or not asks or not asks[0]:
            return None, None
        
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2
        
        return spread, mid_price
    
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
    
    def clear_history(self, symbol: Optional[str] = None):
        """
        Clear price history.
        
        Args:
            symbol: Specific symbol to clear, or None to clear all
        """
        if symbol:
            self._price_history[symbol].clear()
        else:
            self._price_history.clear()
