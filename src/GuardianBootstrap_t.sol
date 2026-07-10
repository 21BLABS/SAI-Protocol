// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/SoulFactory.sol";
import "../src/SoulAccount.sol";

contract MockDstackVerifier {
    mapping(address => bytes32) public registeredKeys;

    function verifyAppAttestation(
        bytes calldata,
        address derivedEnclaveKey,
        bytes32 expectedComposeHash
    ) external view returns (bool) {
        return registeredKeys[derivedEnclaveKey] == expectedComposeHash;
    }

    function registerMockKey(address key, bytes32 composeHash) external {
        registeredKeys[key] = composeHash;
    }
}

contract GuardianBootstrapTest is Test {
    SoulFactory public factory;
    SoulAccount public soulImpl;
    MockDstackVerifier public mockVerifier;

    address ENTRY_POINT = makeAddr("entryPoint");
    address randomCaller = makeAddr("randomCaller");
    bytes32 constant TEST_COMPOSE_HASH = keccak256("sai-agent-trader:v1.0");

    function setUp() public {
        mockVerifier = new MockDstackVerifier();
        soulImpl = new SoulAccount(ENTRY_POINT, address(mockVerifier));
        factory = new SoulFactory(address(soulImpl));
    }

    /// @notice Before the fix, this reverted forever: no msg.sender could
    /// ever equal address(0), so a guardian-less soul could never rotate.
    function test_BootstrapWithNoGuardian_AnyoneCanSubmitValidProof() public {
        // Spawn a fully sovereign soul: no human guardian.
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, address(0));
        SoulAccount soul = SoulAccount(payable(soulAddr));

        uint256 enclavePrivateKey = 0xA11CE;
        address enclaveKey = vm.addr(enclavePrivateKey);
        mockVerifier.registerMockKey(enclaveKey, TEST_COMPOSE_HASH);

        // A random, unrelated address submits the proof on the agent's behalf.
        vm.prank(randomCaller);
        soul.rotateEnclaveKey(enclaveKey, 24 hours, hex"");

        assertEq(soul.activeEnclaveKey(), enclaveKey, "key should be set via bootstrap path");
    }

    /// @notice An invalid proof must still fail even during bootstrap -
    /// the open caller set is not an open security check.
    function test_BootstrapWithNoGuardian_InvalidProofStillReverts() public {
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, address(0));
        SoulAccount soul = SoulAccount(payable(soulAddr));

        address unregisteredKey = makeAddr("unregistered");

        vm.prank(randomCaller);
        vm.expectRevert("SoulAccount: Hardware attestation failed");
        soul.rotateEnclaveKey(unregisteredKey, 24 hours, hex"");
    }

    /// @notice After the first key is set, the open-caller bootstrap window
    /// closes - only guardian or active key can rotate from then on.
    function test_AfterFirstRotation_RandomCallerLockedOut() public {
        address guardian = makeAddr("guardian");
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, guardian);
        SoulAccount soul = SoulAccount(payable(soulAddr));

        uint256 key1Priv = 0xA11CE;
        address key1 = vm.addr(key1Priv);
        mockVerifier.registerMockKey(key1, TEST_COMPOSE_HASH);
        soul.rotateEnclaveKey(key1, 24 hours, hex"");

        uint256 key2Priv = 0xB0B;
        address key2 = vm.addr(key2Priv);
        mockVerifier.registerMockKey(key2, TEST_COMPOSE_HASH);

        vm.warp(block.timestamp + 6 minutes);
        vm.prank(randomCaller);
        vm.expectRevert("SoulAccount: Unauthorized rotation");
        soul.rotateEnclaveKey(key2, 24 hours, hex"");
    }

    /// @notice Core circuit-breaker behavior: triggerEmergency actually
    /// disables the account, and the active-key bypass cannot do it (only
    /// the guardian can).
    function test_TriggerEmergency_FreezesAccount() public {
        address guardian = makeAddr("guardian");
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, guardian);
        SoulAccount soul = SoulAccount(payable(soulAddr));

        uint256 enclavePrivateKey = 0xA11CE;
        address enclaveKey = vm.addr(enclavePrivateKey);
        mockVerifier.registerMockKey(enclaveKey, TEST_COMPOSE_HASH);
        soul.rotateEnclaveKey(enclaveKey, 24 hours, hex"");
        assertEq(soul.activeEnclaveKey(), enclaveKey);

        // Non-guardian cannot trigger emergency.
        vm.prank(randomCaller);
        vm.expectRevert("SoulAccount: Only guardian");
        soul.triggerEmergency("suspicious activity");

        // Guardian schedules emergency.
        vm.prank(guardian);
        soul.triggerEmergency("suspicious activity");

        // Fast forward past emergency delay and execute
        vm.warp(block.timestamp + 1 hours + 1);
        soul.executeEmergency();

        assertEq(soul.activeEnclaveKey(), address(0), "key should be wiped after emergency");
        assertEq(soul.enclaveKeyExpiration(), 0, "expiration should be wiped after emergency");
    }

    /// @notice After a freeze, recovery is immediate - no cooldown wait
    /// required, since the cooldown only rate-limits churn on an already
    /// active key, not recovery into a disabled one.
    function test_RecoveryAfterEmergency_IsImmediate() public {
        address guardian = makeAddr("guardian");
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, guardian);
        SoulAccount soul = SoulAccount(payable(soulAddr));

        uint256 key1Priv = 0xA11CE;
        address key1 = vm.addr(key1Priv);
        mockVerifier.registerMockKey(key1, TEST_COMPOSE_HASH);
        soul.rotateEnclaveKey(key1, 24 hours, hex"");

        vm.prank(guardian);
        soul.triggerEmergency("compromise suspected");
        
        // Fast forward past emergency delay and execute
        vm.warp(block.timestamp + 1 hours + 1);
        soul.executeEmergency();
        assertEq(soul.activeEnclaveKey(), address(0));

        uint256 key2Priv = 0xB0B;
        address key2 = vm.addr(key2Priv);
        mockVerifier.registerMockKey(key2, TEST_COMPOSE_HASH);

        // No vm.warp here - recovery should work in the very same block
        // the freeze happened in, proving the cooldown bypass works.
        vm.prank(randomCaller); // anyone can deliver the recovery proof
        soul.rotateEnclaveKey(key2, 24 hours, hex"");

        assertEq(soul.activeEnclaveKey(), key2, "soul should recover immediately, no cooldown wait");
    }

    /// @notice Cooldown still applies normally once a key is active again -
    /// the bypass only exists for the disabled/bootstrap state.
    function test_CooldownStillAppliesAfterRecovery() public {
        address guardian = makeAddr("guardian");
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, guardian);
        SoulAccount soul = SoulAccount(payable(soulAddr));

        uint256 key1Priv = 0xA11CE;
        address key1 = vm.addr(key1Priv);
        mockVerifier.registerMockKey(key1, TEST_COMPOSE_HASH);
        soul.rotateEnclaveKey(key1, 24 hours, hex"");

        vm.prank(guardian);
        soul.triggerEmergency("compromise suspected");
        
        // Fast forward past emergency delay and execute
        vm.warp(block.timestamp + 1 hours + 1);
        soul.executeEmergency();

        uint256 key2Priv = 0xB0B;
        address key2 = vm.addr(key2Priv);
        mockVerifier.registerMockKey(key2, TEST_COMPOSE_HASH);
        soul.rotateEnclaveKey(key2, 24 hours, hex""); // immediate recovery

        // Now try to rotate again right away - this is a normal, active-key
        // rotation, so the cooldown should still block it.
        uint256 key3Priv = 0xC0C0;
        address key3 = vm.addr(key3Priv);
        mockVerifier.registerMockKey(key3, TEST_COMPOSE_HASH);

        vm.expectRevert("SoulAccount: Rotation cooldown active");
        soul.rotateEnclaveKey(key3, 24 hours, hex"");
    }
}
