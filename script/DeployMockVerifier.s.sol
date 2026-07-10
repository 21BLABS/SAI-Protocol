// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/MockDstackVerifier.sol";
import "../src/SoulFactory.sol";
import "../src/SoulAccount.sol";

contract DeployMockVerifier is Script {
    using MessageHashUtils for bytes32;

    MockDstackVerifier public mockVerifier;
    SoulAccount public soulImpl;
    SoulFactory public factory;
    
    address public ENTRY_POINT;
    bytes32 constant TEST_COMPOSE_HASH = keccak256("sai-agent-trader:v1.0");

    function setUp() public {
        ENTRY_POINT = vm.parseAddress("0x0000000071727De22E5E9d8BAf0edAc6f37da032");
    }

    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);
        
        vm.startBroadcast(deployerPrivateKey);

        // 1. Deploy mock verifier
        mockVerifier = new MockDstackVerifier();
        console.log("SUCCESS: MockDstackVerifier deployed at:", address(mockVerifier));

        // 2. Deploy SoulAccount with mock verifier
        soulImpl = new SoulAccount(ENTRY_POINT, address(mockVerifier));
        console.log("SUCCESS: SoulAccount Impl deployed at:", address(soulImpl));

        // 3. Deploy factory
        factory = new SoulFactory(address(soulImpl));
        console.log("SUCCESS: SoulFactory deployed at:", address(factory));

        // 4. Register the deployer's throwaway key in the mock verifier
        // This allows the throwaway key to be used as enclave key
        bytes32 composeHash = TEST_COMPOSE_HASH;
        mockVerifier.registerMockKey(deployer, composeHash);
        console.log("SUCCESS: Registered deployer key in mock verifier");

        // 5. Spawn SoulAccount proxy
        address soulProxy = factory.spawnSoul(composeHash, deployer);
        console.log("SUCCESS: SoulAccount proxy spawned at:", soulProxy);

        // 6. Deposit ETH to EntryPoint for gas payments
        SoulAccount soul = SoulAccount(payable(soulProxy));
        soul.deposit{value: 0.01 ether}();
        console.log("SUCCESS: Deposited 0.01 ETH to EntryPoint");

        vm.stopBroadcast();

        console.log("\n=== DEPLOYMENT SUMMARY ===");
        console.log("Mock Verifier:", address(mockVerifier));
        console.log("SoulAccount Impl:", address(soulImpl));
        console.log("SoulFactory:", address(factory));
        console.log("SoulAccount Proxy:", soulProxy);
        console.log("\nUpdate your .env with.");
        console.log("SOUL_ACCOUNT_ADDRESS=", soulProxy);
    }
}
