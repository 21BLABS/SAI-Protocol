"""
SAI Protocol — Base Agent Interface
------------------------------------
Abstract base class for all autonomous agents running in SAI TEEs.
Defines the standard lifecycle and interface that all agent implementations must follow.

All agents must:
  1. Inherit from BaseAgent
  2. Implement the abstract methods
  3. Follow the lifecycle: initialize() -> execute_cycle() -> shutdown()
  4. Use the provided key_manager for signing operations
  5. Respect the DRY_RUN flag for safe testing
"""

import os
import logging
import signal
import time
from contextlib import contextmanager
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enclave.key_manager import EnclaveKeyManager

import sys
from pathlib import Path
# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config, ConfigurationError

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Exception raised when a cycle times out."""
    pass


@contextmanager
def timeout_context(seconds: int):
    """
    Context manager for timing out operations.
    
    Args:
        seconds: Timeout duration in seconds
    """
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {seconds} seconds")
    
    # Set the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    
    try:
        yield
    finally:
        # Cancel the alarm and restore old handler
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


class BaseAgent(ABC):
    """
    Abstract base class for all SAI autonomous agents.
    
    Provides:
      - Standard lifecycle management
      - Key manager integration
      - Dry-run mode support
      - Error handling and logging
      - Health status reporting
      - Agent communication interface
    
    Agent implementations must:
      - Implement initialize() for setup
      - Implement execute_cycle() for main logic
      - Implement shutdown() for cleanup
      - Implement get_agent_info() for metadata
      - Optionally implement handle_message() for inter-agent communication
    """

    def __init__(self, key_manager: EnclaveKeyManager, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the base agent.

        Args:
            key_manager: EnclaveKeyManager instance for signing operations
            config: Optional agent-specific configuration dictionary
        """
        self.key_manager = key_manager
        self.config = config or {}
        self._is_initialized = False
        self._is_running = False
        self._cycle_count = 0
        self._messaging_enabled = config.get("messaging_enabled", False)
        self._agent_discovery = config.get("agent_discovery", None)
        self._private_key = config.get("private_key", None)
        self._cycle_timeout = config.get("cycle_timeout", 300)  # Default 5 minutes
        self._pending_messages: Dict[int, float] = {}  # message_id -> timestamp
        self._message_timeout = config.get("message_timeout", 300)  # Default 5 minutes

        # Validate private key if provided
        if self._private_key:
            try:
                Config.validate_private_key_config(self._private_key)
            except ConfigurationError as e:
                logger.error(f"Invalid private key in config: {e}")
                raise

        logger.info(f"{self.__class__.__name__} instantiated (DRY_RUN={Config.DRY_RUN})")

    # ─── Abstract methods (must be implemented by subclasses) ──────────────

    @abstractmethod
    def initialize(self) -> None:
        """
        One-time setup when the agent first starts.
        Called by the orchestrator before the main loop begins.
        
        Implementations should:
          - Validate configuration
          - Set up external connections (APIs, databases)
          - Initialize internal state
          - Raise exceptions if setup fails
        """
        pass

    @abstractmethod
    def execute_cycle(self) -> Dict[str, Any]:
        """
        Execute one complete decision/action cycle.
        Called repeatedly by the orchestrator's main loop.
        
        Implementations should:
          - Fetch relevant data (market data, governance proposals, etc.)
          - Process and analyze the data
          - Make decisions based on strategy
          - Execute actions (sign transactions, submit operations)
          - Return a cycle report with results
        
        Returns:
            Dict containing cycle results:
            {
                "success": bool,
                "action_taken": str,
                "details": dict,
                "error": str (if failed)
            }
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Cleanup when the agent is stopping.
        Called by the orchestrator before process exit.
        
        Implementations should:
          - Close external connections
          - Persist any necessary state
          - Release resources
          - Log shutdown completion
        """
        pass

    @abstractmethod
    def get_agent_info(self) -> Dict[str, Any]:
        """
        Return metadata about this agent for registration and discovery.
        
        Returns:
            Dict containing:
            {
                "agent_type": str,           # e.g., "trading", "governance", "service"
                "version": str,              # Semantic version
                "name": str,                 # Human-readable name
                "description": str,          # What this agent does
                "capabilities": list[str],    # List of capabilities
                "author": str,               # Creator/organization
                "chain_id": int,             # Target blockchain
                "requires_paymaster": bool   # Whether agent needs paymaster
            }
        """
        pass

    # ─── Optional communication methods ───────────────────────────────────

    def handle_message(self, from_agent: str, message_type: str, data: bytes) -> Dict[str, Any]:
        """
        Handle incoming messages from other agents.
        Override this method to enable inter-agent communication.
        
        Args:
            from_agent: Address of the sending agent
            message_type: Type of message being received
            data: Message payload
        
        Returns:
            Dict containing response:
            {
                "success": bool,
                "response": dict,
                "error": str (if failed)
            }
        """
        logger.warning(f"{self.__class__.__name__} received message but handle_message not implemented")
        return {
            "success": False,
            "response": {},
            "error": "handle_message not implemented"
        }

    def send_message(self, to_agent: str, message_type: str, data: bytes, payment: int = 0) -> Dict[str, Any]:
        """
        Send a message to another agent.
        Requires messaging to be enabled and configured.

        Args:
            to_agent: Address of the recipient agent
            message_type: Type of message to send
            data: Message payload
            payment: Optional payment amount in wei

        Returns:
            Dict containing result:
            {
                "success": bool,
                "message_id": int,
                "error": str (if failed)
            }
        """
        if not self._messaging_enabled:
            return {
                "success": False,
                "message_id": 0,
                "error": "Messaging not enabled"
            }

        if not self._agent_discovery:
            return {
                "success": False,
                "message_id": 0,
                "error": "AgentDiscovery not configured"
            }

        if not self._private_key:
            return {
                "success": False,
                "message_id": 0,
                "error": "Private key not configured for messaging"
            }

        try:
            result = self._agent_discovery.send_message(
                to_agent=to_agent,
                message_type=message_type,
                data=data,
                private_key=self._private_key,
                payment=payment
            )
            message_id = result.get("message_id", 0)
            
            # Track pending message if successful
            if result.get("success") and message_id > 0:
                import time
                self._pending_messages[message_id] = time.time()
                logger.info(f"Tracking pending message {message_id}")
            
            return {
                "success": result.get("success", False),
                "message_id": message_id,
                "error": None if result.get("success") else "Transaction failed"
            }
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {
                "success": False,
                "message_id": 0,
                "error": str(e)
            }

    def get_supported_message_types(self) -> List[str]:
        """
        Return list of message types this agent can handle.
        Override this method to declare supported message types.

        Returns:
            List of supported message type identifiers
        """
        return []

    def get_message_status(self, message_id: int) -> Dict[str, Any]:
        """
        Check the delivery status of a message by calling AgentMessaging.getMessageFields().

        Args:
            message_id: ID of the message to check

        Returns:
            Dict containing message status:
            {
                "delivered": bool,
                "details": dict (full message details if available),
                "error": str (if failed)
            }
        """
        if not self._agent_discovery:
            return {
                "delivered": False,
                "details": {},
                "error": "AgentDiscovery not configured"
            }

        try:
            message_details = self._agent_discovery.get_message_details(message_id)
            if message_details:
                delivered = message_details.get("delivered", False)
                logger.info(f"Message {message_id} delivered: {delivered}")
                return {
                    "delivered": delivered,
                    "details": message_details,
                    "error": None
                }
            else:
                return {
                    "delivered": False,
                    "details": {},
                    "error": "Message not found"
                }
        except Exception as e:
            logger.error(f"Failed to get message status for {message_id}: {e}")
            return {
                "delivered": False,
                "details": {},
                "error": str(e)
            }

    def retry_undelivered_messages(self) -> Dict[str, Any]:
        """
        Check pending message IDs and resend any that haven't been marked delivered
        after the configurable timeout.

        Returns:
            Dict containing retry results:
            {
                "retried_count": int,
                "still_pending_count": int,
                "errors": list[str]
            }
        """
        if not self._pending_messages:
            return {
                "retried_count": 0,
                "still_pending_count": 0,
                "errors": []
            }

        retried_count = 0
        still_pending_count = 0
        errors = []
        current_time = time.time()
        messages_to_remove = []

        for message_id, sent_time in self._pending_messages.items():
            # Check if message has timed out
            if current_time - sent_time > self._message_timeout:
                # Check delivery status
                status = self.get_message_status(message_id)
                
                if status.get("delivered"):
                    logger.info(f"Message {message_id} was delivered, removing from pending")
                    messages_to_remove.append(message_id)
                else:
                    # Retry sending the message
                    logger.warning(f"Message {message_id} not delivered after timeout, retrying...")
                    
                    # Get original message details if available
                    details = status.get("details", {})
                    to_agent = details.get("to_agent")
                    message_type = details.get("message_type")
                    data = bytes.fromhex(details.get("data", "")) if details.get("data") else b""
                    
                    if to_agent and message_type and data:
                        try:
                            # Convert bytes32 message type back to string (simplified)
                            # In production, you'd need to store the original message type string
                            result = self.send_message(
                                to_agent=to_agent,
                                message_type="retry",  # Simplified - would need proper type mapping
                                data=data
                            )
                            
                            if result.get("success"):
                                retried_count += 1
                                messages_to_remove.append(message_id)
                                logger.info(f"Successfully retried message {message_id}")
                            else:
                                still_pending_count += 1
                                errors.append(f"Retry failed for message {message_id}: {result.get('error')}")
                        except Exception as e:
                            still_pending_count += 1
                            errors.append(f"Retry failed for message {message_id}: {str(e)}")
                    else:
                        still_pending_count += 1
                        errors.append(f"Cannot retry message {message_id}: insufficient details")
                        messages_to_remove.append(message_id)  # Remove if we can't retry
            else:
                still_pending_count += 1

        # Remove processed messages from pending list
        for message_id in messages_to_remove:
            del self._pending_messages[message_id]

        logger.info(
            f"Retry complete: {retried_count} retried, "
            f"{still_pending_count} still pending, {len(errors)} errors"
        )

        return {
            "retried_count": retried_count,
            "still_pending_count": still_pending_count,
            "errors": errors
        }

    # ─── Lifecycle management ───────────────────────────────────────────────

    def execute_cycle_with_timeout(self) -> Dict[str, Any]:
        """
        Execute one cycle with timeout protection.
        
        Returns:
            Dict containing cycle results or timeout error
        """
        try:
            with timeout_context(self._cycle_timeout):
                result = self.execute_cycle()
                self._increment_cycle()
                return result
        except TimeoutError as e:
            logger.error(f"{self.__class__.__name__} cycle timed out: {e}")
            return {
                "success": False,
                "action_taken": "none",
                "details": {},
                "error": f"Cycle timeout after {self._cycle_timeout} seconds"
            }
        except Exception as e:
            logger.error(f"{self.__class__.__name__} cycle failed: {e}", exc_info=True)
            return {
                "success": False,
                "action_taken": "none",
                "details": {},
                "error": str(e)
            }

    def start(self) -> None:
        """
        Start the agent. Calls initialize() and marks as running.
        """
        if self._is_initialized:
            logger.warning(f"{self.__class__.__name__} already initialized")
            return

        logger.info(f"Initializing {self.__class__.__name__}...")
        try:
            self.initialize()
            self._is_initialized = True
            self._is_running = True
            logger.info(f"{self.__class__.__name__} initialized successfully")
        except Exception as e:
            logger.critical(f"{self.__class__.__name__} initialization failed: {e}", exc_info=True)
            raise

    def stop(self) -> None:
        """
        Stop the agent. Calls shutdown() and marks as stopped.
        """
        if not self._is_running:
            logger.warning(f"{self.__class__.__name__} not running")
            return

        logger.info(f"Shutting down {self.__class__.__name__}...")
        try:
            self.shutdown()
            self._is_running = False
            logger.info(f"{self.__class__.__name__} shut down successfully")
        except Exception as e:
            logger.error(f"{self.__class__.__name__} shutdown failed: {e}", exc_info=True)

    # ─── Utility methods ─────────────────────────────────────────────────────

    @property
    def is_initialized(self) -> bool:
        """Whether the agent has been initialized."""
        return self._is_initialized

    @property
    def is_running(self) -> bool:
        """Whether the agent is currently running."""
        return self._is_running

    @property
    def cycle_count(self) -> int:
        """Number of cycles executed."""
        return self._cycle_count

    @property
    def messaging_enabled(self) -> bool:
        """Whether agent communication is enabled."""
        return self._messaging_enabled

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status for monitoring.
        
        Returns:
            Dict with health information:
            {
                "healthy": bool,
                "initialized": bool,
                "running": bool,
                "key_active": bool,
                "cycle_count": int,
                "messaging_enabled": bool,
                "agent_info": dict
            }
        """
        return {
            "healthy": self._is_initialized and self._is_running and self.key_manager.is_key_active,
            "initialized": self._is_initialized,
            "running": self._is_running,
            "key_active": self.key_manager.is_key_active,
            "cycle_count": self._cycle_count,
            "messaging_enabled": self._messaging_enabled,
            "agent_info": self.get_agent_info()
        }

    def _increment_cycle(self) -> None:
        """Increment the cycle counter."""
        self._cycle_count += 1
