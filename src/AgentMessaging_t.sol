// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/AgentMessaging.sol";

contract AgentMessagingTest is Test {
    AgentMessaging public messaging;
    
    address public owner = address(0x1);
    address public agent1 = address(0x2);
    address public agent2 = address(0x3);
    address public agent3 = address(0x4);
    
    bytes32[] public tradingMessageTypes;
    bytes32[] public governanceMessageTypes;
    
    bytes32 constant TRADE_SIGNAL = keccak256("TRADE_SIGNAL");
    bytes32 constant VOTE_REQUEST = keccak256("VOTE_REQUEST");
    
    function setUp() public {
        vm.startPrank(owner);
        messaging = new AgentMessaging();
        vm.stopPrank();
        
        // Setup message types
        tradingMessageTypes = new bytes32[](2);
        tradingMessageTypes[0] = TRADE_SIGNAL;
        tradingMessageTypes[1] = keccak256("MARKET_DATA");
        
        governanceMessageTypes = new bytes32[](2);
        governanceMessageTypes[0] = VOTE_REQUEST;
        governanceMessageTypes[1] = keccak256("PROPOSAL_ANALYSIS");
    }
    
    function test_RegisterEndpoint_Success() public {
        vm.startPrank(agent1);
        
        messaging.registerEndpoint(tradingMessageTypes, 0.1 ether);
        
        vm.stopPrank();
        
        (address soulAddress, bytes32[] memory supportedTypes, uint256 fee, bool active, ) = messaging.getEndpointFields(agent1);
        
        assertEq(soulAddress, agent1);
        assertEq(supportedTypes.length, 2);
        assertEq(supportedTypes[0], TRADE_SIGNAL);
        assertEq(fee, 0.1 ether);
        assertTrue(active);
    }
    
    function test_RegisterEndpoint_EmptyMessageTypes_Reverts() public {
        vm.startPrank(agent1);
        
        bytes32[] memory emptyTypes = new bytes32[](0);
        vm.expectRevert("Must support at least one message type");
        messaging.registerEndpoint(emptyTypes, 0.1 ether);
        
        vm.stopPrank();
    }
    
    function test_UpdateEndpoint_Success() public {
        vm.startPrank(agent1);
        
        messaging.registerEndpoint(tradingMessageTypes, 0.1 ether);
        messaging.updateEndpoint(governanceMessageTypes, 0.2 ether, false);
        
        vm.stopPrank();
        
        (, bytes32[] memory supportedTypes, uint256 fee, bool active, ) = messaging.getEndpointFields(agent1);
        
        assertEq(supportedTypes.length, 2);
        assertEq(supportedTypes[0], VOTE_REQUEST);
        assertEq(fee, 0.2 ether);
        assertFalse(active);
    }
    
    function test_UpdateEndpoint_NotRegistered_Reverts() public {
        vm.startPrank(agent1);
        
        vm.expectRevert("Endpoint not registered");
        messaging.updateEndpoint(governanceMessageTypes, 0.2 ether, true);
        
        vm.stopPrank();
    }
    
    function test_SendMessage_Success() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        bytes memory data = hex"1234";
        messaging.sendMessage(agent1, TRADE_SIGNAL, data);
        vm.stopPrank();
        
        uint256[] memory sent = messaging.getSentMessages(agent2);
        uint256[] memory received = messaging.getReceivedMessages(agent1);
        
        assertEq(sent.length, 1);
        assertEq(received.length, 1);
        assertEq(sent[0], received[0]);
        
        (uint256 id, address fromAgent, address toAgent, bytes32 messageType, bytes memory data_, , , ) = messaging.getMessageFields(sent[0]);
        assertEq(fromAgent, agent2);
        assertEq(toAgent, agent1);
        assertEq(messageType, TRADE_SIGNAL);
        assertEq(data_, data);
    }
    
    function test_SendMessage_SenderNotRegistered_Reverts() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        
        bytes memory data = hex"1234";
        vm.expectRevert("Sender not registered");
        messaging.sendMessage(agent1, TRADE_SIGNAL, data);
        
        vm.stopPrank();
    }
    
    function test_SendMessage_RecipientNotRegistered_Reverts() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        bytes memory data = hex"1234";
        vm.expectRevert("Recipient not registered");
        messaging.sendMessage(agent3, TRADE_SIGNAL, data);
        
        vm.stopPrank();
    }
    
    function test_SendMessage_RecipientInactive_Reverts() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        messaging.updateEndpoint(tradingMessageTypes, 0, false);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        bytes memory data = hex"1234";
        vm.expectRevert("Recipient endpoint inactive");
        messaging.sendMessage(agent1, TRADE_SIGNAL, data);
        
        vm.stopPrank();
    }
    
    function test_SendMessage_UnsupportedMessageType_Reverts() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(governanceMessageTypes, 0);
        
        bytes memory data = hex"1234";
        vm.expectRevert("Recipient doesn't support this message type");
        messaging.sendMessage(agent1, VOTE_REQUEST, data);
        
        vm.stopPrank();
    }
    
    function test_SendMessage_WithPayment_Success() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0.1 ether);
        vm.deal(agent2, 1 ether);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        uint256 balanceBefore = agent1.balance;
        bytes memory data = hex"1234";
        messaging.sendMessage{value: 0.1 ether}(agent1, TRADE_SIGNAL, data);
        vm.stopPrank();
        
        vm.startPrank(agent1);
        messaging.withdrawPayments();
        vm.stopPrank();
        
        assertEq(agent1.balance, balanceBefore + 0.1 ether);
    }
    
    function test_SendMessage_InsufficientPayment_Reverts() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0.1 ether);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        vm.deal(agent2, 1 ether);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        bytes memory data = hex"1234";
        vm.expectRevert("Insufficient payment");
        messaging.sendMessage{value: 0.05 ether}(agent1, TRADE_SIGNAL, data);
        
        vm.stopPrank();
    }
    
    function test_MarkMessageDelivered_Success() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        bytes memory data = hex"1234";
        messaging.sendMessage(agent1, TRADE_SIGNAL, data);
        
        uint256[] memory sent = messaging.getSentMessages(agent2);
        vm.stopPrank();
        
        vm.startPrank(agent1);
        messaging.markMessageDelivered(sent[0]);
        vm.stopPrank();
        
        (, , , , , , , bool delivered) = messaging.getMessageFields(sent[0]);
        assertTrue(delivered);
    }
    
    function test_MarkMessageDelivered_NotRecipient_Reverts() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        vm.startPrank(agent2);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        
        bytes memory data = hex"1234";
        messaging.sendMessage(agent1, TRADE_SIGNAL, data);
        vm.stopPrank();
        
        vm.startPrank(agent3);
        uint256[] memory sent = messaging.getSentMessages(agent2);
        vm.expectRevert("Not the recipient");
        messaging.markMessageDelivered(sent[0]);
        vm.stopPrank();
    }
    
    function test_SupportsMessageType_True() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        assertTrue(messaging.supportsMessageType(agent1, TRADE_SIGNAL));
    }
    
    function test_SupportsMessageType_False() public {
        vm.startPrank(agent1);
        messaging.registerEndpoint(tradingMessageTypes, 0);
        vm.stopPrank();
        
        assertFalse(messaging.supportsMessageType(agent1, VOTE_REQUEST));
    }
    
    function test_SetAgentRegistry_Success() public {
        vm.startPrank(owner);
        
        address newRegistry = address(0x5);
        messaging.setAgentRegistry(newRegistry);
        
        assertEq(messaging.agentRegistry(), newRegistry);
        vm.stopPrank();
    }
    
    function test_SetAgentRegistry_Unauthorized_Reverts() public {
        vm.startPrank(agent1);
        
        address newRegistry = address(0x5);
        vm.expectRevert();
        messaging.setAgentRegistry(newRegistry);
        
        vm.stopPrank();
    }
}
