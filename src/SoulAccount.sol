// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol"; // <--- ADD THIS LINE

interface IPhalaDstackVerifier {
    function verifyAppAttestation(
        bytes calldata attestationReport,
        address derivedEnclaveKey,
        bytes32 expectedComposeHash
    ) external view returns (bool);
}

contract SoulAccount is Initializable {
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    struct UserOperation {
        address sender;
        uint256 nonce;
        bytes initCode;
        bytes callData;
        uint256 callGasLimit;
        uint256 verificationGasLimit;
        uint256 preVerificationGas;
        uint256 maxFeePerGas;
        uint256 maxPriorityFeePerGas;
        bytes paymasterAndData;
        bytes signature;
    }

    bytes32 public rootId;
    bytes32 public expectedComposeHash;
    address public activeEnclaveKey;
    uint256 public enclaveKeyExpiration;
    uint256 public lastRotationTimestamp;
    address public immutable entryPoint;
    address public immutable dstackVerifier;
    address public humanGuardian;
    address public deployer;

    mapping(uint256 => bool) public usedNonces;
    uint256 public constant ROTATION_COOLDOWN = 5 minutes;
    uint256 public constant EMERGENCY_DELAY = 1 hours; // Time delay before emergency takes effect
    
    // Emergency activation state
    uint256 public emergencyScheduledAt;
    bytes32 public pendingEmergencyReason;
    bool public emergencyActive;

    event SoulInitialized(bytes32 indexed rootId, bytes32 indexed composeHash, address humanGuardian);
    event EnclaveRotated(address indexed newKey, uint256 expiresAt);
    event ExecutionEnforced(bytes32 indexed userOpHash, address indexed signer);
    event GuardianTriggered(address indexed guardian, bytes32 reason);
    event KeyExpirationWarning(address indexed enclaveKey, uint256 expiresAt);
    event EmergencyScheduled(address indexed guardian, bytes32 reason, uint256 effectiveAt);
    event EmergencyCancelled(address indexed guardian);

    modifier onlyEntryPoint() {
        require(msg.sender == entryPoint, "SoulAccount: Only EntryPoint");
        _;
    }

    constructor(address _entryPoint, address _dstackVerifier) {
        entryPoint = _entryPoint;
        dstackVerifier = _dstackVerifier;
    }

    function initialize(
        bytes32 _rootId,
        bytes32 _composeHash,
        address _humanGuardian,
        address _deployer
    ) external initializer {
        require(msg.sender == _deployer, "SoulAccount: Only deployer can initialize");
        deployer = _deployer;
        rootId = _rootId;
        expectedComposeHash = _composeHash;
        humanGuardian = _humanGuardian;
        emit SoulInitialized(_rootId, _composeHash, _humanGuardian);
    }

    function rotateEnclaveKey(
        address newEnclaveKey,
        uint256 validityDuration,
        bytes calldata hardwareProof
    ) external {
        // Bootstrap case: before any key has ever been set, the account has no
        // way to authorize itself and may have no guardian (fully sovereign
        // souls are spawned with humanGuardian == address(0) by design).
        // In that case the on-chain identity is established entirely by the
        // hardware attestation check below, not by msg.sender, so we allow
        // anyone to submit the first valid proof. Once a key is active, all
        // future rotations are locked down to the guardian or the current key.
        //
        // This is also the state triggerEmergency() puts the account into,
        // so a frozen soul recovers through this same bootstrap path. The
        // rotation cooldown exists to rate-limit *normal* key churn, not to
        // slow down recovery from a guardian-triggered freeze - a soul that
        // has just been deliberately disabled should be able to recover the
        // instant a valid proof exists, not be stuck waiting out a timer
        // that was designed for a different purpose. So the cooldown only
        // applies once a key is already active.
        bool isBootstrap = activeEnclaveKey == address(0);

        if (!isBootstrap) {
            require(
                block.timestamp >= lastRotationTimestamp + ROTATION_COOLDOWN,
                "SoulAccount: Rotation cooldown active"
            );
        }

        require(
            isBootstrap || msg.sender == humanGuardian || msg.sender == activeEnclaveKey,
            "SoulAccount: Unauthorized rotation"
        );

        bool isValid = IPhalaDstackVerifier(dstackVerifier).verifyAppAttestation(
            hardwareProof,
            newEnclaveKey,
            expectedComposeHash
        );
        require(isValid, "SoulAccount: Hardware attestation failed");

        activeEnclaveKey = newEnclaveKey;
        enclaveKeyExpiration = block.timestamp + validityDuration;
        lastRotationTimestamp = block.timestamp;

        emit EnclaveRotated(newEnclaveKey, enclaveKeyExpiration);
    }

    function validateUserOp(
        UserOperation calldata userOp,
        bytes32 userOpHash,
        uint256 missingAccountFunds
    ) external virtual onlyEntryPoint returns (uint256 validationData) {
        if (block.timestamp > enclaveKeyExpiration || activeEnclaveKey == address(0)) {
            return 1;
        }

        // Emit warning if key is expiring within 1 hour
        if (block.timestamp + 1 hours >= enclaveKeyExpiration) {
            emit KeyExpirationWarning(activeEnclaveKey, enclaveKeyExpiration);
        }

        bytes32 ethSignedMessageHash = userOpHash.toEthSignedMessageHash();
        address signer = ethSignedMessageHash.recover(userOp.signature);

        if (signer != activeEnclaveKey) {
            return 1;
        }

        if (usedNonces[userOp.nonce]) {
            return 1;
        }
        usedNonces[userOp.nonce] = true;

        if (missingAccountFunds > 0) {
            (bool success, ) = payable(msg.sender).call{value: missingAccountFunds}("");
            require(success, "SoulAccount: ETH transfer failed");
        }

        emit ExecutionEnforced(userOpHash, signer);
        return 0;
    }

    function execute(
        address dest,
        uint256 value,
        bytes calldata func
    ) external onlyEntryPoint {
        (bool success, ) = dest.call{value: value}(func);
        require(success, "SoulAccount: execute failed");
    }

    function deposit() external payable {
        (bool success, ) = payable(entryPoint).call{value: msg.value}("");
        require(success, "SoulAccount: deposit failed");
    }

    /**
     * @notice Guardian-only circuit breaker with time delay. Schedules an
     * emergency activation that takes effect after EMERGENCY_DELAY.
     * This provides a window for the guardian to cancel if the threat was
     * a false alarm, and gives the agent time to respond.
     * 
     * Once active, this invalidates the active enclave key so validateUserOp
     * starts rejecting every operation (see the expiry/zero-key check at the
     * top of validateUserOp). This is a freeze, not a kill: the agent can
     * recover by submitting a fresh attestation through rotateEnclaveKey once
     * the guardian's concern is resolved.
     */
    function triggerEmergency(bytes32 reason) external {
        require(msg.sender == humanGuardian, "SoulAccount: Only guardian");
        
        // Schedule emergency activation
        emergencyScheduledAt = block.timestamp;
        pendingEmergencyReason = reason;
        
        uint256 effectiveAt = block.timestamp + EMERGENCY_DELAY;
        emit EmergencyScheduled(msg.sender, reason, effectiveAt);
    }
    
    /**
     * @notice Cancel a scheduled emergency activation
     * @dev Only the guardian can cancel a scheduled emergency
     */
    function cancelEmergency() external {
        require(msg.sender == humanGuardian, "SoulAccount: Only guardian");
        require(emergencyScheduledAt > 0, "SoulAccount: No emergency scheduled");
        require(!emergencyActive, "SoulAccount: Emergency already active");
        
        emergencyScheduledAt = 0;
        pendingEmergencyReason = bytes32(0);
        
        emit EmergencyCancelled(msg.sender);
    }
    
    /**
     * @notice Execute a scheduled emergency activation
     * @dev Can be called by anyone after the delay has elapsed
     * This ensures the emergency takes effect even if guardian is unavailable
     */
    function executeEmergency() external {
        require(emergencyScheduledAt > 0, "SoulAccount: No emergency scheduled");
        require(!emergencyActive, "SoulAccount: Emergency already active");
        require(
            block.timestamp >= emergencyScheduledAt + EMERGENCY_DELAY,
            "SoulAccount: Emergency delay not elapsed"
        );
        
        // Activate emergency
        emergencyActive = true;
        activeEnclaveKey = address(0);
        enclaveKeyExpiration = 0;
        
        emit GuardianTriggered(humanGuardian, pendingEmergencyReason);
    }

    receive() external payable {}
}