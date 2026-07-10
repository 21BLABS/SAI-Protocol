"""
SAI Protocol SDK — Soul Manager
-------------------------------
Python SDK for managing SAI Protocol souls (autonomous agents).

Provides:
  - Soul deployment via SoulFactory
  - Soul registration in AgentRegistry
  - Soul state monitoring
  - Key rotation management
  - Guardian operations
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from web3 import Web3
from eth_account import Account

logger = logging.getLogger(__name__)


class SoulManager:
    """
    High-level interface for managing SAI Protocol souls.
    
    Handles deployment, registration, monitoring, and lifecycle management
    of autonomous agents on the SAI Protocol.
    """

    def __init__(
        self,
        w3: Web3,
        factory_address: str,
        registry_address: Optional[str] = None,
        private_key: Optional[str] = None
    ):
        """
        Initialize the SoulManager.
        
        Args:
            w3: Web3 instance connected to the target chain
            factory_address: SoulFactory contract address
            registry_address: Optional AgentRegistry contract address
            private_key: Optional private key for signing transactions
        """
        self.w3 = w3
        self.factory_address = Web3.to_checksum_address(factory_address)
        self.registry_address = Web3.to_checksum_address(registry_address) if registry_address else None
        self.private_key = private_key
        self.account = Account.from_key(private_key) if private_key else None
        
        # Load ABIs
        self._load_abis()
        
        # Initialize contracts
        self.factory = w3.eth.contract(
            address=self.factory_address,
            abi=self.factory_abi
        )
        
        if self.registry_address:
            self.registry = w3.eth.contract(
                address=self.registry_address,
                abi=self.registry_abi
            )
        
        logger.info(f"SoulManager initialized for factory at {self.factory_address}")

    def _load_abis(self):
        """Load contract ABIs from embedded JSON."""
        # SoulFactory ABI
        self.factory_abi = [
            {
                "name": "spawnSoul",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "composeHash", "type": "bytes32"},
                    {"name": "humanGuardian", "type": "address"}
                ],
                "outputs": [{"name": "soul", "type": "address"}]
            },
            {
                "name": "souls",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "", "type": "bytes32"}],
                "outputs": [{"name": "", "type": "address"}]
            },
            {
                "name": "totalSoulsSpawned",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"name": "", "type": "uint256"}]
            },
            {
                "name": "SoulSpawned",
                "type": "event",
                "inputs": [
                    {"name": "soulAddress", "type": "address", "indexed": True},
                    {"name": "rootId", "type": "bytes32", "indexed": True},
                    {"name": "creator", "type": "address", "indexed": True},
                    {"name": "modelHash", "type": "bytes32", "indexed": False}
                ],
                "anonymous": False
            }
        ]
        
        # AgentRegistry ABI
        self.registry_abi = [
            {
                "name": "registerAgent",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "soulAddress", "type": "address"},
                    {"name": "rootId", "type": "bytes32"},
                    {"name": "agentType", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "description", "type": "string"},
                    {"name": "capabilities", "type": "string[]"},
                    {"name": "author", "type": "address"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "requiresPaymaster", "type": "bool"}
                ],
                "outputs": []
            },
            {
                "name": "getAgent",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "soulAddress", "type": "address"}],
                "outputs": [
                    {"name": "soulAddress", "type": "address"},
                    {"name": "rootId", "type": "bytes32"},
                    {"name": "agentType", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "description", "type": "string"},
                    {"name": "capabilities", "type": "string[]"},
                    {"name": "author", "type": "address"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "requiresPaymaster", "type": "bool"},
                    {"name": "registeredAt", "type": "uint256"},
                    {"name": "active", "type": "bool"}
                ]
            },
            {
                "name": "getAgentByRootId",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"name": "rootId", "type": "bytes32"}],
                "outputs": [
                    {"name": "soulAddress", "type": "address"},
                    {"name": "rootId", "type": "bytes32"},
                    {"name": "agentType", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "description", "type": "string"},
                    {"name": "capabilities", "type": "string[]"},
                    {"name": "author", "type": "address"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "requiresPaymaster", "type": "bool"},
                    {"name": "registeredAt", "type": "uint256"},
                    {"name": "active", "type": "bool"}
                ]
            },
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

    def spawn_soul(
        self,
        compose_hash: str,
        human_guardian: str,
        gas_limit: int = 500_000
    ) -> Dict[str, Any]:
        """
        Spawn a new soul via SoulFactory.
        
        Args:
            compose_hash: The compose hash for the TEE environment
            human_guardian: Address of the human guardian (can be address(0))
            gas_limit: Gas limit for the transaction
            
        Returns:
            Dict containing transaction details and soul address
        """
        if not self.account:
            raise ValueError("Private key required for soul deployment")
        
        compose_hash_bytes = Web3.to_bytes(hexstr=compose_hash)
        guardian_address = Web3.to_checksum_address(human_guardian)
        
        logger.info(f"Spawning soul with compose hash {compose_hash}")
        
        # Estimate gas with 20% buffer
        try:
            estimated_gas = self.factory.functions.spawnSoul(
                compose_hash_bytes,
                guardian_address
            ).estimate_gas({"from": self.account.address})
            gas_limit = int(estimated_gas * 1.2)  # 20% buffer
            logger.info(f"Estimated gas: {estimated_gas}, using limit: {gas_limit}")
        except Exception as e:
            logger.warning(f"Gas estimation failed: {e}, using default limit")
            gas_limit = gas_limit
        
        # Build transaction
        tx = self.factory.functions.spawnSoul(
            compose_hash_bytes,
            guardian_address
        ).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": gas_limit,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.w3.eth.chain_id
        })
        
        # Sign and send
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        
        # Wait for receipt
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt["status"] != 1:
            raise RuntimeError(f"Soul deployment failed: {receipt}")
        
        # Get soul address from event logs using proper ABI decoding
        soul_address = None
        for log in receipt["logs"]:
            if log["address"] == self.factory_address:
                # Decode SoulSpawned event
                event = self.factory.events.SoulSpawned().process_log(log)
                soul_address = event["args"]["soulAddress"]
                break
        
        if not soul_address:
            raise RuntimeError("Failed to extract soul address from transaction logs")
        
        logger.info(f"Soul spawned at {soul_address}")
        
        return {
            "success": True,
            "soul_address": soul_address,
            "tx_hash": tx_hash.hex(),
            "block_number": receipt["blockNumber"]
        }

    def register_agent(
        self,
        soul_address: str,
        root_id: str,
        agent_type: str,
        version: str,
        name: str,
        description: str,
        capabilities: List[str],
        chain_id: int,
        requires_paymaster: bool = False,
        gas_limit: int = 500_000
    ) -> Dict[str, Any]:
        """
        Register an agent in the AgentRegistry.
        
        Args:
            soul_address: SoulAccount address
            root_id: Root identity from SoulFactory
            agent_type: Type of agent (trading, governance, service, etc.)
            version: Semantic version
            name: Human-readable name
            description: What this agent does
            capabilities: List of capabilities
            chain_id: Target blockchain
            requires_paymaster: Whether agent needs paymaster
            gas_limit: Gas limit for the transaction
            
        Returns:
            Dict containing transaction details
        """
        if not self.account:
            raise ValueError("Private key required for agent registration")
        
        if not self.registry_address:
            raise ValueError("Registry address not set")
        
        soul_addr = Web3.to_checksum_address(soul_address)
        root_id_bytes = Web3.to_bytes(hexstr=root_id)
        
        logger.info(f"Registering agent {name} ({agent_type})")
        
        # Estimate gas with 20% buffer
        try:
            estimated_gas = self.registry.functions.registerAgent(
                soul_addr,
                root_id_bytes,
                agent_type,
                version,
                name,
                description,
                capabilities,
                self.account.address,
                chain_id,
                requires_paymaster
            ).estimate_gas({"from": self.account.address})
            gas_limit = int(estimated_gas * 1.2)  # 20% buffer
            logger.info(f"Estimated gas: {estimated_gas}, using limit: {gas_limit}")
        except Exception as e:
            logger.warning(f"Gas estimation failed: {e}, using default limit")
            gas_limit = gas_limit
        
        # Build transaction
        tx = self.registry.functions.registerAgent(
            soul_addr,
            root_id_bytes,
            agent_type,
            version,
            name,
            description,
            capabilities,
            self.account.address,
            chain_id,
            requires_paymaster
        ).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": gas_limit,
            "gasPrice": self.w3.eth.gas_price,
            "chainId": self.w3.eth.chain_id
        })
        
        # Sign and send
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        
        # Wait for receipt
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if receipt["status"] != 1:
            raise RuntimeError(f"Agent registration failed: {receipt}")
        
        logger.info(f"Agent registered successfully")
        
        return {
            "success": True,
            "tx_hash": tx_hash.hex(),
            "block_number": receipt["blockNumber"]
        }

    def get_agent(self, soul_address: str) -> Dict[str, Any]:
        """
        Get agent information from the registry.
        
        Args:
            soul_address: SoulAccount address
            
        Returns:
            Dict containing agent information
        """
        if not self.registry_address:
            raise ValueError("Registry address not set")
        
        soul_addr = Web3.to_checksum_address(soul_address)
        
        try:
            agent_info = self.registry.functions.getAgent(soul_addr).call()
            return {
                "soul_address": agent_info[0],
                "root_id": agent_info[1].hex(),
                "agent_type": agent_info[2],
                "version": agent_info[3],
                "name": agent_info[4],
                "description": agent_info[5],
                "capabilities": agent_info[6],
                "author": agent_info[7],
                "chain_id": agent_info[8],
                "requires_paymaster": agent_info[9],
                "registered_at": agent_info[10],
                "active": agent_info[11]
            }
        except Exception as e:
            logger.error(f"Failed to get agent info: {e}")
            return {"error": str(e)}

    def get_agents_by_type(self, agent_type: str) -> List[str]:
        """
        Get all agents of a specific type.
        
        Args:
            agent_type: Type of agent
            
        Returns:
            List of soul addresses
        """
        if not self.registry_address:
            raise ValueError("Registry address not set")
        
        try:
            return self.registry.functions.getAgentsByType(agent_type).call()
        except Exception as e:
            logger.error(f"Failed to get agents by type: {e}")
            return []

    def is_agent_active(self, soul_address: str) -> bool:
        """
        Check if an agent is registered and active.
        
        Args:
            soul_address: SoulAccount address
            
        Returns:
            True if agent is active
        """
        if not self.registry_address:
            return False
        
        try:
            return self.registry.functions.isAgentActive(
                Web3.to_checksum_address(soul_address)
            ).call()
        except Exception:
            return False

    def get_total_souls(self) -> int:
        """
        Get total number of spawned souls.
        
        Returns:
            Total soul count
        """
        try:
            return self.factory.functions.totalSoulsSpawned().call()
        except Exception as e:
            logger.error(f"Failed to get total souls: {e}")
            return 0
