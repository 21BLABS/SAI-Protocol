"""
SAI Protocol — Market Data Feed Abstraction Layer
-------------------------------------------------
Abstract base class and implementations for market data sources.

Provides:
  - Abstract base class for market data feeds
  - Polymarket data feed implementation
  - CEX ticker feed implementation (Coinbase/Binance)
  - Data validation and sanitization
  - Fallback mechanisms
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import deque
import threading
import requests

logger = logging.getLogger(__name__)


class GlobalRateLimiter:
    """
    Global rate limiter shared across all feed instances.
    
    Prevents rate limit bypass by creating multiple feed instances.
    Uses a singleton pattern to ensure all instances share the same rate limit state.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, max_requests: int = 100, time_window: float = 60.0):
        """
        Create or return the singleton instance.
        
        Args:
            max_requests: Maximum requests per time window
            time_window: Time window in seconds
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.max_requests = max_requests
                    cls._instance.time_window = time_window
                    cls._instance.requests = deque()
                    cls._instance._instance_lock = threading.Lock()
        return cls._instance
    
    def acquire(self) -> bool:
        """
        Attempt to acquire a global request token.
        
        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        with self._instance_lock:
            now = time.time()
            
            # Remove old requests outside the time window
            while self.requests and self.requests[0] <= now - self.time_window:
                self.requests.popleft()
            
            # Check if we can make a request
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            
            logger.warning(
                f"Global rate limit exceeded: {len(self.requests)}/{self.max_requests} "
                f"in last {self.time_window}s"
            )
            return False


@dataclass
class MarketData:
    """Normalized market data structure."""
    symbol: str
    price: float
    volume: float
    timestamp: float
    source: str
    quality_score: float  # 0.0 to 1.0
    additional_data: Dict[str, Any]


@dataclass
class OrderBook:
    """Order book data structure."""
    symbol: str
    bids: List[tuple[float, float]]  # (price, quantity)
    asks: List[tuple[float, float]]  # (price, quantity)
    timestamp: float
    source: str


class RateLimiter:
    """
    Token bucket rate limiter for API calls.
    
    Prevents excessive API calls to external services by enforcing
    a maximum number of requests per time window.
    """
    
    def __init__(self, max_requests: int, time_window: float, global_limiter: 'GlobalRateLimiter' = None):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed in time window
            time_window: Time window in seconds
            global_limiter: Optional global rate limiter for cross-instance limiting
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        self.lock = threading.Lock()
        self.global_limiter = global_limiter
    
    def acquire(self) -> bool:
        """
        Attempt to acquire a request token.
        
        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        # Check global rate limiter first if configured
        if self.global_limiter and not self.global_limiter.acquire():
            logger.debug("Global rate limit exceeded")
            return False
        
        with self.lock:
            now = time.time()
            
            # Remove old requests outside the time window
            while self.requests and self.requests[0] <= now - self.time_window:
                self.requests.popleft()
            
            # Check if we can make a request
            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            
            logger.warning(
                f"Rate limit exceeded: {len(self.requests)}/{self.max_requests} "
                f"in last {self.time_window}s"
            )
            return False
    
    def wait_for_token(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until a request token is available.
        
        Args:
            timeout: Maximum time to wait in seconds (None = wait indefinitely)
        
        Returns:
            True if token acquired, False if timeout reached
        """
        start_time = time.time()
        
        while True:
            if self.acquire():
                return True
            
            if timeout is not None and time.time() - start_time >= timeout:
                logger.warning(f"Rate limiter timeout after {timeout}s")
                return False
            
            # Sleep briefly before retrying
            time.sleep(0.1)


class MarketDataFeed(ABC):
    """
    Abstract base class for market data feeds.
    
    All market data sources must implement these methods:
    - get_price(): Fetch current price for a symbol
    - get_order_book(): Fetch order book for a symbol
    - get_volume(): Fetch trading volume for a symbol
    - is_healthy(): Check if the data source is operational
    """
    
    # Symbol-specific price ranges for validation (min_price, max_price)
    SYMBOL_PRICE_RANGES = {
        "BTC-USD": (1000.0, 200000.0),
        "ETH-USD": (50.0, 20000.0),
        "BTCUSDT": (1000.0, 200000.0),
        "ETHUSDT": (50.0, 20000.0),
    }
    
    # Maximum acceptable data age in seconds (stale data threshold)
    MAX_DATA_AGE_SECONDS = 60.0
    
    # Global rate limiter instance (shared across all feeds)
    _global_rate_limiter = None
    
    @classmethod
    def get_global_rate_limiter(cls) -> GlobalRateLimiter:
        """
        Get or create the global rate limiter instance.
        
        Returns:
            GlobalRateLimiter singleton instance
        """
        if cls._global_rate_limiter is None:
            cls._global_rate_limiter = GlobalRateLimiter(max_requests=100, time_window=60.0)
            logger.info("Global rate limiter initialized (100 requests per 60s)")
        return cls._global_rate_limiter
    
    def __init__(self, name: str, timeout: int = 10, rate_limit: Optional[tuple[int, float]] = None):
        """
        Initialize the market data feed.
        
        Args:
            name: Name of the data source
            timeout: Request timeout in seconds
            rate_limit: Optional tuple (max_requests, time_window) for rate limiting
        """
        self.name = name
        self.timeout = timeout
        self._last_error = None
        self._last_success_time = None
        self._failure_count = 0
        
        # Initialize rate limiter if specified
        if rate_limit:
            max_requests, time_window = rate_limit
            self.rate_limiter = RateLimiter(
                max_requests, 
                time_window,
                global_limiter=self.get_global_rate_limiter()
            )
            logger.info(f"{name}: Rate limiting enabled ({max_requests} requests per {time_window}s) with global limiter")
        else:
            self.rate_limiter = None
        
    @abstractmethod
    def get_price(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch current price for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD")
            
        Returns:
            MarketData object or None if fetch fails
        """
        pass
    
    @abstractmethod
    def get_order_book(self, symbol: str, depth: int = 10) -> Optional[OrderBook]:
        """
        Fetch order book for a symbol.
        
        Args:
            symbol: Trading pair symbol
            depth: Number of levels to fetch
            
        Returns:
            OrderBook object or None if fetch fails
        """
        pass
    
    @abstractmethod
    def get_volume(self, symbol: str) -> Optional[float]:
        """
        Fetch trading volume for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Volume or None if fetch fails
        """
        pass
    
    def is_healthy(self) -> bool:
        """
        Check if the data source is operational.
        
        Returns:
            True if healthy, False otherwise
        """
        # Consider unhealthy if:
        # - Failed more than 3 times in a row
        # - No successful fetch in the last 5 minutes
        if self._failure_count >= 3:
            return False
        
        if self._last_success_time:
            time_since_success = time.time() - self._last_success_time
            if time_since_success > 300:  # 5 minutes
                return False
        
        return True
    
    def _record_success(self):
        """Record a successful fetch."""
        self._failure_count = 0
        self._last_success_time = time.time()
        self._last_error = None
    
    def _record_failure(self, error: Exception):
        """Record a failed fetch."""
        self._failure_count += 1
        self._last_error = error
        logger.warning(f"{self.name} fetch failed (count={self._failure_count}): {error}")
    
    def _check_rate_limit(self) -> bool:
        """
        Check if request is allowed under rate limit.
        
        Returns:
            True if request allowed, False if rate limited
        """
        if self.rate_limiter is None:
            return True
        
        if not self.rate_limiter.acquire():
            logger.debug(f"{self.name}: Rate limited, skipping request")
            return False
        
        return True
    
    def _validate_price(self, price: float, symbol: str = None) -> bool:
        """
        Validate a price value with symbol-specific ranges.
        
        Args:
            price: Price to validate
            symbol: Optional symbol for symbol-specific validation
            
        Returns:
            True if valid, False otherwise
        """
        if price is None or price <= 0:
            logger.warning(f"Invalid price: {price} (must be positive)")
            return False
        if price > 1e12:  # Sanity check for extremely high prices
            logger.warning(f"Invalid price: {price} (exceeds maximum)")
            return False
        
        # Symbol-specific validation if symbol provided
        if symbol and symbol in self.SYMBOL_PRICE_RANGES:
            min_price, max_price = self.SYMBOL_PRICE_RANGES[symbol]
            if not (min_price <= price <= max_price):
                logger.warning(
                    f"Price {price} for {symbol} outside valid range "
                    f"[{min_price}, {max_price}]"
                )
                return False
        
        return True
    
    def _validate_timestamp(self, timestamp: float) -> bool:
        """
        Validate data timestamp to ensure data is not stale.
        
        Args:
            timestamp: Unix timestamp to validate
            
        Returns:
            True if timestamp is recent enough, False otherwise
        """
        if timestamp is None:
            logger.warning("Timestamp is None")
            return False
        
        current_time = time.time()
        data_age = current_time - timestamp
        
        if data_age > self.MAX_DATA_AGE_SECONDS:
            logger.warning(
                f"Data is stale: {data_age:.1f}s old "
                f"(max allowed: {self.MAX_DATA_AGE_SECONDS}s)"
            )
            return False
        
        if data_age < 0:
            logger.warning(f"Timestamp is in the future: {timestamp}")
            return False
        
        return True
    
    def _validate_volume(self, volume: float) -> bool:
        """
        Validate a volume value.
        
        Args:
            volume: Volume to validate
            
        Returns:
            True if valid, False otherwise
        """
        if volume is None or volume < 0:
            return False
        if volume > 1e18:  # Sanity check for extremely high volumes
            return False
        return True


class PolymarketFeed(MarketDataFeed):
    """
    Polymarket data feed implementation using the real CLOB API.
    
    Fetches prediction market data from Polymarket CLOB API at https://clob.polymarket.com
    Markets are identified by condition ID, not symbol strings.
    """
    
    def __init__(self, api_key: Optional[str] = None, timeout: int = 10):
        """
        Initialize Polymarket feed.
        
        Args:
            api_key: Optional API key for authenticated requests (not required for reads)
            timeout: Request timeout in seconds
        """
        super().__init__("Polymarket", timeout)
        self.api_key = api_key
        self.base_url = "https://clob.polymarket.com"  # Real CLOB API endpoint
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        })
        
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        
        # Cache for market condition IDs
        self._condition_cache: Dict[str, str] = {}
    
    def get_price(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch current price for a prediction market.
        
        Args:
            symbol: Market condition ID or token ID (Polymarket uses condition IDs)
            
        Returns:
            MarketData object or None if fetch fails
        """
        if not self._check_rate_limit():
            return None
        
        try:
            # Try to fetch order book for the condition
            url = f"{self.base_url}/markets/{symbol}/orderbook"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract YES token price from order book (best bid)
            # Polymarket CLOB returns order book with bids/asks
            bids = data.get("bids", [])
            if not bids:
                logger.warning(f"No bids found in Polymarket orderbook for {symbol}")
                return None
            
            # Best bid is the highest price someone is willing to pay
            best_bid = float(bids[0].get("price", 0))
            
            if not self._validate_price(best_bid, symbol):
                logger.warning(f"Invalid price from Polymarket for {symbol}: {best_bid}")
                return None
            
            # Calculate implied probability (price is in range 0-1 for YES tokens)
            implied_probability = best_bid
            
            # Calculate volume from order book
            volume = sum(float(bid.get("amount", 0)) for bid in bids)
            
            market_data = MarketData(
                symbol=symbol,
                price=implied_probability,  # Implied probability (0-1)
                volume=volume,
                timestamp=time.time(),
                source="Polymarket",
                quality_score=self._calculate_quality_score(data),
                additional_data={
                    "condition_id": symbol,
                    "market_type": "prediction",
                    "implied_probability": implied_probability,
                    "token_type": "YES",
                    "orderbook_depth": len(bids)
                }
            )
            
            self._record_success()
            return market_data
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Polymarket response for {symbol}: {e}")
            return None
    
    def get_order_book(self, symbol: str, depth: int = 10) -> Optional[OrderBook]:
        """
        Fetch order book for a prediction market.
        
        Args:
            symbol: Market condition ID
            depth: Number of levels to fetch
            
        Returns:
            OrderBook object or None if fetch fails
        """
        if not self._check_rate_limit():
            return None
        
        try:
            url = f"{self.base_url}/markets/{symbol}/orderbook"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            bids = [(float(bid["price"]), float(bid["amount"])) 
                   for bid in data.get("bids", [])[:depth]]
            asks = [(float(ask["price"]), float(ask["amount"])) 
                   for ask in data.get("asks", [])[:depth]]
            
            order_book = OrderBook(
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=time.time(),
                source="Polymarket"
            )
            
            self._record_success()
            return order_book
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Polymarket orderbook for {symbol}: {e}")
            return None
    
    def get_volume(self, symbol: str) -> Optional[float]:
        """
        Fetch trading volume for a prediction market.
        
        Args:
            symbol: Market condition ID
            
        Returns:
            Volume or None if fetch fails
        """
        if not self._check_rate_limit():
            return None
        
        try:
            url = f"{self.base_url}/markets/{symbol}/orderbook"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # Calculate volume from order book
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            volume = sum(float(bid.get("amount", 0)) for bid in bids) + \
                    sum(float(ask.get("amount", 0)) for ask in asks)
            
            if not self._validate_volume(volume):
                logger.warning(f"Invalid volume from Polymarket for {symbol}: {volume}")
                return None
            
            self._record_success()
            return volume
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Polymarket volume for {symbol}: {e}")
            return None
    
    def get_active_crypto_markets(self, limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch active crypto-related prediction markets.
        
        Args:
            limit: Maximum number of markets to return
            
        Returns:
            List of market metadata or None if fetch fails
        """
        try:
            response = self.session.get(
                f"{self.base_url}/markets",
                params={"active": "true", "closed": "false", "limit": limit},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            crypto_keywords = ["BTC", "ETH", "Bitcoin", "Ethereum", "crypto", "price"]
            markets = []
            
            for market in data.get("data", []):
                question = market.get("question", "").lower()
                if (any(keyword.lower() in question for keyword in crypto_keywords)
                        and not market.get("closed", True)
                        and market.get("accepting_orders", False)):
                    markets.append(market)
            
            return markets[:limit]
            
        except requests.RequestException as e:
            self._record_failure(e)
            logger.error(f"Failed to fetch Polymarket crypto markets: {e}")
            return None
    
    def _calculate_quality_score(self, data: Dict[str, Any]) -> float:
        """
        Calculate a quality score for the data.
        
        Args:
            data: Raw API response data
            
        Returns:
            Quality score between 0.0 and 1.0
        """
        score = 1.0
        
        # Reduce score if order book depth is low
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        total_depth = len(bids) + len(asks)
        
        if total_depth < 5:
            score -= 0.3
        elif total_depth < 10:
            score -= 0.1
        
        # Reduce score if spread is wide (for prediction markets, spread > 0.02 is wide)
        if bids and asks:
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            if best_ask > 0:
                spread = (best_ask - best_bid) / best_ask
                if spread > 0.02:
                    score -= 0.2
        
        # Ensure score is between 0 and 1
        return max(0.0, min(1.0, score))


class CEXFeed(MarketDataFeed):
    """
    CEX ticker feed implementation.
    
    Supports Coinbase and Binance APIs for reference pricing.
    """
    
    def __init__(self, exchange: str = "coinbase", timeout: int = 10):
        """
        Initialize CEX feed.
        
        Args:
            exchange: Either "coinbase" or "binance"
            timeout: Request timeout in seconds
        """
        super().__init__(f"CEX-{exchange}", timeout)
        self.exchange = exchange.lower()
        self.session = requests.Session()
        
        if self.exchange == "coinbase":
            self.base_url = "https://api.coinbase.com/v2"
        elif self.exchange == "binance":
            self.base_url = "https://api.binance.com"
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
    
    def get_price(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch current price for a trading pair.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC-USD" for Coinbase, "BTCUSDT" for Binance)
            
        Returns:
            MarketData object or None if fetch fails
        """
        if not self._check_rate_limit():
            return None
        
        try:
            if self.exchange == "coinbase":
                return self._get_coinbase_price(symbol)
            elif self.exchange == "binance":
                return self._get_binance_price(symbol)
        except Exception as e:
            self._record_failure(e)
            return None
    
    def _get_coinbase_price(self, symbol: str) -> Optional[MarketData]:
        """Fetch price from Coinbase API."""
        try:
            url = f"{self.base_url}/prices/{symbol}/spot"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            price = float(data["data"]["amount"])
            
            if not self._validate_price(price, symbol):
                logger.warning(f"Invalid price from Coinbase for {symbol}: {price}")
                return None
            
            market_data = MarketData(
                symbol=symbol,
                price=price,
                volume=0.0,  # Coinbase spot price doesn't include volume
                timestamp=time.time(),
                source="Coinbase",
                quality_score=0.95,  # Coinbase is generally high quality
                additional_data={
                    "currency": data["data"]["currency"]
                }
            )
            
            self._record_success()
            return market_data
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Coinbase response for {symbol}: {e}")
            return None
    
    def _get_binance_price(self, symbol: str) -> Optional[MarketData]:
        """Fetch price from Binance API."""
        try:
            url = f"{self.base_url}/api/v3/ticker/price"
            params = {"symbol": symbol}
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            price = float(data["price"])
            
            if not self._validate_price(price, symbol):
                logger.warning(f"Invalid price from Binance for {symbol}: {price}")
                return None
            
            market_data = MarketData(
                symbol=symbol,
                price=price,
                volume=0.0,
                timestamp=time.time(),
                source="Binance",
                quality_score=0.95,  # Binance is generally high quality
                additional_data={}
            )
            
            self._record_success()
            return market_data
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Binance response for {symbol}: {e}")
            return None
    
    def get_order_book(self, symbol: str, depth: int = 10) -> Optional[OrderBook]:
        """
        Fetch order book for a trading pair.
        
        Args:
            symbol: Trading pair symbol
            depth: Number of levels to fetch
            
        Returns:
            OrderBook object or None if fetch fails
        """
        if not self._check_rate_limit():
            return None
        
        try:
            if self.exchange == "coinbase":
                return self._get_coinbase_orderbook(symbol, depth)
            elif self.exchange == "binance":
                return self._get_binance_orderbook(symbol, depth)
        except Exception as e:
            self._record_failure(e)
            return None
    
    def _get_coinbase_orderbook(self, symbol: str, depth: int) -> Optional[OrderBook]:
        """Fetch order book from Coinbase API."""
        try:
            url = f"{self.base_url}/products/{symbol}/book?level={depth}"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            bids = [(float(bid[0]), float(bid[1])) for bid in data["bids"][:depth]]
            asks = [(float(ask[0]), float(ask[1])) for ask in data["asks"][:depth]]
            
            order_book = OrderBook(
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=time.time(),
                source="Coinbase"
            )
            
            self._record_success()
            return order_book
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Coinbase orderbook for {symbol}: {e}")
            return None
    
    def _get_binance_orderbook(self, symbol: str, depth: int) -> Optional[OrderBook]:
        """Fetch order book from Binance API."""
        try:
            url = f"{self.base_url}/api/v3/depth"
            params = {"symbol": symbol, "limit": depth}
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            bids = [(float(bid[0]), float(bid[1])) for bid in data["bids"][:depth]]
            asks = [(float(ask[0]), float(ask[1])) for ask in data["asks"][:depth]]
            
            order_book = OrderBook(
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=time.time(),
                source="Binance"
            )
            
            self._record_success()
            return order_book
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Binance orderbook for {symbol}: {e}")
            return None
    
    def get_volume(self, symbol: str) -> Optional[float]:
        """
        Fetch trading volume for a trading pair.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Volume or None if fetch fails
        """
        if not self._check_rate_limit():
            return None
        
        try:
            if self.exchange == "coinbase":
                return self._get_coinbase_volume(symbol)
            elif self.exchange == "binance":
                return self._get_binance_volume(symbol)
        except Exception as e:
            self._record_failure(e)
            return None
    
    def _get_coinbase_volume(self, symbol: str) -> Optional[float]:
        """Fetch volume from Coinbase API."""
        try:
            url = f"{self.base_url}/products/{symbol}/stats"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            volume = float(data["volume_24h"])
            
            if not self._validate_volume(volume):
                logger.warning(f"Invalid volume from Coinbase for {symbol}: {volume}")
                return None
            
            self._record_success()
            return volume
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Coinbase volume for {symbol}: {e}")
            return None
    
    def _get_binance_volume(self, symbol: str) -> Optional[float]:
        """Fetch volume from Binance API."""
        try:
            url = f"{self.base_url}/api/v3/ticker/24hr"
            params = {"symbol": symbol}
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            volume = float(data["volume"])
            
            if not self._validate_volume(volume):
                logger.warning(f"Invalid volume from Binance for {symbol}: {volume}")
                return None
            
            self._record_success()
            return volume
            
        except requests.RequestException as e:
            self._record_failure(e)
            return None
        except (ValueError, KeyError) as e:
            self._record_failure(e)
            logger.error(f"Failed to parse Binance volume for {symbol}: {e}")
            return None


class FallbackFeed(MarketDataFeed):
    """
    Fallback feed that tries multiple data sources in order.
    
    Implements the fallback mechanism for high availability.
    """
    
    def __init__(self, feeds: List[MarketDataFeed]):
        """
        Initialize fallback feed.
        
        Args:
            feeds: List of data sources to try in order
        """
        super().__init__("Fallback", timeout=10)
        self.feeds = feeds
        self._last_successful_feed = None
    
    def get_price(self, symbol: str) -> Optional[MarketData]:
        """
        Fetch price from the first available feed.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            MarketData object or None if all feeds fail
        """
        for feed in self.feeds:
            if not feed.is_healthy():
                logger.debug(f"Skipping unhealthy feed: {feed.name}")
                continue
            
            data = feed.get_price(symbol)
            if data:
                self._last_successful_feed = feed.name
                logger.debug(f"Successfully fetched price from {feed.name}")
                return data
        
        logger.error(f"All feeds failed to fetch price for {symbol}")
        return None
    
    def get_order_book(self, symbol: str, depth: int = 10) -> Optional[OrderBook]:
        """
        Fetch order book from the first available feed.
        
        Args:
            symbol: Trading pair symbol
            depth: Number of levels to fetch
            
        Returns:
            OrderBook object or None if all feeds fail
        """
        for feed in self.feeds:
            if not feed.is_healthy():
                continue
            
            data = feed.get_order_book(symbol, depth)
            if data:
                self._last_successful_feed = feed.name
                return data
        
        logger.error(f"All feeds failed to fetch order book for {symbol}")
        return None
    
    def get_volume(self, symbol: str) -> Optional[float]:
        """
        Fetch volume from the first available feed.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Volume or None if all feeds fail
        """
        for feed in self.feeds:
            if not feed.is_healthy():
                continue
            
            data = feed.get_volume(symbol)
            if data:
                self._last_successful_feed = feed.name
                return data
        
        logger.error(f"All feeds failed to fetch volume for {symbol}")
        return None
    
    def is_healthy(self) -> bool:
        """
        Check if at least one feed is healthy.
        
        Returns:
            True if at least one feed is healthy
        """
        return any(feed.is_healthy() for feed in self.feeds)
    
    def get_feed_status(self) -> Dict[str, bool]:
        """
        Get health status of all feeds.
        
        Returns:
            Dict mapping feed names to health status
        """
        return {feed.name: feed.is_healthy() for feed in self.feeds}
