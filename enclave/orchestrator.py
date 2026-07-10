"""
SAI Protocol — Enclave Orchestrator
-------------------------------------
Entry point for the Docker container running inside the TEE.
Boot sequence:
  1. Start health check server (dStack needs this before accepting attestations)
  2. Boot key manager (generates key + attests on-chain — blocks until done)
  3. Start heartbeat daemon (background key rotation thread)
  4. Start agent loop (begins market monitoring and trade execution)

All components run in the same process. If the key manager fails to boot,
the whole process exits — there's no point running the agent without a
valid on-chain signing key.
"""

import logging
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from enclave.key_manager import EnclaveKeyManager

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import validate_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


# ─── Health check server ──────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for dStack health checks with rate limiting."""
    key_manager: EnclaveKeyManager = None
    shutdown_requested = False
    _shutdown_lock = threading.Lock()
    
    # Rate limiting: max 10 requests per minute per IP
    rate_limit_requests = 10
    rate_limit_window = 60  # seconds
    _request_counts = defaultdict(list)
    _rate_limit_lock = threading.Lock()

    def _check_rate_limit(self, client_ip: str) -> bool:
        """Check if client has exceeded rate limit."""
        with self._rate_limit_lock:
            now = time.time()
            # Clean up old requests outside the window
            self._request_counts[client_ip] = [
                ts for ts in self._request_counts[client_ip]
                if now - ts < self.rate_limit_window
            ]
            
            # Check if under limit
            if len(self._request_counts[client_ip]) < self.rate_limit_requests:
                self._request_counts[client_ip].append(now)
                return True
            return False

    def do_GET(self):
        client_ip = self.client_address[0]
        
        if not self._check_rate_limit(client_ip):
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"rate limit exceeded"}')
            return
        
        if self.path == "/health":
            if self.key_manager and self.key_manager.is_key_active:
                body = b'{"status":"ok","key":"active"}'
                code = 200
            else:
                body = b'{"status":"degraded","key":"inactive"}'
                code = 503
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default HTTP server access logs — too noisy
        pass


def start_health_server(key_manager: EnclaveKeyManager, port: int = 8080):
    HealthHandler.key_manager = key_manager
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server running on :{port}/health")
    return server


# ─── Main boot sequence ───────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("SAI Protocol Agent — Enclave Boot")
    logger.info("=" * 60)

    # Validate required configuration at startup
    validate_config(["SOUL_ACCOUNT_ADDRESS", "BASE_SEPOLIA_RPC_URL"])

    key_manager = EnclaveKeyManager()
    health_server = None
    agent = None

    # Setup graceful shutdown handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        
        # Use lock to prevent race conditions during shutdown
        with HealthHandler._shutdown_lock:
            HealthHandler.shutdown_requested = True
        
        if health_server:
            logger.info("Shutting down health server...")
            health_server.shutdown()
        
        if agent and hasattr(agent, 'stop'):
            logger.info("Stopping agent...")
            agent.stop()
        
        logger.info("Shutdown complete. Exiting.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Start health server first — dStack checks this before allowing
    # the attestation flow to proceed. It returns 503 until the key
    # is active, which is correct — we're not ready yet.
    health_server = start_health_server(key_manager)

    # Boot the key manager. This blocks until:
    #   1. A fresh keypair is generated
    #   2. A hardware attestation quote is fetched from dStack
    #   3. rotateEnclaveKey() is confirmed on-chain
    # If any step fails, we exit — running without a valid key is pointless.
    try:
        key_manager.boot()
    except Exception as e:
        logger.critical(f"Key manager boot failed: {e}")
        logger.critical("Cannot proceed without an active on-chain key. Exiting.")
        sys.exit(1)

    # Start the heartbeat background thread for automatic key rotation
    key_manager.start_heartbeat()

    # Start the agent loop, passing it the key manager as the signing interface.
    # Import here to avoid circular imports and to defer agent dep loading
    # until after the enclave is confirmed active.
    try:
        # Import the specific agent implementation based on configuration
        agent_type = os.environ.get("AGENT_TYPE", "trading")
        
        if agent_type == "trading":
            from agents.trading.trading_agent import TradingAgent
            agent = TradingAgent(key_manager=key_manager)
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
        
        # Initialize and start the agent
        agent.start()
        logger.info(f"Starting {agent_type} agent loop...")
        agent.run()  # blocks forever (or until crash)
    except Exception as e:
        logger.critical(f"Agent loop crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
