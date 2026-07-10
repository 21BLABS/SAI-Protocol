// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
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

contract SoulFactoryDeploy is Script, Test {
    using MessageHashUtils for bytes32;

    SoulFactory public factory;
    SoulAccount public soulImpl;
    MockDstackVerifier public mockVerifier;
    
    address dev = makeAddr("dev");
    bytes32 constant TEST_COMPOSE_HASH = keccak256("sai-agent-trader:v1.0");

    // We parse the hex string dynamically to completely bypass EIP-55 checksum constraints
    address public ENTRY_POINT;
    address public PHALA_DSTACK_VERIFIER;

    function setUp() public {
        ENTRY_POINT = vm.parseAddress("0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789");
        PHALA_DSTACK_VERIFIER = vm.parseAddress("0x481ce1a6EEC3016d1E61725B1527D73Df1c393a5");
    }

    /**
     * @notice Live On-Chain Broadcast Execution Block
     */
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(deployerPrivateKey);

        SoulAccount realSoulImpl = new SoulAccount(ENTRY_POINT, PHALA_DSTACK_VERIFIER);
        console.log("SUCCESS: Real SoulAccount Impl deployed at:", address(realSoulImpl));

        SoulFactory realFactory = new SoulFactory(address(realSoulImpl));
        console.log("SUCCESS: Real SoulFactory deployed at:", address(realFactory));

        vm.stopBroadcast();
    }

    // ====================== LOCAL INTEGRATION TEST ======================
    function test_FullSoulLifecycle() public {
        // 1. Deploy test environment
        mockVerifier = new MockDstackVerifier();
        soulImpl = new SoulAccount(ENTRY_POINT, address(mockVerifier));
        factory = new SoulFactory(address(soulImpl));

        vm.startPrank(dev);

        // 2. Spawn Soul
        address soulAddr = factory.spawnSoul(TEST_COMPOSE_HASH, dev); 
        SoulAccount soul = SoulAccount(payable(soulAddr));

        console.log("Local Sandbox: Soul spawned at address:", soulAddr);

        // 3. Mock the enclave key generation inside the hardware
        uint256 enclavePrivateKey = 0xA11CE; // Secure mock private key
        address enclaveKey = vm.addr(enclavePrivateKey); // Derive matching public key address
        mockVerifier.registerMockKey(enclaveKey, TEST_COMPOSE_HASH);
        
        vm.warp(block.timestamp + 1 days);
        
        // 4. Rotate key (establish sovereignty)
        bytes memory dummyProof = hex"";
        soul.rotateEnclaveKey(enclaveKey, 24 hours, dummyProof);

        assertEq(soul.activeEnclaveKey(), enclaveKey);
        assertGt(soul.enclaveKeyExpiration(), block.timestamp);

      // 5. Simulate valid UserOp execution path
        SoulAccount.UserOperation memory op = SoulAccount.UserOperation({
            sender: soulAddr,
            nonce: 0,
            initCode: "",
            callData: abi.encodeWithSignature("execute(address,uint256,bytes)", dev, 0, ""),
            callGasLimit: 100_000,
            verificationGasLimit: 100_000,
            preVerificationGas: 50_000,
            maxFeePerGas: 1 gwei,
            maxPriorityFeePerGas: 1 gwei,
            paymasterAndData: "",
            signature: "" 
        });

        bytes32 userOpHash = keccak256(abi.encode(op)); 
        bytes32 ethSignedHash = userOpHash.toEthSignedMessageHash();
        
        // 🔑
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(enclavePrivateKey, ethSignedHash); 
        op.signature = abi.encodePacked(r, s, v);

        // 6. Execute Validation from the authorized EntryPoint
        vm.stopPrank();
        vm.prank(ENTRY_POINT);
        uint256 validation = soul.validateUserOp(op, userOpHash, 0);
        assertEq(validation, 0); 

        console.log("===> Full protocol lifecycle test successfully passed!");
    }
}
