"""
SAI Protocol — Market Data Pipeline Test
---------------------------------------
End-to-end test for the market data pipeline.

Tests:
  - CEX feed initialization and data fetching
  - Data normalization
  - Market signal generation
  - Integration with trading agent
"""

import os
import sys
import logging
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Import modules directly to avoid loading trading_agent which requires env vars
from agents.trading import market_data_feed
from agents.trading import data_normalizer
from agents.trading import market_signal

CEXFeed = market_data_feed.CEXFeed
FallbackFeed = market_data_feed.FallbackFeed
PolymarketFeed = market_data_feed.PolymarketFeed
DataNormalizer = data_normalizer.DataNormalizer
MarketSignalGenerator = market_signal.MarketSignalGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


def test_cex_feed():
    """Test CEX feed initialization and data fetching."""
    logger.info("=" * 60)
    logger.info("TEST 1: CEX Feed")
    logger.info("=" * 60)
    
    try:
        # Initialize Coinbase feed
        feed = CEXFeed(exchange="coinbase", timeout=10)
        logger.info("✓ CEX feed initialized")
        
        # Test fetching price for BTC-USD
        logger.info("Fetching BTC-USD price...")
        price_data = feed.get_price("BTC-USD")
        
        if price_data:
            logger.info(f"✓ Price fetched: {price_data.price}")
            logger.info(f"  Source: {price_data.source}")
            logger.info(f"  Quality score: {price_data.quality_score}")
            logger.info(f"  Timestamp: {price_data.timestamp}")
        else:
            logger.error("✗ Failed to fetch price")
            return False
        
        # Test fetching order book
        logger.info("Fetching BTC-USD order book...")
        order_book = feed.get_order_book("BTC-USD", depth=5)
        
        if order_book:
            logger.info(f"✓ Order book fetched: {len(order_book.bids)} bids, {len(order_book.asks)} asks")
            if order_book.bids:
                logger.info(f"  Best bid: {order_book.bids[0][0]}")
            if order_book.asks:
                logger.info(f"  Best ask: {order_book.asks[0][0]}")
        else:
            logger.warning("⚠ Order book not available (may be expected)")
        
        # Test health check
        logger.info(f"Feed healthy: {feed.is_healthy()}")
        
        logger.info("✓ CEX feed test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ CEX feed test FAILED: {e}", exc_info=True)
        return False


def test_data_normalizer():
    """Test data normalization."""
    logger.info("=" * 60)
    logger.info("TEST 2: Data Normalizer")
    logger.info("=" * 60)
    
    try:
        # Initialize normalizer
        normalizer = DataNormalizer()
        logger.info("✓ Data normalizer initialized")
        
        # Initialize feed
        feed = CEXFeed(exchange="coinbase", timeout=10)
        
        # Fetch data
        price_data = feed.get_price("BTC-USD")
        if not price_data:
            logger.error("✗ Failed to fetch data for normalization test")
            return False
        
        # Normalize data
        logger.info("Normalizing market data...")
        normalized = normalizer.normalize_market_data(price_data)
        
        if normalized:
            logger.info(f"✓ Data normalized")
            logger.info(f"  Original symbol: {price_data.symbol}")
            logger.info(f"  Normalized symbol: {normalized.normalized_symbol}")
            logger.info(f"  Normalized price: {normalized.price}")
            logger.info(f"  Confidence: {normalized.confidence}")
            logger.info(f"  Quality score: {normalized.quality_score}")
        else:
            logger.error("✗ Failed to normalize data")
            return False
        
        # Test order book normalization
        order_book = feed.get_order_book("BTC-USD", depth=5)
        if order_book:
            logger.info("Normalizing order book...")
            normalized_ob = normalizer.normalize_order_book(order_book)
            
            if normalized_ob:
                logger.info(f"✓ Order book normalized")
                logger.info(f"  Spread: {normalized_ob.spread}")
                logger.info(f"  Mid price: {normalized_ob.mid_price}")
            else:
                logger.error("✗ Failed to normalize order book")
                return False
        
        logger.info("✓ Data normalizer test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Data normalizer test FAILED: {e}", exc_info=True)
        return False


def test_market_signal_generator():
    """Test market signal generation."""
    logger.info("=" * 60)
    logger.info("TEST 3: Market Signal Generator")
    logger.info("=" * 60)
    
    try:
        # Initialize components
        normalizer = DataNormalizer()
        signal_generator = MarketSignalGenerator(normalizer)
        feed = CEXFeed(exchange="coinbase", timeout=10)
        
        logger.info("✓ Components initialized")
        
        # Fetch data for multiple symbols
        logger.info("Fetching data for multiple symbols...")
        symbols = ["BTC-USD", "ETH-USD"]
        market_data_list = []
        
        for symbol in symbols:
            data = feed.get_price(symbol)
            if data:
                market_data_list.append(data)
                logger.info(f"  ✓ {symbol}: {data.price}")
        
        if len(market_data_list) < 2:
            logger.warning("⚠ Only fetched data for one symbol, arbitrage detection limited")
        
        # Generate market summary
        logger.info("Generating market summary...")
        summary = signal_generator.generate_market_summary(market_data_list)
        
        if summary:
            logger.info(f"✓ Market summary generated")
            logger.info(f"  Symbol: {summary.symbol}")
            logger.info(f"  Current price: {summary.current_price}")
            logger.info(f"  Volume: {summary.volume}")
            logger.info(f"  Confidence: {summary.confidence}")
            logger.info(f"  Sources used: {summary.sources_used}")
        else:
            logger.error("✗ Failed to generate market summary")
            return False
        
        # Detect arbitrage opportunities
        logger.info("Detecting arbitrage opportunities...")
        opportunities = signal_generator.detect_arbitrage_opportunities(market_data_list)
        
        logger.info(f"✓ Detected {len(opportunities)} opportunities")
        for opp in opportunities:
            logger.info(f"  - {opp.symbol}: {opp.opportunity_type}, profit={opp.expected_profit:.2f}%")
        
        # Generate trading signal
        logger.info("Generating trading signal...")
        signal = signal_generator.generate_trading_signal(summary, opportunities)
        
        if signal:
            logger.info(f"✓ Trading signal generated")
            logger.info(f"  Type: {signal.signal_type}")
            logger.info(f"  Confidence: {signal.confidence}")
            logger.info(f"  Reason: {signal.reason}")
            logger.info(f"  Risk level: {signal.risk_level}")
        else:
            logger.info("⚠ No trading signal generated (expected if no clear opportunity)")
        
        logger.info("✓ Market signal generator test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Market signal generator test FAILED: {e}", exc_info=True)
        return False


def test_fallback_feed():
    """Test fallback feed mechanism."""
    logger.info("=" * 60)
    logger.info("TEST 4: Fallback Feed")
    logger.info("=" * 60)
    
    try:
        # Initialize multiple feeds
        coinbase_feed = CEXFeed(exchange="coinbase", timeout=10)
        binance_feed = CEXFeed(exchange="binance", timeout=10)
        
        # Create fallback feed
        fallback = FallbackFeed([coinbase_feed, binance_feed])
        logger.info("✓ Fallback feed initialized with 2 sources")
        
        # Check feed status
        status = fallback.get_feed_status()
        logger.info(f"Feed status: {status}")
        
        # Fetch price using fallback
        logger.info("Fetching price using fallback...")
        price_data = fallback.get_price("BTC-USD")
        
        if price_data:
            logger.info(f"✓ Price fetched via fallback: {price_data.price}")
            logger.info(f"  Source: {price_data.source}")
            logger.info(f"  Last successful feed: {fallback._last_successful_feed}")
        else:
            logger.error("✗ Failed to fetch price via fallback")
            return False
        
        logger.info("✓ Fallback feed test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Fallback feed test FAILED: {e}", exc_info=True)
        return False


def test_integration():
    """Test full pipeline integration."""
    logger.info("=" * 60)
    logger.info("TEST 5: Full Pipeline Integration")
    logger.info("=" * 60)
    
    try:
        # This test would require a full TradingAgent setup
        # For now, we'll test the pipeline components together
        
        normalizer = DataNormalizer()
        signal_generator = MarketSignalGenerator(normalizer)
        coinbase_feed = CEXFeed(exchange="coinbase", timeout=10)
        binance_feed = CEXFeed(exchange="binance", timeout=10)
        fallback = FallbackFeed([coinbase_feed, binance_feed])
        
        logger.info("✓ All components initialized")
        
        # Fetch data
        symbols = ["BTC-USD", "ETH-USD"]
        market_data_list = []
        
        for symbol in symbols:
            data = fallback.get_price(symbol)
            if data:
                market_data_list.append(data)
        
        if not market_data_list:
            logger.error("✗ No data fetched")
            return False
        
        logger.info(f"✓ Fetched data for {len(market_data_list)} symbols")
        
        # Normalize
        normalized_list = [normalizer.normalize_market_data(data) for data in market_data_list]
        logger.info(f"✓ Normalized {len(normalized_list)} data points")
        
        # Generate summary
        summary = signal_generator.generate_market_summary(market_data_list)
        if not summary:
            logger.error("✗ Failed to generate summary")
            return False
        
        logger.info(f"✓ Summary generated for {summary.symbol}")
        
        # Detect opportunities
        opportunities = signal_generator.detect_arbitrage_opportunities(market_data_list)
        logger.info(f"✓ Detected {len(opportunities)} opportunities")
        
        # Generate signal
        signal = signal_generator.generate_trading_signal(summary, opportunities)
        logger.info(f"✓ Signal generated: {signal.signal_type if signal else 'hold'}")
        
        logger.info("✓ Full pipeline integration test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Full pipeline integration test FAILED: {e}", exc_info=True)
        return False


def test_polymarket_feed():
    """Test Polymarket feed with real CLOB API."""
    logger.info("=" * 60)
    logger.info("TEST 6: Polymarket Feed (Real API)")
    logger.info("=" * 60)
    
    try:
        # Initialize Polymarket feed
        polymarket_feed = PolymarketFeed(timeout=10)
        logger.info("✓ Polymarket feed initialized")
        
        # Try to fetch active crypto markets first
        logger.info("Fetching active crypto markets...")
        markets = polymarket_feed.get_active_crypto_markets(limit=10)
        
        if markets and len(markets) > 0:
            logger.info(f"✓ Fetched {len(markets)} active crypto markets")
            for market in markets[:3]:  # Show first 3
                logger.info(f"  - {market.get('condition_id')}: {market.get('question')}")
            
            # Try to fetch price for the first market
            first_condition_id = markets[0].get("condition_id")
            if first_condition_id:
                logger.info(f"Fetching price for condition {first_condition_id}...")
                price_data = polymarket_feed.get_price(first_condition_id)
                
                if price_data:
                    logger.info(f"✓ Price fetched: {price_data.price:.4f}")
                    logger.info(f"  Implied probability: {price_data.additional_data.get('implied_probability'):.4f}")
                    logger.info(f"  Volume: {price_data.volume:.4f}")
                    logger.info(f"  Quality score: {price_data.quality_score}")
                else:
                    logger.warning("⚠ Failed to fetch price (may be expected if no liquidity)")
        else:
            logger.warning("⚠ No active crypto markets found (may be expected)")
        
        # Test health check
        logger.info(f"Feed healthy: {polymarket_feed.is_healthy()}")
        
        logger.info("✓ Polymarket feed test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"✗ Polymarket feed test FAILED: {e}", exc_info=True)
        return False


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("MARKET DATA PIPELINE TEST SUITE")
    logger.info("=" * 60)
    
    results = {}
    
    # Run tests
    results["CEX Feed"] = test_cex_feed()
    results["Data Normalizer"] = test_data_normalizer()
    results["Market Signal Generator"] = test_market_signal_generator()
    results["Fallback Feed"] = test_fallback_feed()
    results["Full Integration"] = test_integration()
    results["Polymarket Feed"] = test_polymarket_feed()
    
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
