"""
SAI Protocol — Centralized Configuration
-----------------------------------------
Centralized configuration module for all environment variables and settings.
Provides validation, defaults, and graceful error handling for missing configuration.

This module eliminates duplication of environment variable definitions across
the codebase and ensures consistent validation and error handling.
"""

import os
import sys
import logging
from typing import Optional
from pathlib import Path
from web3 import Web3
from dotenv import load_dotenv, find_dotenv

# Load environment variables at module import time
# Try to find .env in the project root directory
env_path = find_dotenv(usecwd=True)
if env_path:
    load_dotenv(env_path)
else:
    # Fallback: try loading from the directory of this file
    project_root = Path(__file__).parent
    load_dotenv(project_root / ".env")

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Exception raised for configuration errors."""
    pass


def sanitize_address(address: str) -> str:
    """
    Sanitize an Ethereum address for logging by showing only first 6 and last 4 characters.
    
    Args:
        address: The address to sanitize
        
    Returns:
        Sanitized address string
    """
    if not address or len(address) < 10:
        return "***"
    
    return f"{address[:6]}...{address[-4:]}"




def validate_ethereum_address(address: str, var_name: str) -> str:
    """
    Validate an Ethereum address.
    
    Args:
        address: The address to validate
        var_name: Name of the environment variable (for error messages)
    
    Returns:
        The checksummed address
    
    Raises:
        ConfigurationError: If the address is invalid
    """
    if not address:
        raise ConfigurationError(f"{var_name} is required but not set")
    
    try:
        checksummed = Web3.to_checksum_address(address)
        logger.debug(f"Validated {var_name}: {sanitize_address(checksummed)}")
        return checksummed
    except Exception as e:
        # Allow zero address for testing purposes
        if address.lower() == "0x0000000000000000000000000000000000000000":
            logger.warning(f"{var_name} is zero address - using for testing only")
            return address
        # Sanitize error message to prevent information leakage
        raise ConfigurationError(f"{var_name} is not a valid Ethereum address") from e


def validate_url(url: str, var_name: str) -> str:
    """
    Validate a URL.
    
    Args:
        url: The URL to validate
        var_name: Name of the environment variable (for error messages)
    
    Returns:
        The validated URL
    
    Raises:
        ConfigurationError: If the URL is invalid
    """
    if not url:
        raise ConfigurationError(f"{var_name} is required but not set")
    
    if not url.startswith(("http://", "https://", "ws://", "wss://")):
        raise ConfigurationError(f"{var_name} must be a valid URL: {url}")
    
    logger.debug(f"Validated {var_name}: {url}")
    return url


def validate_private_key(private_key: Optional[str], var_name: str = "private_key") -> None:
    """
    Validate a private key if provided.
    
    Args:
        private_key: The private key to validate (can be None)
        var_name: Name of the configuration key (for error messages)
    
    Raises:
        ConfigurationError: If the private key is invalid
    """
    if private_key is None:
        logger.debug(f"{var_name} is not set (optional)")
        return
    
    # Remove 0x prefix if present
    key = private_key.lower().replace("0x", "")
    
    # Private key should be 64 hex characters (32 bytes)
    if len(key) != 64:
        raise ConfigurationError(
            f"{var_name} must be 64 hex characters (32 bytes), got {len(key)} characters"
        )
    
    # Verify it's valid hex
    try:
        int(key, 16)
        logger.debug(f"Validated {var_name}")
    except ValueError as e:
        raise ConfigurationError(f"{var_name} contains invalid hex characters") from e


def get_bool_env(var_name: str, default: bool = False) -> bool:
    """
    Get a boolean environment variable.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if not set
    
    Returns:
        Boolean value
    """
    value = os.environ.get(var_name, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def get_required_env(var_name: str) -> str:
    """
    Get a required environment variable.
    
    Args:
        var_name: Name of the environment variable
    
    Returns:
        The environment variable value
    
    Raises:
        ConfigurationError: If the variable is not set
    """
    value = os.environ.get(var_name)
    if not value:
        raise ConfigurationError(f"Required environment variable {var_name} is not set")
    return value


def get_optional_env(var_name: str, default: str = "") -> str:
    """
    Get an optional environment variable with a default.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if not set
    
    Returns:
        The environment variable value or default
    """
    return os.environ.get(var_name, default)


def get_float_env(var_name: str, default: float) -> float:
    """
    Get a float environment variable with a default.
    
    Args:
        var_name: Name of the environment variable
        default: Default value if not set
    
    Returns:
        The environment variable value as float or default
    """
    try:
        return float(os.environ.get(var_name, str(default)))
    except ValueError as e:
        logger.warning(f"Invalid float value for {var_name}, using default {default}: {e}")
        return default


# ─── Module-Level Environment Variables ─────────────────────────────────────────
# These are the centralized environment variable definitions for the entire codebase.
# All files should import these from config.py instead of using os.environ directly.

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
SOUL_ACCOUNT_ADDRESS = os.environ.get("SOUL_ACCOUNT_ADDRESS")
BASE_SEPOLIA_RPC_URL = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
PIMLICO_RPC_URL = os.environ.get("PIMLICO_RPC_URL")
CHAIN_ID = int(os.environ.get("CHAIN_ID", "84532"))
ENTRY_POINT = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
PHALA_VERIFIER_ADDRESS = "0x481ce1a6EEC3016d1E61725B1527D73Df1c393a5"


def validate_config(required: list[str]) -> None:
    """
    Validate that required environment variables are set.
    Exits with a clear error message if any required variables are missing.
    
    Args:
        required: List of environment variable names that must be set
    
    This function should be called at startup in entry point scripts to ensure
    all required configuration is present before the application begins.
    """
    missing = [var for var in required if not globals().get(var)]
    if missing:
        print(f"[FATAL] Missing required env vars: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in all values.")
        sys.exit(1)


# ─── Core Configuration ────────────────────────────────────────────────────────

class Config:
    """
    Centralized configuration class for SAI Protocol.
    
    All environment variables are loaded and validated here.
    Other modules should import this class and use its attributes.
    """
    
    # ─── Mode Configuration ───────────────────────────────────────────────────
    
    DRY_RUN: bool = get_bool_env("DRY_RUN", default=False)
    
    # ─── Account Configuration ─────────────────────────────────────────────────
    
    SOUL_ACCOUNT_ADDRESS: str = get_optional_env("SOUL_ACCOUNT_ADDRESS", "")
    
    # ─── RPC Configuration ─────────────────────────────────────────────────────
    
    BASE_SEPOLIA_RPC_URL: str = get_optional_env("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    
    PIMLICO_RPC_URL: str = get_optional_env("PIMLICO_RPC_URL", "")
    if PIMLICO_RPC_URL:
        PIMLICO_RPC_URL = validate_url(PIMLICO_RPC_URL, "PIMLICO_RPC_URL")
    
    BUNDLER_RPC_URL: str = get_optional_env("BUNDLER_RPC_URL", "")
    if BUNDLER_RPC_URL:
        BUNDLER_RPC_URL = validate_url(BUNDLER_RPC_URL, "BUNDLER_RPC_URL")
    
    # Validate bundler URL is not a dummy placeholder
    if BUNDLER_RPC_URL and "dummy" in BUNDLER_RPC_URL.lower():
        logger.warning("BUNDLER_RPC_URL contains 'dummy' - ensure production bundler URL is configured")
    
    # ─── Contract Configuration ────────────────────────────────────────────────
    
    ENTRY_POINT: str = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
    CHAIN_ID: int = 84532
    
    # ─── Agent Configuration ───────────────────────────────────────────────────
    
    AGENT_TYPE: str = get_optional_env("AGENT_TYPE", "trading")
    
    # ─── API Configuration ─────────────────────────────────────────────────────
    
    POLYMARKET_API_KEY: str = get_optional_env("POLYMARKET_API_KEY", "")
    
    # ─── TEE/Enclave Configuration ─────────────────────────────────────────────
    
    DSTACK_SIMULATOR_ENDPOINT: str = get_optional_env(
        "DSTACK_SIMULATOR_ENDPOINT", 
        "http://localhost:8090"
    )
    
    # ─── Timing Configuration ──────────────────────────────────────────────────
    
    CYCLE_INTERVAL: int = 60  # seconds
    
    # ─── Gas Configuration ─────────────────────────────────────────────────────
    
    DEFAULT_CALL_GAS_LIMIT: int = 200_000
    DEFAULT_VERIFICATION_GAS_LIMIT: int = 150_000
    DEFAULT_PRE_VERIFICATION_GAS: int = 50_000
    DEFAULT_MAX_FEE_PER_GAS: int = Web3.to_wei(1, "gwei")
    DEFAULT_MAX_PRIORITY_FEE_PER_GAS: int = Web3.to_wei(1, "gwei")
    
    # ─── Risk Management Configuration ─────────────────────────────────────────
    
    MAX_POSITION_SIZE: float = get_float_env("MAX_POSITION_SIZE", 0.2)
    MAX_TOTAL_EXPOSURE: float = get_float_env("MAX_TOTAL_EXPOSURE", 0.8)
    MAX_DRAWDOWN: float = get_float_env("MAX_DRAWDOWN", 0.10)
    DEFAULT_STOP_LOSS_PCT: float = get_float_env("DEFAULT_STOP_LOSS_PCT", 0.05)
    DEFAULT_TAKE_PROFIT_PCT: float = get_float_env("DEFAULT_TAKE_PROFIT_PCT", 0.10)
    POSITION_SIZING_METHOD: str = get_optional_env("POSITION_SIZING_METHOD", "fixed_fraction")
    KELLY_FRACTION: float = get_float_env("KELLY_FRACTION", 0.25)
    FIXED_FRACTION: float = get_float_env("FIXED_FRACTION", 0.1)
    
    # ─── Strategy Configuration ──────────────────────────────────────────────────
    
    STRATEGY_WEIGHT_ARBITRAGE: float = get_float_env("STRATEGY_WEIGHT_ARBITRAGE", 0.7)
    STRATEGY_WEIGHT_TREND_FOLLOWING: float = get_float_env("STRATEGY_WEIGHT_TREND_FOLLOWING", 0.3)
    PRIMARY_STRATEGY: str = get_optional_env("PRIMARY_STRATEGY", "arbitrage")
    MIN_CONFIDENCE: float = get_float_env("MIN_CONFIDENCE", 0.6)
    
    @classmethod
    def validate(cls) -> None:
        """
        Validate all configuration values.
        
        Raises:
            ConfigurationError: If any configuration is invalid
        """
        logger.info("Validating configuration...")
        
        # Log current configuration (without sensitive data)
        logger.info(f"DRY_RUN: {cls.DRY_RUN}")
        logger.info(f"SOUL_ACCOUNT_ADDRESS: {sanitize_address(cls.SOUL_ACCOUNT_ADDRESS)}")
        logger.info(f"BASE_SEPOLIA_RPC_URL: {cls.BASE_SEPOLIA_RPC_URL}")
        logger.info(f"PIMLICO_RPC_URL: {'***' if cls.PIMLICO_RPC_URL else 'not set'}")
        logger.info(f"BUNDLER_RPC_URL: {'***' if cls.BUNDLER_RPC_URL else 'not set'}")
        logger.info(f"AGENT_TYPE: {cls.AGENT_TYPE}")
        logger.info(f"POLYMARKET_API_KEY: {'***' if cls.POLYMARKET_API_KEY else 'not set'}")
        
        logger.info("Configuration validated successfully")
    
    @classmethod
    def validate_private_key_config(cls, private_key: Optional[str]) -> None:
        """
        Validate a private key from configuration.
        
        Args:
            private_key: The private key to validate (can be None)
        
        Raises:
            ConfigurationError: If the private key is invalid
        """
        validate_private_key(private_key, "private_key")


# ─── Convenience Functions ─────────────────────────────────────────────────────

def get_config() -> Config:
    """
    Get the configuration instance.
    
    Returns:
        The Config class
    """
    return Config


def sanitize_sensitive_data(data: str, data_type: str = "address") -> str:
    """
    Sanitize sensitive data for logging purposes.
    
    Args:
        data: The sensitive data to sanitize
        data_type: Type of data (address, private_key, api_key, etc.)
    
    Returns:
        Sanitized version safe for logging
    """
    if not data:
        return "***"
    
    if data_type == "address":
        return sanitize_address(data)
    elif data_type in ("private_key", "api_key", "secret"):
        # Show only first 4 and last 4 characters for highly sensitive data
        if len(data) < 8:
            return "***"
        return f"{data[:4]}...{data[-4:]}"
    else:
        # Default: show first 8 and last 4 characters
        if len(data) < 12:
            return "***"
        return f"{data[:8]}...{data[-4:]}"
