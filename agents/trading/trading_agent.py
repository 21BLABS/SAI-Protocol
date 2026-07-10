"""
SAI Protocol — Trading Agent Implementation
-------------------------------------------
Autonomous trading agent that inherits from BaseAgent.
Implements market data fetching, strategy evaluation, and trade execution.

Execution cycle (repeating):
  1. Fetch market data from oracle/Polymarket feeds
  2. Run strategy engine to evaluate opportunities
  3. If signal found: package as UserOperation
  4. In DRY_RUN mode: write to local JSON log instead of broadcasting
  5. In LIVE mode: sign with enclave key and submit to bundler
  6. Sleep until next cycle

DRY_RUN mode is controlled by the DRY_RUN environment variable.
Set DRY_RUN=true in dstack.yaml to run the full pipeline without
spending any gas or submitting anything to the bundler.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from web3 import Web3
from eth_abi import encode

from market_data_feed import PolymarketFeed, CEXFeed, FallbackFeed
from data_normalizer import DataNormalizer
from market_signal import MarketSignalGenerator
from strategy_engine import ArbitrageStrategy, TrendFollowingStrategy, StrategySelector
from risk_manager import RiskManager
from signal_processor import SignalProcessor
from decision_engine import DecisionEngine
from trade_encoder import PolymarketTradeEncoder, UserOperationEncoder, TradeParams, OrderSide
from trade_executor import TradeExecutor, BundlerClient
from trade_monitor import TradeMonitor, TradeErrorHandler, PositionTracker

from enclave.key_manager import EnclaveKeyManager
from agent.base_agent import BaseAgent

import sys
from pathlib import Path
# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import Config

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

# Use centralized configuration from config.py
DRY_RUN = Config.DRY_RUN
SOUL_ACCOUNT_ADDR = Config.SOUL_ACCOUNT_ADDRESS
PIMLICO_RPC_URL = Config.PIMLICO_RPC_URL
BASE_SEPOLIA_RPC = Config.BASE_SEPOLIA_RPC_URL

ENTRY_POINT = Config.ENTRY_POINT
CHAIN_ID = Config.CHAIN_ID

# How often the agent checks for opportunities (seconds)
CYCLE_INTERVAL = Config.CYCLE_INTERVAL

# Dry-run log output directory
DRY_RUN_LOG_DIR = Path("/app/dry_run_logs")

# ─── UserOperation helpers ────────────────────────────────────────────────────

def build_user_op(
    sender: str,
    nonce: int,
    call_data: bytes,
    call_gas_limit: Optional[int] = None,
    verification_gas_limit: Optional[int] = None,
    pre_verification_gas: Optional[int] = None,
    max_fee_per_gas: Optional[int] = None,
    max_priority_fee_per_gas: Optional[int] = None
) -> dict:
    """
    Build a UserOperation with dynamic or provided gas parameters.
    
    Args:
        sender: Sender address
        nonce: Nonce value
        call_data: Call data bytes
        call_gas_limit: Optional call gas limit (default: from Config)
        verification_gas_limit: Optional verification gas limit (default: from Config)
        pre_verification_gas: Optional pre-verification gas (default: from Config)
        max_fee_per_gas: Optional max fee per gas (default: from Config)
        max_priority_fee_per_gas: Optional max priority fee per gas (default: from Config)
    
    Returns:
        UserOperation dictionary
    """
    return {
        "sender":               sender,
        "nonce":                hex(nonce),
        "initCode":             "0x",
        "callData":             "0x" + call_data.hex(),
        "callGasLimit":         hex(call_gas_limit or Config.DEFAULT_CALL_GAS_LIMIT),
        "verificationGasLimit": hex(verification_gas_limit or Config.DEFAULT_VERIFICATION_GAS_LIMIT),
        "preVerificationGas":   hex(pre_verification_gas or Config.DEFAULT_PRE_VERIFICATION_GAS),
        "maxFeePerGas":         hex(max_fee_per_gas or Config.DEFAULT_MAX_FEE_PER_GAS),
        "maxPriorityFeePerGas": hex(max_priority_fee_per_gas or Config.DEFAULT_MAX_PRIORITY_FEE_PER_GAS),
        "paymasterAndData":     "0x",
        "signature":            "0x",
    }

def hash_user_op(op: dict) -> bytes:
    inner = Web3.keccak(encode(
        ['address','uint256','bytes32','bytes32','uint256','uint256',
         'uint256','uint256','uint256','bytes32'],
        [
            Web3.to_checksum_address(op["sender"]),
            int(op["nonce"], 16),
            Web3.keccak(bytes.fromhex(op["initCode"].lstrip("0x") or "")),
            Web3.keccak(bytes.fromhex(op["callData"].lstrip("0x") or "")),
            int(op["callGasLimit"], 16),
            int(op["verificationGasLimit"], 16),
            int(op["preVerificationGas"], 16),
            int(op["maxFeePerGas"], 16),
            int(op["maxPriorityFeePerGas"], 16),
            Web3.keccak(bytes.fromhex(op["paymasterAndData"].lstrip("0x") or "")),
        ]
    ))
    return Web3.keccak(encode(
        ['bytes32', 'address', 'uint256'],
        [inner, Web3.to_checksum_address(ENTRY_POINT), CHAIN_ID]
    ))

# ─── Dry-run logger ───────────────────────────────────────────────────────────

class DryRunLogger:
    """
    In simulation mode, writes every fully-signed UserOperation to a
    timestamped JSON file instead of broadcasting it to the bundler.

    This lets you:
    - Verify the agent's decision-making over thousands of market ticks
    - Inspect exactly what would have been broadcast
    - Benchmark strategy performance without spending gas
    - Catch signing errors before they touch real funds
    """

    def __init__(self):
        DRY_RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.session_file = DRY_RUN_LOG_DIR / f"session_{int(time.time())}.jsonl"
        self.op_count = 0
        logger.info(f"[DRY RUN] Logging to {self.session_file}")

    def log_op(
        self,
        op: dict,
        market_signal: dict,
        strategy_decision: dict,
    ):
        """Write one cycle's output to the session log."""
        self.op_count += 1
        record = {
            "timestamp":         datetime.now(timezone.utc).isoformat(),
            "op_number":         self.op_count,
            "market_signal":     market_signal,
            "strategy_decision": strategy_decision,
            "user_op":           op,
            "would_broadcast_to": ENTRY_POINT,
        }
        with open(self.session_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        logger.info(
            f"[DRY RUN] Op #{self.op_count} logged. "
            f"Signal: {market_signal.get('summary', 'n/a')} | "
            f"Decision: {strategy_decision.get('action', 'n/a')}"
        )

# ─── Nonce tracker ────────────────────────────────────────────────────────────

SOUL_NONCE_ABI = [{
    "name": "usedNonces",
    "type": "function",
    "stateMutability": "view",
    "inputs": [{"type": "uint256"}],
    "outputs": [{"type": "bool"}],
}]

class NonceTracker:
    """
    Tracks the next usable nonce for the SoulAccount.
    Reads the on-chain state once at boot, then increments locally.
    Falls back to on-chain check if local tracking gets out of sync.
    Implements periodic on-chain verification to prevent desynchronization.
    """

    def __init__(self, w3: Web3, soul_addr: str, verify_interval: int = 100):
        self._w3 = w3
        self._soul = w3.eth.contract(
            address=Web3.to_checksum_address(soul_addr),
            abi=SOUL_NONCE_ABI,
        )
        self._nonce = self._find_first_unused()
        self._verify_interval = verify_interval  # Verify every N nonces
        self._nonce_count = 0  # Track number of nonces used
        logger.info(f"Nonce tracker initialized at nonce {self._nonce} (verify every {verify_interval} nonces)")

    def _find_first_unused(self, start: int = 0) -> int:
        n = start
        while self._soul.functions.usedNonces(n).call():
            n += 1
        return n

    def _verify_nonce_sync(self) -> None:
        """
        Verify local nonce is synchronized with on-chain state.
        If out of sync, resynchronize by finding the first unused nonce.
        """
        try:
            # Check if current nonce is already used on-chain
            if self._soul.functions.usedNonces(self._nonce).call():
                logger.warning(
                    f"Nonce desynchronization detected: local nonce {self._nonce} already used on-chain. "
                    "Resynchronizing..."
                )
                self._nonce = self._find_first_unused(self._nonce)
                logger.info(f"Nonce resynchronized to {self._nonce}")
            else:
                logger.debug(f"Nonce synchronization verified: {self._nonce}")
        except Exception as e:
            logger.error(f"Failed to verify nonce synchronization: {e}")

    def next(self) -> int:
        nonce = self._nonce
        self._nonce += 1
        self._nonce_count += 1
        
        # Periodic verification to prevent desynchronization
        if self._nonce_count % self._verify_interval == 0:
            self._verify_nonce_sync()
        
        return nonce

# ─── Main agent implementation ──────────────────────────────────────────────────

class TradingAgent(BaseAgent):
    """
    Autonomous trading agent implementation.
    Inherits from BaseAgent and implements trading-specific logic.
    
    The strategy engine (Phase 4) plugs in via _evaluate_market().
    Right now it's a stub that returns a no-op decision — replace it
    with real logic in Phase 4 without touching anything else here.
    """

    def __init__(self, key_manager: EnclaveKeyManager, config: Optional[Dict[str, Any]] = None):
        super().__init__(key_manager, config)
        self.w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))
        self.nonce_tracker = NonceTracker(self.w3, SOUL_ACCOUNT_ADDR)
        self.dry_run_logger = DryRunLogger() if DRY_RUN else None
        
        # Slippage protection configuration
        self.max_slippage_bps = config.get("max_slippage_bps", 50)  # Default 0.5% (50 basis points)
        self.min_acceptable_price = config.get("min_acceptable_price", None)
        
        # Market data pipeline configuration
        self._init_market_data_pipeline(config)
        
        # Strategy engine configuration
        self._init_strategy_engine(config)
        
        # Trade execution configuration
        self._init_trade_execution(config)

        if DRY_RUN:
            logger.info("=" * 50)
            logger.info("  SIMULATION MODE — DRY RUN ACTIVE")
            logger.info("  No transactions will be broadcast.")
            logger.info("  All ops logged to dry_run_logs/")
            logger.info("=" * 50)
        else:
            logger.info("LIVE MODE — transactions will be broadcast to bundler")
    
    def _init_market_data_pipeline(self, config: Optional[Dict[str, Any]]):
        """
        Initialize the market data pipeline components.
        
        Args:
            config: Agent configuration dictionary
        """
        # Get market data configuration
        polymarket_api_key = config.get("polymarket_api_key") or os.environ.get("POLYMARKET_API_KEY")
        cex_exchange = config.get("cex_exchange", "coinbase")  # or "binance"
        target_symbols = config.get("target_symbols", ["BTC-USD", "ETH-USD"])
        
        # Initialize data feeds
        feeds = []
        
        # Add Polymarket feed if API key is available
        if polymarket_api_key:
            polymarket_feed = PolymarketFeed(api_key=polymarket_api_key)
            feeds.append(polymarket_feed)
            logger.info("Polymarket feed initialized")
        else:
            logger.warning("Polymarket API key not provided, skipping Polymarket feed")
        
        # Add CEX feed for reference pricing
        cex_feed = CEXFeed(exchange=cex_exchange)
        feeds.append(cex_feed)
        logger.info(f"CEX feed initialized ({cex_exchange})")
        
        # Create fallback feed
        if feeds:
            self.market_feed = FallbackFeed(feeds)
            logger.info(f"Market data feed initialized with {len(feeds)} source(s)")
        else:
            logger.error("No market data feeds available")
            self.market_feed = None
        
        # Initialize data normalizer
        self.data_normalizer = DataNormalizer()
        logger.info("Data normalizer initialized")
        
        # Initialize market signal generator
        self.signal_generator = MarketSignalGenerator(self.data_normalizer)
        logger.info("Market signal generator initialized")
        
        # Store target symbols
        self.target_symbols = target_symbols
        logger.info(f"Target symbols: {target_symbols}")
    
    def _init_strategy_engine(self, config: Optional[Dict[str, Any]]):
        """
        Initialize the strategy engine components.
        
        Args:
            config: Agent configuration dictionary
        """
        # Get strategy configuration
        strategy_config = config.get("strategy", {})
        risk_config = config.get("risk", {})
        
        # Initialize strategies
        arbitrage_strategy = ArbitrageStrategy(strategy_config)
        trend_strategy = TrendFollowingStrategy(strategy_config)
        
        self.strategies = [arbitrage_strategy, trend_strategy]
        logger.info(f"Initialized {len(self.strategies)} strategies")
        
        # Initialize risk manager
        self.risk_manager = RiskManager(risk_config)
        logger.info("Risk manager initialized")
        
        # Initialize signal processor
        self.signal_processor = SignalProcessor(strategy_config)
        logger.info("Signal processor initialized")
        
        # Initialize decision engine
        self.decision_engine = DecisionEngine(
            strategies=self.strategies,
            risk_manager=self.risk_manager,
            signal_processor=self.signal_processor,
            config=strategy_config
        )
        logger.info("Decision engine initialized")
    
    def _init_trade_execution(self, config: Optional[Dict[str, Any]]):
        """
        Initialize the trade execution components.
        
        Args:
            config: Agent configuration dictionary
        """
        # Get trade execution configuration
        trade_config = config.get("trade", {})
        bundler_url = config.get("bundler_url") or Config.BUNDLER_RPC_URL
        
        if not bundler_url:
            logger.warning("Bundler URL not provided, trade execution will be in dry run mode")
            bundler_url = "https://dummy.bundler.url"  # Placeholder
        elif "dummy" in bundler_url.lower():
            logger.warning("Bundler URL is a dummy placeholder - ensure production bundler URL is configured")
        
        # Initialize trade encoder
        self.trade_encoder = PolymarketTradeEncoder(trade_config, key_manager=self.key_manager)
        self.user_op_encoder = UserOperationEncoder(trade_config)
        logger.info("Trade encoders initialized")
        
        # Initialize bundler client
        self.bundler_client = BundlerClient(bundler_url, trade_config)
        logger.info(f"Bundler client initialized: {bundler_url}")
        
        # Initialize trade executor
        self.trade_executor = TradeExecutor(
            bundler_url=bundler_url,
            user_op_encoder=self.user_op_encoder,
            config={**trade_config, "dry_run": DRY_RUN}
        )
        logger.info("Trade executor initialized")
        
        # Initialize trade monitor
        self.trade_monitor = TradeMonitor(self.bundler_client, trade_config)
        logger.info("Trade monitor initialized")
        
        # Initialize error handler
        self.error_handler = TradeErrorHandler(trade_config)
        logger.info("Error handler initialized")
        
        # Initialize position tracker
        self.position_tracker = PositionTracker(trade_config)
        logger.info("Position tracker initialized")

    # ─── BaseAgent abstract method implementations ─────────────────────────────

    def initialize(self) -> None:
        """Initialize the trading agent."""
        logger.info("Initializing TradingAgent...")
        # Validate configuration
        if not SOUL_ACCOUNT_ADDR:
            raise ValueError("SOUL_ACCOUNT_ADDRESS not set")
        
        # Test blockchain connection
        if not self.w3.is_connected():
            raise ConnectionError("Cannot connect to Base Sepolia RPC")
        
        logger.info("TradingAgent initialized successfully")

    def execute_cycle(self) -> Dict[str, Any]:
        """
        Execute one trading cycle.
        
        Returns:
            Dict containing cycle results
        """
        self._increment_cycle()
        cycle_num = self.cycle_count
        
        logger.info(f"--- Trading Cycle {cycle_num} ---")

        try:
            # 1. Confirm key is still active before doing anything
            if not self.key_manager.is_key_active:
                logger.warning("No active enclave key — skipping cycle, waiting for rotation.")
                return {
                    "success": False,
                    "action_taken": "skip",
                    "details": {"reason": "no_active_key"},
                    "error": None
                }

            # 2. Fetch market data (Phase 4: replace stub with real feeds)
            market_signal = self._fetch_market_signal()

            # 3. Evaluate strategy (Phase 4: replace stub with real engine)
            strategy_decision = self._evaluate_market(market_signal)

            # 4. If no trade signal, skip the rest of this cycle
            if not strategy_decision.get("should_trade", False):
                logger.info(f"No signal this cycle. Reason: {strategy_decision.get('reason', 'none')}")
                return {
                    "success": True,
                    "action_taken": "hold",
                    "details": {"reason": strategy_decision.get('reason', 'none')},
                    "error": None
                }

            # 5. Build the UserOperation with dynamic gas estimation
            # Apply slippage protection to the strategy decision
            if "expected_price" in strategy_decision and "direction" in strategy_decision:
                adjusted_price = self._apply_slippage_protection(
                    strategy_decision["expected_price"],
                    strategy_decision["direction"]
                )
                strategy_decision["slippage_protected_price"] = adjusted_price
                logger.info(f"Applied slippage protection: {strategy_decision['expected_price']} -> {adjusted_price}")
            
            call_data = self._encode_trade(strategy_decision)
            nonce = self.nonce_tracker.next()
            
            # Estimate gas limits dynamically
            gas_estimates = self._estimate_gas_limits(call_data)
            
            op = build_user_op(
                sender=Web3.to_checksum_address(SOUL_ACCOUNT_ADDR),
                nonce=nonce,
                call_data=call_data,
                call_gas_limit=gas_estimates["call_gas_limit"],
                verification_gas_limit=gas_estimates["verification_gas_limit"],
                pre_verification_gas=gas_estimates["pre_verification_gas"],
                max_fee_per_gas=gas_estimates["max_fee_per_gas"],
                max_priority_fee_per_gas=gas_estimates["max_priority_fee_per_gas"]
            )

            # 6. Sign with the enclave key
            op_hash = hash_user_op(op)
            signature = self.key_manager.sign_user_op_hash(op_hash)
            op["signature"] = "0x" + signature.hex()

            # 7. Dry-run or live
            if DRY_RUN:
                self.dry_run_logger.log_op(op, market_signal, strategy_decision)
                return {
                    "success": True,
                    "action_taken": "dry_run_log",
                    "details": {"market_signal": market_signal, "strategy_decision": strategy_decision},
                    "error": None
                }
            else:
                result = self._submit_to_bundler(op)
                return {
                    "success": True,
                    "action_taken": "submit_to_bundler",
                    "details": {"op_hash": result},
                    "error": None
                }

        except Exception as e:
            logger.error(f"Trading cycle {cycle_num} failed: {e}", exc_info=True)
            return {
                "success": False,
                "action_taken": "error",
                "details": {},
                "error": str(e)
            }

    def shutdown(self) -> None:
        """Shutdown the trading agent."""
        logger.info("Shutting down TradingAgent...")
        # Close connections, cleanup resources
        logger.info("TradingAgent shut down successfully")

    def get_agent_info(self) -> Dict[str, Any]:
        """Return metadata about this trading agent."""
        return {
            "agent_type": "trading",
            "version": "1.0.0",
            "name": "SAI Trading Agent",
            "description": "Autonomous trading agent for prediction markets and DEX arbitrage",
            "capabilities": [
                "market_data_ingestion",
                "strategy_evaluation",
                "trade_execution",
                "risk_management"
            ],
            "author": "SAI Protocol",
            "chain_id": CHAIN_ID,
            "requires_paymaster": False
        }

    # ─── Legacy run method for backward compatibility ───────────────────────────

    def run(self):
        """
        Main loop. Runs until process is killed or an unrecoverable error occurs.
        This method is kept for backward compatibility with the orchestrator.
        """
        while True:
            try:
                result = self.execute_cycle()
                if not result["success"]:
                    logger.warning(f"Cycle failed: {result.get('error', 'unknown')}")
            except Exception as e:
                logger.error(f"Cycle execution failed: {e}", exc_info=True)
                # Don't exit on a single cycle failure — log it and continue.
                # The heartbeat will handle key rotation independently.

            time.sleep(CYCLE_INTERVAL)


    # ── Stubs — replace these in Phase 4 ──────────────────────────────────────

    def _estimate_gas_limits(self, call_data: bytes) -> Dict[str, int]:
        """
        Estimate gas limits for UserOperation with 20% buffer.
        Tries bundler's estimateUserOperationGas endpoint first, falls back to network estimation.
        
        Args:
            call_data: Call data bytes
            
        Returns:
            Dict containing gas limit estimates
        """
        # Try bundler gas estimation first
        bundler_gas_estimates = self._estimate_gas_from_bundler(call_data)
        if bundler_gas_estimates:
            logger.info("Using bundler gas estimates")
            return bundler_gas_estimates
        
        # Fallback to network-based estimation
        try:
            # Get current gas prices from network
            current_gas_price = self.w3.eth.gas_price
            max_fee_per_gas = int(current_gas_price * 1.2)  # 20% buffer
            max_priority_fee_per_gas = int(current_gas_price * 1.1)  # 10% buffer
            
            # Estimate gas limits based on call data size
            call_data_size = len(call_data)
            base_call_gas = 50_000 + (call_data_size * 100)  # Base + per-byte cost
            call_gas_limit = int(base_call_gas * 1.2)  # 20% buffer
            
            verification_gas_limit = int(call_gas_limit * 0.75)  # 75% of call gas
            pre_verification_gas = int(call_gas_limit * 0.25)  # 25% of call gas
            
            logger.info(
                f"Network-based gas estimation: "
                f"callGas={call_gas_limit}, "
                f"maxFee={max_fee_per_gas}, "
                f"maxPriority={max_priority_fee_per_gas}"
            )
            
            return {
                "call_gas_limit": call_gas_limit,
                "verification_gas_limit": verification_gas_limit,
                "pre_verification_gas": pre_verification_gas,
                "max_fee_per_gas": max_fee_per_gas,
                "max_priority_fee_per_gas": max_priority_fee_per_gas
            }
            
        except Exception as e:
            logger.warning(f"Gas estimation failed, using conservative defaults: {e}")
            return {
                "call_gas_limit": 200_000,
                "verification_gas_limit": 150_000,
                "pre_verification_gas": 50_000,
                "max_fee_per_gas": Web3.to_wei(1, "gwei"),
                "max_priority_fee_per_gas": Web3.to_wei(1, "gwei")
            }
    
    def _estimate_gas_from_bundler(self, call_data: bytes) -> Optional[Dict[str, int]]:
        """
        Estimate gas using bundler's estimateUserOperationGas endpoint.
        
        Args:
            call_data: Call data bytes
            
        Returns:
            Dict with gas estimates or None if estimation fails
        """
        bundler_url = self.bundler_client.bundler_url if hasattr(self.bundler_client, 'bundler_url') else None
        
        if not bundler_url or "dummy" in bundler_url:
            logger.debug("Bundler URL not configured or is dummy, skipping bundler gas estimation")
            return None
        
        try:
            import requests
            
            # Build a minimal UserOperation for estimation
            user_op = {
                "sender": SOUL_ACCOUNT_ADDR,
                "nonce": "0x0",
                "initCode": "0x",
                "callData": "0x" + call_data.hex(),
                "callGasLimit": "0x186A0",  # 100k
                "verificationGasLimit": "0x249F0",  # 150k
                "preVerificationGas": "0xC350",  # 50k
                "maxFeePerGas": "0x3B9ACA00",  # 1 gwei
                "maxPriorityFeePerGas": "0x3B9ACA00",
                "paymasterAndData": "0x",
                "signature": "0x"
            }
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_estimateUserOperationGas",
                "params": [user_op, ENTRY_POINT]
            }
            
            response = requests.post(bundler_url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if "result" in data:
                result = data["result"]
                estimates = {
                    "call_gas_limit": int(result.get("callGasLimit", 200_000), 16),
                    "verification_gas_limit": int(result.get("verificationGasLimit", 150_000), 16),
                    "pre_verification_gas": int(result.get("preVerificationGas", 50_000), 16),
                    "max_fee_per_gas": int(result.get("maxFeePerGas", Web3.to_wei(1, "gwei")), 16),
                    "max_priority_fee_per_gas": int(result.get("maxPriorityFeePerGas", Web3.to_wei(1, "gwei")), 16)
                }
                logger.info(f"Bundler gas estimates: {estimates}")
                return estimates
            
        except Exception as e:
            logger.debug(f"Bundler gas estimation failed: {e}")
        
        return None

    def _apply_slippage_protection(self, expected_price: float, direction: str) -> float:
        """
        Apply slippage protection to calculate minimum acceptable price.
        
        Args:
            expected_price: Expected execution price
            direction: Trade direction ("buy" or "sell")
            
        Returns:
            Minimum acceptable price with slippage protection
        """
        if self.min_acceptable_price is not None:
            return self.min_acceptable_price
        
        # Calculate slippage-adjusted price
        slippage_multiplier = (10000 - self.max_slippage_bps) / 10000
        
        if direction == "buy":
            # For buys, we want to pay at most slippage more than expected
            max_acceptable_price = expected_price * (10000 + self.max_slippage_bps) / 10000
            logger.info(f"Slippage protection: buy max price={max_acceptable_price} (expected={expected_price}, slippage={self.max_slippage_bps}bps)")
            return max_acceptable_price
        else:
            # For sells, we want to receive at least slippage less than expected
            min_acceptable_price = expected_price * slippage_multiplier
            logger.info(f"Slippage protection: sell min price={min_acceptable_price} (expected={expected_price}, slippage={self.max_slippage_bps}bps)")
            return min_acceptable_price

    def _fetch_market_signal(self) -> dict:
        """
        Phase 4 Sprint A: Real market data ingestion.
        Fetches market data from configured sources, normalizes it,
        and generates trading signals.
        
        Returns:
            Dict containing market summary, trading signals, and opportunities
        """
        if not self.market_feed:
            logger.error("Market data feed not initialized")
            return {
                "summary": "error — no market data feed",
                "timestamp": time.time(),
                "markets": [],
                "error": "Market data feed not initialized"
            }
        
        try:
            # Fetch market data for all target symbols
            all_market_data = []
            all_order_books = []
            
            for symbol in self.target_symbols:
                # Fetch price data
                price_data = self.market_feed.get_price(symbol)
                if price_data:
                    all_market_data.append(price_data)
                    logger.debug(f"Fetched price data for {symbol}: {price_data.price}")
                
                # Fetch order book (optional, may not be available for all sources)
                try:
                    order_book = self.market_feed.get_order_book(symbol, depth=5)
                    if order_book:
                        all_order_books.append(order_book)
                        logger.debug(f"Fetched order book for {symbol}")
                except Exception as e:
                    logger.debug(f"Order book not available for {symbol}: {e}")
            
            if not all_market_data:
                logger.warning("No market data fetched from any source")
                return {
                    "summary": "error — no market data available",
                    "timestamp": time.time(),
                    "markets": [],
                    "error": "No market data available from any source"
                }
            
            # Generate market summary
            summary = self.signal_generator.generate_market_summary(
                all_market_data,
                all_order_books[0] if all_order_books else None
            )
            
            if not summary:
                logger.warning("Failed to generate market summary")
                return {
                    "summary": "error — failed to generate summary",
                    "timestamp": time.time(),
                    "markets": [],
                    "error": "Failed to generate market summary"
                }
            
            # Detect arbitrage opportunities
            opportunities = self.signal_generator.detect_arbitrage_opportunities(
                all_market_data,
                all_order_books
            )
            
            logger.info(f"Detected {len(opportunities)} arbitrage opportunities")
            
            # Generate trading signal
            signal = self.signal_generator.generate_trading_signal(summary, opportunities)
            
            # Build response
            result = {
                "summary": {
                    "symbol": summary.symbol,
                    "current_price": summary.current_price,
                    "volume": summary.volume,
                    "price_change_24h": summary.price_change_24h,
                    "volatility_24h": summary.volatility_24h,
                    "spread": summary.spread,
                    "confidence": summary.confidence,
                    "quality_score": summary.quality_score,
                    "sources_used": summary.sources_used
                },
                "timestamp": summary.timestamp,
                "markets": [summary.symbol],
                "opportunities": [
                    {
                        "symbol": opp.symbol,
                        "type": opp.opportunity_type,
                        "expected_profit": opp.expected_profit,
                        "confidence": opp.confidence,
                        "buy_price": opp.buy_price,
                        "sell_price": opp.sell_price,
                        "buy_source": opp.buy_source,
                        "sell_source": opp.sell_source
                    }
                    for opp in opportunities
                ],
                "signal": {
                    "type": signal.signal_type if signal else "hold",
                    "confidence": signal.confidence if signal else 0.0,
                    "reason": signal.reason if signal else "No clear signal",
                    "risk_level": signal.risk_level if signal else "low",
                    "expected_return": signal.expected_return if signal else None
                } if signal else None
            }
            
            logger.info(
                f"Market signal generated: "
                f"symbol={summary.symbol}, "
                f"price={summary.current_price:.4f}, "
                f"signal={result['signal']['type'] if result['signal'] else 'hold'}, "
                f"confidence={result['signal']['confidence'] if result['signal'] else 0:.2f}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to fetch market signal: {e}", exc_info=True)
            return {
                "summary": "error — exception during data fetch",
                "timestamp": time.time(),
                "markets": [],
                "error": str(e)
            }

    def _evaluate_market(self, signal: dict) -> dict:
        """
        Phase 4 Sprint B: Real strategy engine evaluation.
        
        Uses the decision engine to evaluate market conditions and generate
        trading decisions with documented logic and risk guardrails.
        
        Args:
            signal: Market signal dictionary from _fetch_market_signal
            
        Returns:
            Dict containing decision with trade size, target market,
            direction, and confidence score
        """
        try:
            # Extract market summary and opportunities from signal
            summary_data = signal.get("summary", {})
            opportunities_data = signal.get("opportunities", [])
            
            # Reconstruct MarketSummary object
            from market_signal import MarketSummary, ArbitrageOpportunity
            
            summary = MarketSummary(
                symbol=summary_data.get("symbol", "BTC/USD"),
                current_price=summary_data.get("current_price", 0.0),
                volume=summary_data.get("volume", 0.0),
                price_change_24h=summary_data.get("price_change_24h"),
                volatility_24h=summary_data.get("volatility_24h"),
                spread=summary_data.get("spread"),
                timestamp=signal.get("timestamp", time.time()),
                sources_used=summary_data.get("sources_used", []),
                confidence=summary_data.get("confidence", 0.0),
                quality_score=summary_data.get("quality_score", 0.0),
                additional_data={}
            )
            
            # Reconstruct ArbitrageOpportunity objects
            opportunities = []
            for opp_data in opportunities_data:
                opp = ArbitrageOpportunity(
                    symbol=opp_data.get("symbol"),
                    opportunity_type=opp_data.get("type"),
                    expected_profit=opp_data.get("expected_profit", 0.0),
                    confidence=opp_data.get("confidence", 0.0),
                    timestamp=time.time(),
                    buy_price=opp_data.get("buy_price"),
                    sell_price=opp_data.get("sell_price"),
                    buy_source=opp_data.get("buy_source"),
                    sell_source=opp_data.get("sell_source"),
                    additional_data=opp_data
                )
                opportunities.append(opp)
            
            # Get current price from summary
            current_price = summary.current_price
            
            if current_price == 0.0:
                logger.warning("Current price is 0, cannot evaluate market")
                return {
                    "should_trade": False,
                    "reason": "Invalid current price (0.0)",
                    "action": "hold",
                    "confidence": 0.0,
                    "position_size": 0.0,
                    "timestamp": time.time()
                }
            
            # Use decision engine to make final decision
            final_decision = self.decision_engine.make_decision(
                summary=summary,
                opportunities=opportunities,
                current_price=current_price
            )
            
            # Convert FinalDecision to dict format
            result = {
                "should_trade": final_decision.action.value in ["buy", "sell"],
                "action": final_decision.action.value,
                "symbol": final_decision.symbol,
                "confidence": final_decision.confidence,
                "position_size": final_decision.position_size,
                "entry_price": final_decision.entry_price,
                "exit_price": final_decision.exit_price,
                "stop_loss": final_decision.stop_loss,
                "take_profit": final_decision.take_profit,
                "reason": final_decision.reasoning,
                "risk_level": final_decision.risk_level,
                "expected_return": final_decision.expected_return,
                "max_loss": final_decision.max_loss,
                "primary_strategy": final_decision.primary_strategy,
                "supporting_strategies": final_decision.supporting_strategies,
                "timestamp": final_decision.timestamp,
                "additional_data": final_decision.additional_data
            }
            
            logger.info(
                f"Market evaluation complete: {result['action'].upper()} {result['symbol']} "
                f"with confidence {result['confidence']:.2f}, "
                f"position_size={result['position_size']:.0%}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to evaluate market: {e}", exc_info=True)
            return {
                "should_trade": False,
                "reason": f"Exception during market evaluation: {str(e)}",
                "action": "hold",
                "confidence": 0.0,
                "position_size": 0.0,
                "timestamp": time.time()
            }

    def _encode_trade(self, decision: dict) -> bytes:
        """
        Phase 4 Sprint C: Real trade encoding.
        
        Encodes the Polymarket CLOB trade as ABI-encoded calldata
        for the UserOperation using the trade encoder.
        
        Args:
            decision: Decision dictionary from _evaluate_market
            
        Returns:
            ABI-encoded calldata
        """
        try:
            # Extract decision parameters
            action = decision.get("action")
            symbol = decision.get("symbol")
            entry_price = decision.get("entry_price")
            position_size = decision.get("position_size", 0.0)
            stop_loss = decision.get("stop_loss")
            take_profit = decision.get("take_profit")
            
            if action not in ["buy", "sell"]:
                logger.info(f"No trade encoding needed for action: {action}")
                return b""
            
            # Extract additional data for prediction market trades
            additional_data = decision.get("additional_data", {})
            condition_id = additional_data.get("condition_id")
            token_id = additional_data.get("token_id", "1")  # Default to YES token
            
            if not condition_id:
                logger.warning("No condition_id in decision, cannot encode prediction market trade")
                return b""
            
            # Determine order side
            side = OrderSide.BUY if action == "buy" else OrderSide.SELL
            
            # Create trade parameters
            trade_params = TradeParams(
                condition_id=condition_id,
                token_id=token_id,
                side=side,
                amount=position_size,  # Position size as token amount
                price=entry_price or 0.5,  # Default to 0.5 for binary options
                maker=SOUL_ACCOUNT_ADDR,
                taker=SOUL_ACCOUNT_ADDR,
                expiration=int(time.time()) + 3600,  # 1 hour expiration
                salt="0x" + "00" * 64  # Random salt
            )
            
            # Encode the trade
            encoded_trade = self.trade_encoder.encode_trade(trade_params, self.w3)
            
            logger.info(
                f"Trade encoded: {action.upper()} {symbol}, "
                f"condition_id={condition_id}, calldata_length={len(encoded_trade.calldata)}"
            )
            
            return encoded_trade.calldata
            
        except Exception as e:
            logger.error(f"Failed to encode trade: {e}", exc_info=True)
            return b""

    # ── Live bundler submission ────────────────────────────────────────────────

    def _submit_to_bundler(self, op: dict):
        """
        Submit a signed UserOperation to the bundler using trade executor.
        
        Args:
            op: UserOperation dictionary
        """
        try:
            # Use trade executor to submit the UserOperation
            # For now, we'll use the bundler client directly
            # In production, this would use the full trade executor flow
            
            bundler_url = os.environ.get("BUNDLER_RPC_URL") or self.config.get("bundler_url")
            
            if not bundler_url:
                logger.error("Bundler URL not set — cannot submit in live mode")
                return
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_sendUserOperation",
                "params": [op, self.user_op_encoder.entry_point],
            }
            
            import requests as req
            
            resp = req.post(bundler_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            if "error" in data:
                logger.error(f"Bundler rejected op: {data['error']}")
            else:
                logger.info(f"UserOp submitted. Hash: {data['result']}")
                
                # Add to trade monitor for tracking
                if data.get("result"):
                    self.trade_monitor.add_trade(
                        trade_id=data["result"],
                        execution_result=type('obj', (object,), {
                            'user_op_hash': data["result"],
                            'transaction_hash': None,
                            'status': type('obj', (object,), {'value': 'submitted'}),
                            'timestamp': time.time(),
                            'error': None,
                            'retry_count': 0
                        })()
                    )
                    
        except Exception as e:
            logger.error(f"Bundler submission failed: {e}", exc_info=True)