"""
SAI Protocol SDK — Agent Discovery
----------------------------------
Agent discovery and communication helpers for the SAI Protocol.

Provides:
  - Agent discovery by type and capabilities
  - Agent messaging via AgentMessaging contract
  - Template discovery and deployment
  - Agent health monitoring
"""

import logging
import time
from typing import Dict, Any, List, Optional
from functools import lru_cache
from web3 import Web3

logger = logging.getLogger(__name__)


class AgentDiscovery:
    """
    Agent discovery and communication interface.
    
    Enables finding agents by type, capabilities, and sending messages
    between agents via the AgentMessaging contract.
    """

    def __init__(
        self,
        w3: Web3,
        messaging_address: Optional[str] = None,
        template_address: Optional[str] = None,
        registry_address: Optional[str] = None,
        enable_cache: bool = True,
        cache_ttl: int = 300
    ):
        """
        Initialize the AgentDiscovery.
        
        Args:
            w3: Web3 instance connected to the target chain
            messaging_address: Optional AgentMessaging contract address
            template_address: Optional AgentTemplate contract address
            registry_address: Optional AgentRegistry contract address
            enable_cache: Whether to enable caching for frequently accessed data
            cache_ttl: Cache time-to-live in seconds (default: 300 = 5 minutes)
        """
        self.w3 = w3
        self.messaging_address = Web3.to_checksum_address(messaging_address) if messaging_address else None
        self.template_address = Web3.to_checksum_address(template_address) if template_address else None
        self.registry_address = Web3.to_checksum_address(registry_address) if registry_address else None
        
        # Cache configuration
        self._enable_cache = enable_cache
        self._cache_ttl = cache_ttl
        self._cache: Dict[str, tuple[Any, float]] = {}  # {key: (value, timestamp)}
        
        # Load ABIs
        self._load_abis()
        
        # Initialize contracts
        if self.messaging_address:
            self.messaging = w3.eth.contract(
                address=self.messaging_address,
                abi=self.messaging_abi
            )
        
        if self.template_address:
            self.template = w3.eth.contract(
                address=self.template_address,
                abi=self.template_abi
            )
        
        if self.registry_address:
            self.registry = w3.eth.contract(
                address=self.registry_address,
                abi=self.registry_abi
            )
        
        logger.info("AgentDiscovery initialized")

    def _load_abis(self):
        """Load contract ABIs from embedded JSON."""
        # AgentMessaging ABI
        self.messaging_abi = [
            {
                "name": "registerEndpoint",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "supportedMessageTypes", "type": "bytes32[]"},
                    {"name": "messageFee", "type": "uint256"}
                ],
                "outputs": []
            },
            {
                "name": "sendMessage",
                "type": "function",
                "stateMutability": "payable",
                "inputs": [
                    {"name": "toAgent", "type": "address"},
                    {"name": "messageType", "type": "bytes32"},
                    {"name": "data", "type": "bytes"}
                ],
                "outputs": []
            },
            {
                "name": "markMessageDelivered",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [{"name": "messageId", "type": "uint256"}],
                "outputs": []
            },
            {
                "name": "getEndpoint",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "agent", "type": "address"}],
                "outputs": [
                    {"name": "soulAddress", "type": "address"},
                    {"name": "supportedMessageTypes", "type": "bytes32[]"},
                    {"name": "messageFee", "type": "uint256"},
                    {"name": "active", "type": "bool"},
                    {"name": "registeredAt", "type": "uint256"}
                ]
            },
            {
                "name": "getMessage",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "messageId", "type": "uint256"}],
                "outputs": [
                    {"name": "id", "type": "uint256"},
                    {"name": "fromAgent", "type": "address"},
                    {"name": "toAgent", "type": "address"},
                    {"name": "messageType", "type": "bytes32"},
                    {"name": "data", "type": "bytes"},
                    {"name": "timestamp", "type": "uint256"},
                    {"name": "paymentAmount", "type": "uint256"},
                    {"name": "delivered", "type": "bool"}
                ]
            },
            {
                "name": "getReceivedMessages",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "agent", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256[]"}]
            },
            {
                "name": "getSentMessages",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "agent", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256[]"}]
            },
            {
                "name": "supportsMessageType",
                "type": "function",
                "stateMutability": "view",
                "inputs": [
                    {"name": "agent", "type": "address"},
                    {"name": "messageType", "type": "bytes32"}
                ],
                "outputs": [{"name": "", "type": "bool"}]
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "messageId", "type": "uint256"},
                    {"indexed": True, "name": "fromAgent", "type": "address"},
                    {"indexed": True, "name": "toAgent", "type": "address"},
                    {"indexed": False, "name": "messageType", "type": "bytes32"},
                    {"indexed": False, "name": "timestamp", "type": "uint256"}
                ],
                "name": "MessageSent",
                "type": "event"
            }
        ]
        
        # AgentTemplate ABI
        self.template_abi = [
            {
                "name": "getTemplate",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "templateId", "type": "uint256"}],
                "outputs": [
                    {"name": "id", "type": "uint256"},
                    {"name": "creator", "type": "address"},
                    {"name": "name", "type": "string"},
                    {"name": "description", "type": "string"},
                    {"name": "agentType", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "capabilities", "type": "string[]"},
                    {"name": "configHash", "type": "string"},
                    {"name": "deploymentFee", "type": "uint256"},
                    {"name": "revenueShare", "type": "uint256"},
                    {"name": "totalDeployments", "type": "uint256"},
                    {"name": "totalRevenue", "type": "uint256"},
                    {"name": "active", "type": "bool"},
                    {"name": "createdAt", "type": "uint256"}
                ]
            },
            {
                "name": "getTemplatesByType",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "agentType", "type": "string"}],
                "outputs": [{"name": "", "type": "uint256[]"}]
            },
            {
                "name": "getTemplatesByCreator",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "creator", "type": "address"}],
                "outputs": [{"name": "", "type": "uint256[]"}]
            },
            {
                "name": "recordDeployment",
                "type": "function",
                "stateMutability": "payable",
                "inputs": [
                    {"name": "templateId", "type": "uint256"},
                    {"name": "soulAddress", "type": "address"}
                ],
                "outputs": []
            }
        ]
        
        # AgentRegistry ABI (simplified)
        self.registry_abi = [
            {
                "name": "getAgentsByType",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "agentType", "type": "string"}],
                "outputs": [{"name": "", "type": "address[]"}]
            },
            {
                "name": "isAgentActive",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "soulAddress", "type": "address"}],
                "outputs": [{"name": "", "type": "bool"}]
            }
        ]
    
    def _get_cache_key(self, method: str, *args) -> str:
        """Generate a cache key for a method call."""
        return f"{method}:{':'.join(str(arg) for arg in args)}"
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if not self._enable_cache:
            return None
        
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return value
            else:
                # Expired, remove from cache
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp."""
        if self._enable_cache:
            self._cache[key] = (value, time.time())
    
    def _clear_cache(self) -> None:
        """Clear all cached values."""
        self._cache.clear()
    
    def _execute_transaction_with_retry(
        self,
        tx_func,
        account,
        max_retries: int = 3,
        base_delay: float = 1.0
    ) -> Dict[str, Any]:
        """
        Execute a transaction with retry logic and exponential backoff.
        
        Args:
            tx_func: Function that builds and returns the transaction
            account: Account object for signing
            max_retries: Maximum number of retry attempts
            base_delay: Base delay for exponential backoff in seconds
            
        Returns:
            Dict containing transaction details
        """
        from eth_account import Account
        
        for attempt in range(max_retries):
            try:
                # Build transaction
                tx = tx_func()
                
                # Sign and send
                signed = account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                
                # Wait for receipt
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt["status"] != 1:
                    raise RuntimeError(f"Transaction failed: {receipt}")
                
                return {
                    "success": True,
                    "tx_hash": tx_hash.hex(),
                    "block_number": receipt["blockNumber"]
                }
            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Transaction failed after {max_retries} retries: {e}") from e
                
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Transaction attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

    def discover_agents_by_type(self, agent_type: str) -> List[str]:
        """
        Discover agents by type using the registry.
        
        Args:
            agent_type: Type of agent to search for
            
        Returns:
            List of agent addresses
        """
        if not self.registry_address:
            logger.warning("Registry address not set")
            return []
        
        cache_key = self._get_cache_key("discover_agents_by_type", agent_type)
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result
        
        try:
            result = self.registry.functions.getAgentsByType(agent_type).call()
            self._set_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Failed to discover agents by type: {e}")
            return []

    def discover_templates_by_type(self, agent_type: str) -> List[int]:
        """
        Discover templates by agent type.
        
        Args:
            agent_type: Type of agent templates to search for
            
        Returns:
            List of template IDs
        """
        if not self.template_address:
            logger.warning("Template address not set")
            return []
        
        cache_key = self._get_cache_key("discover_templates_by_type", agent_type)
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result
        
        try:
            result = self.template.functions.getTemplatesByType(agent_type).call()
            self._set_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Failed to discover templates by type: {e}")
            return []

    def get_template_details(self, template_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a template.
        
        Args:
            template_id: ID of the template
            
        Returns:
            Dict containing template details or None if not found
        """
        if not self.template_address:
            logger.warning("Template address not set")
            return None
        
        cache_key = self._get_cache_key("get_template_details", template_id)
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result
        
        try:
            template_info = self.template.functions.getTemplate(template_id).call()
            result = {
                "id": template_info[0],
                "creator": template_info[1],
                "name": template_info[2],
                "description": template_info[3],
                "agent_type": template_info[4],
                "version": template_info[5],
                "capabilities": template_info[6],
                "config_hash": template_info[7],
                "deployment_fee": template_info[8],
                "revenue_share": template_info[9],
                "total_deployments": template_info[10],
                "total_revenue": template_info[11],
                "active": template_info[12],
                "created_at": template_info[13]
            }
            self._set_cache(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"Failed to get template details: {e}")
            return None

    def register_messaging_endpoint(
        self,
        supported_message_types: List[str],
        message_fee: int,
        private_key: str,
        gas_limit: int = 200_000
    ) -> Dict[str, Any]:
        """
        Register agent endpoint for messaging.
        
        Args:
            supported_message_types: List of supported message types
            message_fee: Fee required to send messages
            private_key: Private key for signing
            gas_limit: Gas limit for the transaction
            
        Returns:
            Dict containing transaction details
        """
        if not self.messaging_address:
            raise ValueError("Messaging address not set")
        
        from eth_account import Account
        account = Account.from_key(private_key)
        
        # Convert message types to bytes32
        message_types_bytes = [Web3.keccak(text=mt) for mt in supported_message_types]
        
        def build_tx():
            return self.messaging.functions.registerEndpoint(
                message_types_bytes,
                message_fee
            ).build_transaction({
                "from": account.address,
                "nonce": self.w3.eth.get_transaction_count(account.address),
                "gas": gas_limit,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id
            })
        
        result = self._execute_transaction_with_retry(build_tx, account)
        logger.info("Messaging endpoint registered successfully")
        
        return result

    def send_message(
        self,
        to_agent: str,
        message_type: str,
        data: bytes,
        private_key: str,
        payment: int = 0,
        gas_limit: int = 300_000
    ) -> Dict[str, Any]:
        """
        Send a message to another agent.

        Args:
            to_agent: Recipient agent address
            message_type: Type of message
            data: Message payload
            private_key: Private key for signing
            payment: Optional payment amount
            gas_limit: Gas limit for the transaction

        Returns:
            Dict containing transaction details and message ID
        """
        if not self.messaging_address:
            raise ValueError("Messaging address not set")

        from eth_account import Account
        account = Account.from_key(private_key)

        # Convert message type to bytes32
        message_type_bytes = Web3.keccak(text=message_type)

        def build_tx():
            return self.messaging.functions.sendMessage(
                Web3.to_checksum_address(to_agent),
                message_type_bytes,
                data
            ).build_transaction({
                "from": account.address,
                "nonce": self.w3.eth.get_transaction_count(account.address),
                "gas": gas_limit,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.w3.eth.chain_id,
                "value": payment
            })

        # Execute transaction and get receipt
        tx_hash = None
        receipt = None
        
        for attempt in range(3):
            try:
                tx = build_tx()
                signed = account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt["status"] != 1:
                    raise RuntimeError(f"Transaction failed: {receipt}")
                
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"Transaction failed after 3 retries: {e}") from e
                logger.warning(f"Transaction attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(1.0 * (2 ** attempt))

        # Extract message ID from MessageSent event
        message_id = 0
        if receipt and "logs" in receipt:
            for log in receipt["logs"]:
                # Check if this is a MessageSent event
                if log.get("topics") and len(log["topics"]) >= 1:
                    # MessageSent event signature: keccak256("MessageSent(uint256,address,address,bytes32,uint256)")
                    event_signature = Web3.keccak(text="MessageSent(uint256,address,address,bytes32,uint256)").hex()
                    if log["topics"][0].hex() == event_signature:
                        # messageId is the first indexed parameter (topics[1])
                        message_id = int(log["topics"][1].hex(), 16)
                        logger.info(f"Extracted message ID from event: {message_id}")
                        break

        logger.info(f"Message sent to {to_agent}, message ID: {message_id}")

        return {
            "success": True,
            "tx_hash": tx_hash.hex() if tx_hash else None,
            "block_number": receipt["blockNumber"] if receipt else None,
            "message_id": message_id
        }

    def get_received_messages(self, agent_address: str) -> List[int]:
        """
        Get messages received by an agent.
        
        Args:
            agent_address: Address of the agent
            
        Returns:
            List of message IDs
        """
        if not self.messaging_address:
            logger.warning("Messaging address not set")
            return []
        
        try:
            return self.messaging.functions.getReceivedMessages(
                Web3.to_checksum_address(agent_address)
            ).call()
        except Exception as e:
            logger.error(f"Failed to get received messages: {e}")
            return []

    def get_message_details(self, message_id: int) -> Optional[Dict[str, Any]]:
        """
        Get details of a specific message.
        
        Args:
            message_id: ID of the message
            
        Returns:
            Dict containing message details or None if not found
        """
        if not self.messaging_address:
            logger.warning("Messaging address not set")
            return None
        
        try:
            msg = self.messaging.functions.getMessage(message_id).call()
            return {
                "id": msg[0],
                "from_agent": msg[1],
                "to_agent": msg[2],
                "message_type": msg[3].hex(),
                "data": msg[4].hex(),
                "timestamp": msg[5],
                "payment_amount": msg[6],
                "delivered": msg[7]
            }
        except Exception as e:
            logger.error(f"Failed to get message details: {e}")
            return None
