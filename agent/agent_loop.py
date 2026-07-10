"""
SAI Protocol — Agent Loop
---------------------------
The main execution loop of the autonomous trading agent.
Runs inside the TEE with access to the EnclaveKeyManager for signing.

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

from web3 import Web3
from eth_abi import encode

from enclave.key_manager import EnclaveKeyManager

import sys
from pathlib import Path
# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))
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

def build_user_op(sender: str, nonce: int, call_data: bytes) -> dict:
    return {
        "sender":               sender,
        "nonce":                hex(nonce),
        "initCode":             "0x",
        "callData":             "0x" + call_data.hex(),
        "callGasLimit":         hex(Config.DEFAULT_CALL_GAS_LIMIT),
        "verificationGasLimit": hex(Config.DEFAULT_VERIFICATION_GAS_LIMIT),
        "preVerificationGas":   hex(Config.DEFAULT_PRE_VERIFICATION_GAS),
        "maxFeePerGas":         hex(Config.DEFAULT_MAX_FEE_PER_GAS),
        "maxPriorityFeePerGas": hex(Config.DEFAULT_MAX_PRIORITY_FEE_PER_GAS),
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

# ─── Main agent loop ──────────────────────────────────────────────────────────

class AgentLoop:
    """
    Main execution loop. Ties together market data, strategy, signing,
    and either dry-run logging or live bundler submission.

    The strategy engine (Phase 4) plugs in via _evaluate_market().
    Right now it's a stub that returns a no-op decision — replace it
    with real logic in Phase 4 without touching anything else here.
    """

    def __init__(self, key_manager: EnclaveKeyManager):
        self.key_manager = key_manager
        self.w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))
        self.nonce_tracker = NonceTracker(self.w3, SOUL_ACCOUNT_ADDR)
        self.dry_run_logger = DryRunLogger() if DRY_RUN else None

        if DRY_RUN:
            logger.info("=" * 50)
            logger.info("  SIMULATION MODE — DRY RUN ACTIVE")
            logger.info("  No transactions will be broadcast.")
            logger.info("  All ops logged to dry_run_logs/")
            logger.info("=" * 50)
        else:
            logger.info("LIVE MODE — transactions will be broadcast to bundler")

    def run(self):
        """Main loop. Runs until process is killed or an unrecoverable error occurs."""
        cycle = 0
        while True:
            cycle += 1
            logger.info(f"--- Cycle {cycle} ---")

            try:
                self._run_cycle()
            except Exception as e:
                logger.error(f"Cycle {cycle} failed: {e}", exc_info=True)
                # Don't exit on a single cycle failure — log it and continue.
                # The heartbeat will handle key rotation independently.

            time.sleep(CYCLE_INTERVAL)

    def _run_cycle(self):
        """One full decision-action cycle."""

        # 1. Confirm key is still active before doing anything
        if not self.key_manager.is_key_active:
            logger.warning("No active enclave key — skipping cycle, waiting for rotation.")
            return

        # 2. Fetch market data (Phase 4: replace stub with real feeds)
        market_signal = self._fetch_market_signal()

        # 3. Evaluate strategy (Phase 4: replace stub with real engine)
        strategy_decision = self._evaluate_market(market_signal)

        # 4. If no trade signal, skip the rest of this cycle
        if not strategy_decision.get("should_trade", False):
            logger.info(f"No signal this cycle. Reason: {strategy_decision.get('reason', 'none')}")
            return

        # 5. Build the UserOperation
        call_data = self._encode_trade(strategy_decision)
        nonce = self.nonce_tracker.next()
        op = build_user_op(
            sender=Web3.to_checksum_address(SOUL_ACCOUNT_ADDR),
            nonce=nonce,
            call_data=call_data,
        )

        # 6. Sign with the enclave key
        op_hash = hash_user_op(op)
        signature = self.key_manager.sign_user_op_hash(op_hash)
        op["signature"] = "0x" + signature.hex()

        # 7. Dry-run or live
        if DRY_RUN:
            self.dry_run_logger.log_op(op, market_signal, strategy_decision)
        else:
            self._submit_to_bundler(op)

    # ── Stubs — replace these in Phase 4 ──────────────────────────────────────

    def _fetch_market_signal(self) -> dict:
        """
        Phase 4 Sprint A: Replace with real market data ingestion.
        Should return parsed prediction market conditions, order book state,
        and any relevant oracle data.
        """
        return {
            "summary": "stub — no real data yet",
            "timestamp": time.time(),
            "markets": [],
        }

    def _evaluate_market(self, signal: dict) -> dict:
        """
        Phase 4 Sprint B: Replace with real strategy engine.
        Should return a decision dict with trade size, target market,
        direction, and confidence score.
        """
        return {
            "should_trade": False,
            "reason": "strategy engine not implemented yet (Phase 4)",
            "action": "hold",
        }

    def _encode_trade(self, decision: dict) -> bytes:
        """
        Phase 4 Sprint C: Replace with real trade encoding.
        Should encode the Polymarket or DEX call as ABI-encoded calldata
        for the UserOperation.
        """
        return b""

    # ── Live bundler submission ────────────────────────────────────────────────

    def _submit_to_bundler(self, op: dict):
        """Submit a signed UserOperation to the Pimlico bundler."""
        import requests as req

        if not PIMLICO_RPC_URL:
            logger.error("PIMLICO_RPC_URL not set — cannot submit in live mode.")
            return

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendUserOperation",
            "params": [op, ENTRY_POINT],
        }
        try:
            resp = req.post(PIMLICO_RPC_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error(f"Bundler rejected op: {data['error']}")
            else:
                logger.info(f"UserOp submitted. Hash: {data['result']}")
        except req.RequestException as e:
            logger.error(f"Bundler submission failed: {e}")