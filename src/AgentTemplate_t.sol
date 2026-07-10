// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/AgentTemplate.sol";

contract AgentTemplateTest is Test {
    AgentTemplate public templateContract;
    
    address public owner = address(0x1);
    address public creator1 = address(0x2);
    address public creator2 = address(0x3);
    address public deployer = address(0x4);
    
    string[] public tradingCapabilities;
    string[] public governanceCapabilities;
    
    function setUp() public {
        vm.startPrank(owner);
        templateContract = new AgentTemplate();
        // Grant CREATOR_ROLE to test accounts
        templateContract.grantRole(templateContract.CREATOR_ROLE(), creator1);
        templateContract.grantRole(templateContract.CREATOR_ROLE(), creator2);
        vm.stopPrank();
        
        // Setup capabilities
        tradingCapabilities = new string[](3);
        tradingCapabilities[0] = "market_data_ingestion";
        tradingCapabilities[1] = "strategy_evaluation";
        tradingCapabilities[2] = "trade_execution";
        
        governanceCapabilities = new string[](2);
        governanceCapabilities[0] = "proposal_analysis";
        governanceCapabilities[1] = "voting";
    }
    
    function test_RegisterTemplate_Success() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot v1",
            "Autonomous trading agent for prediction markets",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash_123",
            0.1 ether,
            80 // 80% revenue share to creator
        );
        
        vm.stopPrank();
        
        (uint256 id, address creator, string memory name, string memory description, string memory agentType, string memory version, 
         string[] memory capabilities, string memory configHash, uint256 deploymentFee, uint256 revenueShare, 
         uint256 totalDeployments, uint256 totalRevenue, bool active, uint256 createdAt) = templateContract.getTemplateFields(1);
        
        assertEq(id, 1);
        assertEq(creator, creator1);
        assertEq(name, "Trading Bot v1");
        assertEq(agentType, "trading");
        assertEq(version, "1.0.0");
        assertEq(deploymentFee, 0.1 ether);
        assertEq(revenueShare, 80);
        assertEq(totalDeployments, 0);
        assertEq(totalRevenue, 0);
        assertTrue(active);
    }
    
    function test_RegisterTemplate_InvalidRevenueShare_Reverts() public {
        vm.startPrank(creator1);
        
        vm.expectRevert("Revenue share cannot exceed 100");
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            101 // Invalid revenue share
        );
        
        vm.stopPrank();
    }
    
    function test_RegisterTemplate_EmptyName_Reverts() public {
        vm.startPrank(creator1);
        
        vm.expectRevert("Name cannot be empty");
        templateContract.registerTemplate(
            "",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
    }
    
    function test_UpdateTemplate_Success() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot v1",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        templateContract.updateTemplate(1, "2.0.0", 0.2 ether, false);
        
        vm.stopPrank();
        
       (, , , , , string memory version, , , uint256 deploymentFee, , , , bool active, ) = templateContract.getTemplateFields(1);
        
        assertEq(version, "2.0.0");
        assertEq(deploymentFee, 0.2 ether);
        assertFalse(active);
    }
    
    function test_UpdateTemplate_NotCreator_Reverts() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
        
        vm.startPrank(creator2);
        vm.expectRevert("Not authorized to update template");
        templateContract.updateTemplate(1, "2.0.0", 0.2 ether, true);
        vm.stopPrank();
    }
    
    function test_RecordDeployment_Success() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
        
        vm.startPrank(deployer);
        vm.deal(deployer, 1 ether);
        
        address soulAddress = address(0x5);
        templateContract.recordDeployment{value: 0.1 ether}(1, soulAddress);
        
        vm.stopPrank();
        
        (uint256 templateId, address deployer_, address soulAddress_, , uint256 feePaid) = templateContract.getDeploymentFields(1);
        
        assertEq(templateId, 1);
        assertEq(deployer_, deployer);
        assertEq(soulAddress_, soulAddress);
        assertEq(feePaid, 0.1 ether);
        
        (, , , , , , , , , , uint256 totalDeployments, uint256 totalRevenue, , ) = templateContract.getTemplateFields(1);
        
        assertEq(totalDeployments, 1);
        assertEq(totalRevenue, 0.1 ether);
    }
    
    function test_RecordDeployment_InsufficientFee_Reverts() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
        
        vm.startPrank(deployer);
        vm.deal(deployer, 1 ether);
        
        address soulAddress = address(0x5);
        vm.expectRevert("Insufficient deployment fee");
        templateContract.recordDeployment{value: 0.05 ether}(1, soulAddress);
        
        vm.stopPrank();
    }
    
    function test_RecordDeployment_InactiveTemplate_Reverts() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        templateContract.updateTemplate(1, "1.0.0", 0.1 ether, false);
        
        vm.stopPrank();
        
        vm.startPrank(deployer);
        vm.deal(deployer, 1 ether);
        
        address soulAddress = address(0x5);
        vm.expectRevert("Template is not active");
        templateContract.recordDeployment{value: 0.1 ether}(1, soulAddress);
        
        vm.stopPrank();
    }
    
    function test_RecordDeployment_DuplicateSoul_Reverts() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
        
        vm.startPrank(deployer);
        vm.deal(deployer, 1 ether);
        
        address soulAddress = address(0x5);
        templateContract.recordDeployment{value: 0.1 ether}(1, soulAddress);
        
        vm.expectRevert("Soul already deployed from a template");
        templateContract.recordDeployment{value: 0.1 ether}(1, soulAddress);
        
        vm.stopPrank();
    }
    
    function test_GetTemplatesByCreator_Success() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        templateContract.registerTemplate(
            "Governance Bot",
            "Description",
            "governance",
            "1.0.0",
            governanceCapabilities,
            "config_hash",
            0.05 ether,
            70
        );
        
        vm.stopPrank();
        
        uint256[] memory templateIds = templateContract.getTemplatesByCreator(creator1);
        
        assertEq(templateIds.length, 2);
        assertEq(templateIds[0], 1);
        assertEq(templateIds[1], 2);
    }
    
    function test_GetTemplatesByType_Success() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot 1",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        templateContract.registerTemplate(
            "Trading Bot 2",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
        
        uint256[] memory templateIds = templateContract.getTemplatesByType("trading");
        
        assertEq(templateIds.length, 2);
        assertEq(templateIds[0], 1);
        assertEq(templateIds[1], 2);
    }
    
    function test_GetDeploymentBySoul_Success() public {
        vm.startPrank(creator1);
        
        templateContract.registerTemplate(
            "Trading Bot",
            "Description",
            "trading",
            "1.0.0",
            tradingCapabilities,
            "config_hash",
            0.1 ether,
            80
        );
        
        vm.stopPrank();
        
        vm.startPrank(deployer);
        vm.deal(deployer, 1 ether);
        
        address soulAddress = address(0x5);
        templateContract.recordDeployment{value: 0.1 ether}(1, soulAddress);
        
        (uint256 templateId, , address soulAddress_, , ) = templateContract.getDeploymentBySoulFields(soulAddress);
        
        assertEq(templateId, 1);
        assertEq(soulAddress_, soulAddress);
        
        vm.stopPrank();
    }
    
    function test_SetPlatformFeePercentage_Success() public {
        vm.startPrank(owner);
        
        templateContract.setPlatformFeePercentage(15);
        
        assertEq(templateContract.platformFeePercentage(), 15);
        
        vm.stopPrank();
    }
    
    function test_SetPlatformFeePercentage_Unauthorized_Reverts() public {
        vm.startPrank(creator1);
        
        vm.expectRevert();
        templateContract.setPlatformFeePercentage(15);
        
        vm.stopPrank();
    }
    
    function test_SetPlatformFeePercentage_InvalidPercentage_Reverts() public {
        vm.startPrank(owner);
        
        vm.expectRevert("Percentage cannot exceed 100");
        templateContract.setPlatformFeePercentage(101);
        
        vm.stopPrank();
    }
}
