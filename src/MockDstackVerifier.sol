// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MockDstackVerifier
 * @notice Mock verifier for Phase 1 testing that accepts any proof
 * @dev This is a simplified version of the real Phala dStack verifier for testing purposes
 */
contract MockDstackVerifier {
    mapping(address => bytes32) public registeredKeys;

    /**
     * @notice Verify an app attestation
     * @dev In mock mode, this simply checks if the key is registered with the expected compose hash
     * @param derivedEnclaveKey The derived enclave key address
     * @param expectedComposeHash The expected compose hash
     * @return bool True if verification succeeds
     */
    function verifyAppAttestation(
        bytes calldata,
        address derivedEnclaveKey,
        bytes32 expectedComposeHash
    ) external view returns (bool) {
        return registeredKeys[derivedEnclaveKey] == expectedComposeHash;
    }

    /**
     * @notice Register a mock key for testing
     * @dev Only callable by the contract deployer in production, but open for testing
     * @param key The enclave key address to register
     * @param composeHash The compose hash to associate with the key
     */
    function registerMockKey(address key, bytes32 composeHash) external {
        registeredKeys[key] = composeHash;
    }

    /**
     * @notice Check if a key is registered
     * @param key The enclave key address to check
     * @return composeHash The compose hash if registered, or bytes32(0) if not
     */
    function getRegisteredKey(address key) external view returns (bytes32) {
        return registeredKeys[key];
    }
}
