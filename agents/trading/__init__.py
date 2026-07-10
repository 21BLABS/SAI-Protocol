"""
SAI Protocol — Trading Agent Package
-----------------------------------
Autonomous trading agent with market data pipeline, strategy engine,
and trade execution capabilities.
"""

# Import market data components (no dependencies)
from .market_data_feed import (
    MarketDataFeed,
    MarketData,
    OrderBook,
    PolymarketFeed,
    CEXFeed,
    FallbackFeed
)
from .data_normalizer import (
    DataNormalizer,
    NormalizedMarketData,
    NormalizedOrderBook
)
from .market_signal import (
    MarketSignalGenerator,
    MarketSummary,
    ArbitrageOpportunity,
    TradingSignal
)

# Import strategy engine components
from .strategy_engine import (
    BaseStrategy,
    StrategyDecision,
    StrategyType,
    ArbitrageStrategy,
    TrendFollowingStrategy,
    StrategySelector
)
from .risk_manager import (
    RiskManager,
    Position,
    RiskMetrics,
    RiskLevel
)
from .signal_processor import (
    SignalProcessor,
    TechnicalIndicatorCalculator,
    VolumeAnalyzer,
    LiquidityAssessor,
    TechnicalIndicators,
    VolumeAnalysis,
    LiquidityAssessment
)
from .decision_engine import (
    DecisionEngine,
    FinalDecision,
    DecisionAction
)

# Import trade encoder components
from .trade_encoder import (
    PolymarketTradeEncoder,
    UserOperationEncoder,
    TradeParams,
    EncodedTrade,
    TokenType,
    OrderSide
)
from .trade_executor import (
    TradeExecutor,
    BundlerClient,
    ExecutionResult,
    ExecutionStatus
)
from .trade_monitor import (
    TradeMonitor,
    TradeRecord,
    TradeStatus,
    TradeErrorHandler,
    PositionTracker
)

# Import TradingAgent lazily (requires environment variables)
def get_trading_agent():
    """Lazy import of TradingAgent to avoid env var requirements."""
    from .trading_agent import TradingAgent
    return TradingAgent

__all__ = [
    # Main agent
    "TradingAgent",
    "get_trading_agent",
    
    # Market data feeds
    "MarketDataFeed",
    "MarketData",
    "OrderBook",
    "PolymarketFeed",
    "CEXFeed",
    "FallbackFeed",
    
    # Data normalization
    "DataNormalizer",
    "NormalizedMarketData",
    "NormalizedOrderBook",
    
    # Signal generation
    "MarketSignalGenerator",
    "MarketSummary",
    "ArbitrageOpportunity",
    "TradingSignal",
    
    # Strategy engine
    "BaseStrategy",
    "StrategyDecision",
    "StrategyType",
    "ArbitrageStrategy",
    "TrendFollowingStrategy",
    "StrategySelector",
    
    # Risk manager
    "RiskManager",
    "Position",
    "RiskMetrics",
    "RiskLevel",
    
    # Signal processor
    "SignalProcessor",
    "TechnicalIndicatorCalculator",
    "VolumeAnalyzer",
    "LiquidityAssessor",
    "TechnicalIndicators",
    "VolumeAnalysis",
    "LiquidityAssessment",
    
    # Decision engine
    "DecisionEngine",
    "FinalDecision",
    "DecisionAction",
    
    # Trade encoder
    "PolymarketTradeEncoder",
    "UserOperationEncoder",
    "TradeParams",
    "EncodedTrade",
    "TokenType",
    "OrderSide",
    
    # Trade executor
    "TradeExecutor",
    "BundlerClient",
    "ExecutionResult",
    "ExecutionStatus",
    
    # Trade monitor
    "TradeMonitor",
    "TradeRecord",
    "TradeStatus",
    "TradeErrorHandler",
    "PositionTracker",
]
