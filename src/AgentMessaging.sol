// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title AgentMessaging
 * @notice Agent-to-agent communication protocol for SAI Protocol
 * @dev Enables secure messaging between autonomous agents with discovery and routing
 * 
 * Features:
 * - Agent discovery by type and capabilities
 * - Secure message passing with authentication
 * - Message routing and delivery confirmation
 * - Payment integration for agent services
 */
contract AgentMessaging is Ownable, ReentrancyGuard {
    
    // Message structure
    struct Message {
        uint256 id;
        address fromAgent;
        address toAgent;
        bytes32 messageType;
        bytes data;
        uint256 timestamp;
        uint256 paymentAmount;
        bool delivered;
    }
    
    // Agent endpoint registration
    struct AgentEndpoint {
        address soulAddress;
        bytes32[] supportedMessageTypes;
        uint256 messageFee;        // Fee per message
        bool active;
        uint256 registeredAt;
    }
    
    // Mapping from agent address to endpoint info
    mapping(address => AgentEndpoint) public endpoints;
    
    // Mapping from message ID to message
    mapping(uint256 => Message) public messages;
    
    // Mapping from agent to their received message IDs
    mapping(address => uint256[]) public receivedMessages;
    
    // Mapping from agent to their sent message IDs
    mapping(address => uint256[]) public sentMessages;
    
    // Mapping from message type to array of agent addresses that support it
    mapping(bytes32 => address[]) public agentsByMessageType;
    
    // Escrow payments for pull payment pattern (prevents reentrancy)
    mapping(address => uint256) public _escrowPayments;
    
    // Message counter
    uint256 public messageCounter;
    
    // Maximum message size to prevent DoS attacks (10KB)
    uint256 public constant MAX_MESSAGE_SIZE = 10 * 1024;
    
    // Agent registry address for verification
    address public agentRegistry;
    
    // Events
    event EndpointRegistered(
        address indexed soulAddress,
        bytes32[] supportedMessageTypes,
        uint256 messageFee
    );
    
    event EndpointUpdated(
        address indexed soulAddress,
        bytes32[] supportedMessageTypes,
        uint256 messageFee,
        bool active
    );
    
    event MessageSent(
        uint256 indexed messageId,
        address indexed fromAgent,
        address indexed toAgent,
        bytes32 messageType,
        uint256 paymentAmount
    );
    
    event MessageDelivered(
        uint256 indexed messageId,
        address indexed toAgent
    );
    
    event AgentRegistryUpdated(address indexed newRegistry);
    
    event PaymentWithdrawn(address indexed recipient, uint256 amount);
    
    constructor() Ownable(msg.sender) {}
    
    /**
     * @notice Set the agent registry address
     * @param _agentRegistry Address of the AgentRegistry contract
     */
    function setAgentRegistry(address _agentRegistry) external onlyOwner {
        agentRegistry = _agentRegistry;
        emit AgentRegistryUpdated(_agentRegistry);
    }
    
    /**
     * @notice Register agent endpoint for messaging
     * @param supportedMessageTypes List of message types this agent can handle
     * @param messageFee Fee required to send messages to this agent
     */
    function registerEndpoint(
        bytes32[] memory supportedMessageTypes,
        uint256 messageFee
    ) external {
        require(supportedMessageTypes.length > 0, "Must support at least one message type");
        
        endpoints[msg.sender] = AgentEndpoint({
            soulAddress: msg.sender,
            supportedMessageTypes: supportedMessageTypes,
            messageFee: messageFee,
            active: true,
            registeredAt: block.timestamp
        });
        
        // Index agent by each supported message type
        for (uint256 i = 0; i < supportedMessageTypes.length; i++) {
            agentsByMessageType[supportedMessageTypes[i]].push(msg.sender);
        }
        
        emit EndpointRegistered(msg.sender, supportedMessageTypes, messageFee);
    }
    
    /**
     * @notice Update agent endpoint
     * @param supportedMessageTypes Updated list of supported message types
     * @param messageFee Updated message fee
     * @param active Whether the endpoint is active
     */
    function updateEndpoint(
        bytes32[] memory supportedMessageTypes,
        uint256 messageFee,
        bool active
    ) external {
        require(endpoints[msg.sender].soulAddress != address(0), "Endpoint not registered");
        
        // Remove old message type indices
        bytes32[] memory oldTypes = endpoints[msg.sender].supportedMessageTypes;
        for (uint256 i = 0; i < oldTypes.length; i++) {
            _removeAgentFromMessageType(oldTypes[i], msg.sender);
        }
        
        endpoints[msg.sender].supportedMessageTypes = supportedMessageTypes;
        endpoints[msg.sender].messageFee = messageFee;
        endpoints[msg.sender].active = active;
        
        // Add new message type indices
        for (uint256 i = 0; i < supportedMessageTypes.length; i++) {
            agentsByMessageType[supportedMessageTypes[i]].push(msg.sender);
        }
        
        emit EndpointUpdated(msg.sender, supportedMessageTypes, messageFee, active);
    }
    
    /**
     * @notice Send a message to another agent
     * @param toAgent Recipient agent address
     * @param messageType Type of message being sent
     * @param data Message payload
     */
    function sendMessage(
        address toAgent,
        bytes32 messageType,
        bytes memory data
    ) external payable nonReentrant {
        require(endpoints[msg.sender].soulAddress != address(0), "Sender not registered");
        require(endpoints[toAgent].soulAddress != address(0), "Recipient not registered");
        require(endpoints[toAgent].active, "Recipient endpoint inactive");
        require(_supportsMessageType(toAgent, messageType), "Recipient doesn't support this message type");
        require(msg.value >= endpoints[toAgent].messageFee, "Insufficient payment");
        require(data.length <= MAX_MESSAGE_SIZE, "Message size exceeds maximum limit");
        
        messageCounter++;
        uint256 messageId = messageCounter;
        
        // Store message with payment amount for pull payment
        messages[messageId] = Message({
            id: messageId,
            fromAgent: msg.sender,
            toAgent: toAgent,
            messageType: messageType,
            data: data,
            timestamp: block.timestamp,
            paymentAmount: msg.value,
            delivered: false
        });
        
        sentMessages[msg.sender].push(messageId);
        receivedMessages[toAgent].push(messageId);
        
        emit MessageSent(messageId, msg.sender, toAgent, messageType, msg.value);
        
        // Transfer payment to recipient using pull payment pattern
        // Payment is held in escrow until recipient claims it
        // This prevents reentrancy by ensuring recipient cannot re-enter during payment
        if (msg.value > 0) {
            // Store payment in escrow mapping for recipient to pull
            _escrowPayments[toAgent] += msg.value;
        }
    }
    
    /**
     * @notice Mark a message as delivered
     * @param messageId ID of the message to mark as delivered
     */
    function markMessageDelivered(uint256 messageId) external {
        Message storage message = messages[messageId];
        require(message.toAgent == msg.sender, "Not the recipient");
        require(!message.delivered, "Already delivered");
        
        message.delivered = true;
        emit MessageDelivered(messageId, msg.sender);
    }
    
    /**
     * @notice Withdraw escrowed payments (pull payment pattern)
     * @dev Recipients must call this to claim their message fees
     * This prevents reentrancy attacks by separating payment transfer from message delivery
     */
    function withdrawPayments() external nonReentrant {
        uint256 amount = _escrowPayments[msg.sender];
        require(amount > 0, "No payments to withdraw");
        
        _escrowPayments[msg.sender] = 0;
        
        (bool success, ) = payable(msg.sender).call{value: amount}("");
        require(success, "AgentMessaging: Payment withdrawal failed");
        
        emit PaymentWithdrawn(msg.sender, amount);
    }
    
    /**
     * @notice Get messages sent by an agent
     * @param agent Address of the agent
     */
    function getSentMessages(address agent) external view returns (uint256[] memory) {
        return sentMessages[agent];
    }
    
    /**
     * @notice Get messages received by an agent
     * @param agent Address of the agent
     */
    function getReceivedMessages(address agent) external view returns (uint256[] memory) {
        return receivedMessages[agent];
    }
    
    /**
     * @notice Get message details
     * @param messageId ID of the message
     */
    function getMessage(uint256 messageId) external view returns (Message memory) {
        return messages[messageId];
    }
    
    /**
     * @notice Discover agents by message type
     * @param messageType Type of message to find agents for
     */
    function discoverAgentsByMessageType(bytes32 messageType) external view returns (address[] memory) {
        address[] memory allAgents = agentsByMessageType[messageType];
        
        // Filter to only return active agents
        uint256 activeCount = 0;
        for (uint256 i = 0; i < allAgents.length; i++) {
            if (endpoints[allAgents[i]].active) {
                activeCount++;
            }
        }
        
        address[] memory activeAgents = new address[](activeCount);
        uint256 index = 0;
        for (uint256 i = 0; i < allAgents.length; i++) {
            if (endpoints[allAgents[i]].active) {
                activeAgents[index] = allAgents[i];
                index++;
            }
        }
        
        return activeAgents;
    }
    
    /**
     * @notice Get endpoint info for an agent
     * @param agent Address of the agent
     */
    function getEndpoint(address agent) external view returns (AgentEndpoint memory) {
        return endpoints[agent];
    }

    /**
     * @notice Get endpoint info for an agent (individual fields for compatibility)
     * @param agent Address of the agent
     */
    function getEndpointFields(address agent) external view returns (
        address soulAddress,
        bytes32[] memory supportedMessageTypes,
        uint256 messageFee,
        bool active,
        uint256 registeredAt
    ) {
        AgentEndpoint memory endpoint = endpoints[agent];
        return (
            endpoint.soulAddress,
            endpoint.supportedMessageTypes,
            endpoint.messageFee,
            endpoint.active,
            endpoint.registeredAt
        );
    }
    
    /**
     * @notice Check if an agent supports a specific message type
     * @param agent Address of the agent
     * @param messageType Type of message to check
     */
    function supportsMessageType(address agent, bytes32 messageType) external view returns (bool) {
        return _supportsMessageType(agent, messageType);
    }

    /**
     * @notice Get message details (individual fields for compatibility)
     * @param messageId ID of the message
     */
    function getMessageFields(uint256 messageId) external view returns (
        uint256 id,
        address fromAgent,
        address toAgent,
        bytes32 messageType,
        bytes memory data,
        uint256 timestamp,
        uint256 paymentAmount,
        bool delivered
    ) {
        Message memory message = messages[messageId];
        return (
            message.id,
            message.fromAgent,
            message.toAgent,
            message.messageType,
            message.data,
            message.timestamp,
            message.paymentAmount,
            message.delivered
        );
    }
    
    /**
     * @notice Internal function to check message type support
     */
    function _supportsMessageType(address agent, bytes32 messageType) internal view returns (bool) {
        AgentEndpoint storage endpoint = endpoints[agent];
        for (uint256 i = 0; i < endpoint.supportedMessageTypes.length; i++) {
            if (endpoint.supportedMessageTypes[i] == messageType) {
                return true;
            }
        }
        return false;
    }
    
    /**
     * @notice Internal function to remove agent from message type index
     */
    function _removeAgentFromMessageType(bytes32 messageType, address agent) internal {
        address[] storage agents = agentsByMessageType[messageType];
        for (uint256 i = 0; i < agents.length; i++) {
            if (agents[i] == agent) {
                // Remove by shifting last element to this position
                agents[i] = agents[agents.length - 1];
                agents.pop();
                break;
            }
        }
    }
}
