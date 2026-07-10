"""
SAI Protocol SDK
----------------
Python SDK for interacting with the SAI Protocol autonomous agent foundation.

Provides high-level interfaces for:
  - Soul deployment and management
  - Agent registration and discovery
  - Agent-to-agent communication
  - Template marketplace
  - TEE integration
  - UserOperation building and signing
"""

from sdk.soul_manager import SoulManager
from sdk.agent_discovery import AgentDiscovery

__version__ = "0.2.0"
__all__ = ["SoulManager", "AgentDiscovery"]
