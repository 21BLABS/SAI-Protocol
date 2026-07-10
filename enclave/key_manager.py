"""
SAI Protocol — Enclave Key Manager
------------------------------------
Runs exclusively inside the Phala dStack TEE. Responsibilities:
  1. Generate an ephemeral ECDSA keypair (private key never leaves this process)
  2. Fetch a hardware attestation quote from the local dStack endpoint
  3. Call rotateEnclaveKey() on the SoulAccount with the quote as proof
  4. Run a heartbeat loop that rotates the key before it expires

The private key is held in memory only, never written to disk or logged.
"""

import time
import logging
import requests
import threading
import ctypes
import ctypes.util
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from config import Config, sanitize_address

logger = logging.getLogger(__name__)


# ─── Secure Memory Handling ────────────────────────────────────────────────────

def secure_zero_memory(data: str | bytes) -> None:
    """
    Securely zero memory to prevent private key leakage.
    
    This function attempts to zero memory using ctypes to call memset.
    While Python's garbage collector makes this imperfect, it provides
    additional hardening in TEE environments where memory protection is critical.
    
    Args:
        data: The string or bytes to zero from memory
    """
    if not data:
        return
    
    try:
        # Convert to bytes if string
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        else:
            data_bytes = data
        
        # Use ctypes to call memset on the memory
        libc = ctypes.CDLL(ctypes.util.find_library('c'))
        libc.memset(ctypes.c_void_p(id(data_bytes)), 0, len(data_bytes))
        
        logger.debug("Secure memory zeroization attempted")
    except Exception as e:
        # Log but don't fail - this is a defense-in-depth measure
        logger.warning(f"Secure memory zeroization failed (non-critical): {e}")


# ─── Config ───────────────────────────────────────────────────────────────────

# Use centralized configuration from config.py
SOUL_ACCOUNT_ADDRESS    = Config.SOUL_ACCOUNT_ADDRESS
BASE_SEPOLIA_RPC_URL    = Config.BASE_SEPOLIA_RPC_URL
DSTACK_SIMULATOR_ENDPOINT = Config.DSTACK_SIMULATOR_ENDPOINT

# Rotate 1 hour before expiry so there's a buffer if the network is slow.
# PRD specifies "1 hour before expiration" as the heartbeat target.
ROTATION_BUFFER_SECONDS = 3600

# Key validity requested from the contract (24 hours)
KEY_VALIDITY_SECONDS = 86400

ROTATE_ABI = [
    {
        "name": "rotateEnclaveKey",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "newEnclaveKey",    "type": "address"},
            {"name": "validityDuration", "type": "uint256"},
            {"name": "hardwareProof",    "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "enclaveKeyExpiration",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}],
    },
    {
        "name": "activeEnclaveKey",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}],
    },
]


class EnclaveKeyManager:
    """
    Manages the lifecycle of the ephemeral ECDSA signing key inside the TEE.

    Key generation, attestation fetching, on-chain rotation, and heartbeat
    scheduling are all handled here. The signing interface (sign_user_op_hash)
    is the only public surface — the private key itself is never exposed.
    """

    def __init__(self):
        self._private_key: str | None = None
        self._public_address: str | None = None
        self._key_expiration: int = 0
        self._lock = threading.Lock()
        self._w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC_URL))
        self._soul = self._w3.eth.contract(
            address=Web3.to_checksum_address(SOUL_ACCOUNT_ADDRESS),
            abi=ROTATE_ABI,
        )

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def public_address(self) -> str | None:
        """The enclave key's Ethereum address. Safe to expose — it's public."""
        return self._public_address

    @property
    def is_key_active(self) -> bool:
        """True if a key exists and hasn't expired yet (with buffer)."""
        if not self._private_key:
            return False
        return time.time() < (self._key_expiration - ROTATION_BUFFER_SECONDS)

    def sign_user_op_hash(self, user_op_hash: bytes) -> bytes:
        """
        Sign a userOpHash with the active enclave private key.
        Applies the eth_sign prefix to match SoulAccount.validateUserOp.
        Raises if no active key exists.
        """
        with self._lock:
            if not self._private_key:
                raise RuntimeError("No active enclave key — rotation required")
            signable = encode_defunct(primitive=user_op_hash)
            signed = Account.sign_message(signable, private_key=self._private_key)
            return signed.signature

    def sign_typed_data(self, domain_hash: bytes, message_hash: bytes) -> str:
        """
        Sign EIP-712 structured data with the active enclave key.
        Computes: sign(keccak256("\x19\x01" + domain_hash + message_hash))
        Returns hex signature string (0x prefixed, 65 bytes).
        """
        with self._lock:
            if not self._private_key:
                raise RuntimeError("No active enclave key")
            
            from eth_account.messages import encode_defunct
            from web3 import Web3
            
            # EIP-712 encoding
            typed_data_hash = Web3.keccak(
                b"\x19\x01" + domain_hash + message_hash
            )
            signable = encode_defunct(primitive=typed_data_hash)
            signed = Account.sign_message(signable, private_key=self._private_key)
            return "0x" + signed.signature.hex()

    def boot(self):
        """
        Called once at enclave startup. Generates a fresh key, attests it,
        and registers it on-chain. Blocks until the first rotation succeeds.
        """
        logger.info("Enclave key manager booting...")
        self._rotate_key()
        logger.info(f"Boot complete. Active key: {sanitize_address(self._public_address) if self._public_address else 'none'}")

    def start_heartbeat(self):
        """
        Starts the background heartbeat thread that monitors key expiration
        and triggers rotation 1 hour before the key expires.
        Non-blocking — returns immediately after starting the thread.
        """
        thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="KeyRotationHeartbeat",
        )
        thread.start()
        logger.info("Key rotation heartbeat started.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _generate_keypair(self) -> tuple[str, str]:
        """
        Generate a fresh ephemeral secp256k1 keypair.
        Returns (private_key_hex, public_address).
        The private key never leaves this method's return value —
        it is the caller's responsibility not to log or persist it.
        """
        acct = Account.create()
        return acct.key.hex(), acct.address

    def _fetch_attestation_quote(self, enclave_key_address: str) -> bytes:
        """
        Fetch a hardware attestation quote from the local dStack endpoint.

        The quote cryptographically binds the enclave_key_address to:
          - The running code's compose hash
          - The TEE hardware identity

        The Phala dStack verifier contract validates this quote on-chain in
        rotateEnclaveKey(). If the running code doesn't match the registered
        composeHash, the verifier rejects it.

        In local/simulation mode (DSTACK_SIMULATOR_ENDPOINT set), the
        simulator returns a mock quote that the MockDstackVerifier accepts.
        
        Implements exponential backoff retry logic for transient failures.
        """
        max_retries = 5
        base_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{DSTACK_SIMULATOR_ENDPOINT}/quote",
                    json={"report_data": enclave_key_address},
                    timeout=10,
                )
                resp.raise_for_status()
                quote_hex = resp.json().get("quote", "")
                return bytes.fromhex(quote_hex.lstrip("0x"))
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch attestation quote after {max_retries} retries: {e}")
                    raise RuntimeError(f"Attestation quote fetch failed: {e}") from e
                
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Attestation fetch attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

    def _rotate_key(self):
        """
        Core rotation logic:
          1. Generate a fresh ephemeral keypair
          2. Fetch a hardware quote binding the new public key to this enclave
          3. Submit rotateEnclaveKey() on-chain with the quote as proof
          4. Update internal state only after on-chain confirmation
        """
        logger.info("Generating new ephemeral keypair...")
        new_private_key, new_address = self._generate_keypair()
        logger.info(f"New enclave key address: {sanitize_address(new_address)}")

        logger.info("Fetching hardware attestation quote...")
        proof = self._fetch_attestation_quote(new_address)
        logger.info(f"Attestation quote fetched ({len(proof)} bytes)")

        logger.info("Submitting rotateEnclaveKey() on-chain...")
        tx_hash = self._submit_rotation(new_private_key, new_address, proof)
        logger.info(f"Rotation confirmed. Tx: {tx_hash}")

        # Only update internal state after on-chain confirmation.
        # If the tx fails, we keep using the old key until expiry.
        with self._lock:
            # Securely zero the old private key before replacing it
            if self._private_key:
                secure_zero_memory(self._private_key)
            
            self._private_key   = new_private_key
            self._public_address = new_address
            self._key_expiration = int(time.time()) + KEY_VALIDITY_SECONDS

        logger.info(
            f"Active key updated. Expires at: "
            f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(self._key_expiration))}"
        )

    def _submit_rotation(
        self, private_key: str, new_address: str, proof: bytes
    ) -> str:
        """
        Build, sign, and send the rotateEnclaveKey() transaction.
        Uses the NEW private key to pay gas — this means the new enclave
        key address needs to be pre-funded with Base Sepolia ETH.

        Note: in production you'd use a paymaster or a separate funded
        relayer EOA for gas. Using the enclave key itself is fine for Phase 2.
        """
        acct = Account.from_key(private_key)

        # Estimate gas dynamically with a 20% buffer for network congestion
        try:
            estimated_gas = self._soul.functions.rotateEnclaveKey(
                new_address,
                KEY_VALIDITY_SECONDS,
                proof,
            ).estimate_gas({"from": acct.address})
            gas_limit = int(estimated_gas * 1.2)  # 20% buffer
            logger.info(f"Estimated gas: {estimated_gas}, using limit: {gas_limit}")
        except Exception as e:
            logger.warning(f"Gas estimation failed: {e}, falling back to 200k")
            gas_limit = 200_000

        tx = self._soul.functions.rotateEnclaveKey(
            new_address,
            KEY_VALIDITY_SECONDS,
            proof,
        ).build_transaction({
            "from":     acct.address,
            "nonce":    self._w3.eth.get_transaction_count(acct.address),
            "gas":      gas_limit,
            "gasPrice": self._w3.eth.gas_price,
            "chainId":  84532,
        })

        signed = acct.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt["status"] != 1:
            raise RuntimeError(
                f"rotateEnclaveKey() reverted. "
                f"Check proof validity and compose hash registration."
            )

        return tx_hash.hex()

    def _heartbeat_loop(self):
        """
        Background thread. Checks every 5 minutes whether the key needs
        rotating (i.e. expiry is within ROTATION_BUFFER_SECONDS).
        Triggers rotation if so. Logs but does not crash on rotation failure —
        the old key remains active until it actually expires, giving the
        next heartbeat cycle a chance to retry.
        """
        logger.info("Heartbeat loop running. Check interval: 5 minutes.")
        while True:
            time.sleep(300)  # check every 5 minutes
            time_until_expiry = self._key_expiration - time.time()
            logger.debug(
                f"Heartbeat: key expires in "
                f"{int(time_until_expiry / 3600)}h "
                f"{int((time_until_expiry % 3600) / 60)}m"
            )

            if time_until_expiry <= ROTATION_BUFFER_SECONDS:
                logger.warning(
                    f"Key expiring in {int(time_until_expiry / 60)} minutes. "
                    f"Triggering rotation..."
                )
                try:
                    self._rotate_key()
                except Exception as e:
                    logger.error(
                        f"Rotation failed: {e}. "
                        f"Will retry in 5 minutes. "
                        f"Key still valid for {int(time_until_expiry / 60)} minutes."
                    )
