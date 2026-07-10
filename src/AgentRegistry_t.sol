// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/AgentRegistry.sol";

contract AgentRegistryTest is Test {
    AgentRegistry public registry;
    
    address public owner = address(0x1);
    address public author1 = address(0x2);
    address public author2 = address(0x3);
    address public soul1 = address(0x4);
    address public soul2 = address(0x5);
    address public soul3 = address(0x6);
    
    bytes32 public rootId1 = keccak256("root1");
    bytes32 public rootId2 = keccak256("root2");
    bytes32 public rootId3 = keccak256("root3");
    
    string[] public tradingCapabilities;
    string[] public governanceCapabilities;
    
    function setUp() public {
        vm.startPrank(owner);
        registry = new AgentRegistry();
        vm.stopPrank();
        
        // Setup capabilities
        tradingCapabilities = new string[](4);
        tradingCapabilities[0] = "market_data_ingestion";
        tradingCapabilities[1] = "strategy_evaluation";
        tradingCapabilities[2] = "trade_execution";
        tradingCapabilities[3] = "risk_management";
        
        governanceCapabilities = new string[](3);
        governanceCapabilities[0] = "proposal_analysis";
        governanceCapabilities[1] = "voting";
        governanceCapabilities[2] = "delegation_management";
    }
    
    function test_RegisterAgent_Success() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.stopPrank();
        
        // Verify registration
        (
            address soulAddress,
            bytes32 rootId,
            string memory agentType,
            string memory version,
            string memory name,
            string memory description,
            string[] memory capabilities,
            address author,
            uint256 chainId,
            bool requiresPaymaster,
            uint256 registeredAt,
            bool active
        ) = registry.getAgentFields(soul1);
        
        assertEq(soulAddress, soul1);
        assertEq(rootId, rootId1);
        assertEq(agentType, "trading");
        assertEq(version, "1.0.0");
        assertEq(name, "SAI Trading Agent");
        assertEq(author, author1);
        assertEq(chainId, 84532);
        assertEq(requiresPaymaster, false);
        assertTrue(active);
        assertTrue(registeredAt > 0);
    }
    
    function test_RegisterAgent_DuplicateAddress_Reverts() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.expectRevert("Agent already registered");
        registry.registerAgent(
            soul1,
            rootId2,
            "governance",
            "1.0.0",
            "Governance Agent",
            "Autonomous governance agent",
            governanceCapabilities,
            author1,
            84532,
            true
        );
        
        vm.stopPrank();
    }
    
    function test_RegisterAgent_DuplicateRootId_Reverts() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.expectRevert("Root ID already registered");
        registry.registerAgent(
            soul2,
            rootId1,
            "governance",
            "1.0.0",
            "Governance Agent",
            "Autonomous governance agent",
            governanceCapabilities,
            author1,
            84532,
            true
        );
        
        vm.stopPrank();
    }
    
    function test_GetAgentByRootId_Success() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.stopPrank();
        
        (address soulAddress, , , , , , , , , , , ) = registry.getAgentByRootIdFields(rootId1);
        assertEq(soulAddress, soul1);
    }
    
    function test_GetAgentByRootId_NotFound_Reverts() public {
        vm.expectRevert("Agent not found");
        registry.getAgentByRootId(keccak256("nonexistent"));
    }
    
    function test_GetAgentsByType_Success() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "Trading Agent 1",
            "Description",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        registry.registerAgent(
            soul2,
            rootId2,
            "trading",
            "1.0.0",
            "Trading Agent 2",
            "Description",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.stopPrank();
        
        address[] memory tradingAgents = registry.getAgentsByType("trading");
        assertEq(tradingAgents.length, 2);
        assertEq(tradingAgents[0], soul1);
        assertEq(tradingAgents[1], soul2);
    }
    
    function test_UpdateAgent_Success() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        registry.updateAgent(soul1, "2.0.0", false);
        
        vm.stopPrank();
        
        (, , , string memory version, , , , , , , , bool active) = registry.getAgentFields(soul1);
        assertEq(version, "2.0.0");
        assertFalse(active);
    }
    
    function test_UpdateAgent_Unauthorized_Reverts() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.stopPrank();
        
        vm.startPrank(author2);
        vm.expectRevert("Unauthorized");
        registry.updateAgent(soul1, "2.0.0", false);
        vm.stopPrank();
    }
    
    function test_DeactivateAgent_Success() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        registry.deactivateAgent(soul1);
        
        vm.stopPrank();
        
        (, , , , , , , , , , , bool active) = registry.getAgentFields(soul1);
        assertFalse(active);
    }
    
    function test_DeactivateAgent_Unauthorized_Reverts() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.stopPrank();
        
        vm.startPrank(author2);
        vm.expectRevert("Unauthorized");
        registry.deactivateAgent(soul1);
        vm.stopPrank();
    }
    
    function test_IsAgentActive_True() public {
        vm.startPrank(author1);
        
        registry.registerAgent(
            soul1,
            rootId1,
            "trading",
            "1.0.0",
            "SAI Trading Agent",
            "Autonomous trading agent",
            tradingCapabilities,
            author1,
            84532,
            false
        );
        
        vm.stopPrank();
        
        assertTrue(registry.isAgentActive(soul1));
    }
    
    function test_IsAgentActive_False() public {
        assertFalse(registry.isAgentActive(soul1));
    }
    
    function test_BatchRegisterAgents_Success() public {
        address[] memory souls = new address[](2);
        souls[0] = soul1;
        souls[1] = soul2;
        
        bytes32[] memory rootIds = new bytes32[](2);
        rootIds[0] = rootId1;
        rootIds[1] = rootId2;
        
        string[] memory agentTypes = new string[](2);
        agentTypes[0] = "trading";
        agentTypes[1] = "governance";
        
        string[] memory versions = new string[](2);
        versions[0] = "1.0.0";
        versions[1] = "1.0.0";
        
        string[] memory names = new string[](2);
        names[0] = "Trading Agent";
        names[1] = "Governance Agent";
        
        string[] memory descriptions = new string[](2);
        descriptions[0] = "Trading";
        descriptions[1] = "Governance";
        
        string[][] memory capabilities = new string[][](2);
        capabilities[0] = tradingCapabilities;
        capabilities[1] = governanceCapabilities;
        
        address[] memory authors = new address[](2);
        authors[0] = author1;
        authors[1] = author1;
        
        uint256[] memory chainIds = new uint256[](2);
        chainIds[0] = 84532;
        chainIds[1] = 84532;
        
        bool[] memory requiresPaymasters = new bool[](2);
        requiresPaymasters[0] = false;
        requiresPaymasters[1] = true;
        
        vm.startPrank(author1);
        registry.batchRegisterAgents(
            souls,
            rootIds,
            agentTypes,
            versions,
            names,
            descriptions,
            capabilities,
            authors,
            chainIds,
            requiresPaymasters
        );
        vm.stopPrank();
        
        assertEq(registry.totalAgents(), 2);
        assertTrue(registry.isAgentActive(soul1));
        assertTrue(registry.isAgentActive(soul2));
    }
    
    function test_BatchRegisterAgents_ArrayLengthMismatch_Reverts() public {
        address[] memory souls = new address[](2);
        bytes32[] memory rootIds = new bytes32[](1);
        
        vm.startPrank(author1);
        vm.expectRevert("Array length mismatch");
        registry.batchRegisterAgents(
            souls,
            rootIds,
            new string[](2),
            new string[](2),
            new string[](2),
            new string[](2),
            new string[][](2),
            new address[](2),
            new uint256[](2),
            new bool[](2)
        );
        vm.stopPrank();
    }
}
