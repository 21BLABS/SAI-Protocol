// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Strings.sol";

/**
 * @title AgentRegistry
 * @notice Registry for SAI Protocol autonomous agents
 * @dev Stores metadata about deployed souls for discovery and categorization
 * 
 * This contract enables:
 * - Agent type discovery (trading, governance, service, etc.)
 * - Capability querying
 * - Version tracking
 * - Agent reputation/health tracking
 */
contract AgentRegistry is Ownable {
    constructor() Ownable(msg.sender) {}
    using Strings for uint256;

    // Agent metadata structure
    struct AgentInfo {
        address soulAddress;        // SoulAccount address
        bytes32 rootId;             // Root identity from SoulFactory
        string agentType;           // e.g., "trading", "governance", "service"
        string version;             // Semantic version
        string name;                // Human-readable name
        string description;         // What this agent does
        string[] capabilities;      // List of capabilities
        address author;             // Creator/organization
        uint256 chainId;            // Target blockchain
        bool requiresPaymaster;     // Whether agent needs paymaster
        uint256 registeredAt;       // Registration timestamp
        bool active;                // Whether agent is currently active
    }

    // Mapping from soul address to agent info
    mapping(address => AgentInfo) public agents;
    
    // Mapping from rootId to soul address (for reverse lookup)
    mapping(bytes32 => address) public rootIdToSoul;
    
    // Mapping from agent type to array of soul addresses
    mapping(string => address[]) public agentsByType;
    
    // Count of registered agents by type
    mapping(string => uint256) public agentCountByType;
    
    // Dynamic tracking of registered agent types
    string[] public registeredTypes;
    mapping(string => bool) public isTypeRegistered;
    
    // Total registered agents
    uint256 public totalAgents;
    
    // Events
    event AgentRegistered(
        address indexed soulAddress,
        bytes32 indexed rootId,
        string agentType,
        string version,
        address indexed author
    );
    
    event AgentUpdated(
        address indexed soulAddress,
        string version,
        bool active
    );
    
    event AgentDeactivated(
        address indexed soulAddress,
        bytes32 indexed rootId
    );
    
    event BatchAgentsRegistered(
        address[] indexed soulAddresses,
        bytes32[] indexed rootIds,
        string[] agentTypes,
        uint256 count
    );

    /**
     * @notice Register a new agent in the registry
     * @param soulAddress The SoulAccount address
     * @param rootId The root identity from SoulFactory
     * @param agentType Type of agent (trading, governance, service, etc.)
     * @param version Semantic version
     * @param name Human-readable name
     * @param description What this agent does
     * @param capabilities List of capabilities
     * @param author Creator/organization
     * @param chainId Target blockchain
     * @param requiresPaymaster Whether agent needs paymaster
     */
    function registerAgent(
        address soulAddress,
        bytes32 rootId,
        string memory agentType,
        string memory version,
        string memory name,
        string memory description,
        string[] memory capabilities,
        address author,
        uint256 chainId,
        bool requiresPaymaster
    ) external {
        _registerAgent(
            soulAddress,
            rootId,
            agentType,
            version,
            name,
            description,
            capabilities,
            author,
            chainId,
            requiresPaymaster
        );
    }

    /**
     * @notice Internal function to register an agent
     * @dev Used by both registerAgent and batchRegisterAgents
     */
    function _registerAgent(
        address soulAddress,
        bytes32 rootId,
        string memory agentType,
        string memory version,
        string memory name,
        string memory description,
        string[] memory capabilities,
        address author,
        uint256 chainId,
        bool requiresPaymaster
    ) internal {
        require(soulAddress != address(0), "Invalid soul address");
        require(rootId != bytes32(0), "Invalid root ID");
        require(agents[soulAddress].soulAddress == address(0), "Agent already registered");
        require(rootIdToSoul[rootId] == address(0), "Root ID already registered");
        
        // Store agent info
        agents[soulAddress] = AgentInfo({
            soulAddress: soulAddress,
            rootId: rootId,
            agentType: agentType,
            version: version,
            name: name,
            description: description,
            capabilities: capabilities,
            author: author,
            chainId: chainId,
            requiresPaymaster: requiresPaymaster,
            registeredAt: block.timestamp,
            active: true
        });
        
        // Update reverse lookup
        rootIdToSoul[rootId] = soulAddress;
        
        // Add to type-based index
        agentsByType[agentType].push(soulAddress);
        agentCountByType[agentType]++;
        
        // Track new agent type dynamically
        if (!isTypeRegistered[agentType]) {
            isTypeRegistered[agentType] = true;
            registeredTypes.push(agentType);
        }
        
        // Update total count
        totalAgents++;
        
        emit AgentRegistered(soulAddress, rootId, agentType, version, author);
    }

    /**
     * @notice Update agent metadata
     * @param soulAddress The SoulAccount address
     * @param version New version
     * @param active Whether agent is currently active
     */
    function updateAgent(
        address soulAddress,
        string memory version,
        bool active
    ) external {
        require(agents[soulAddress].soulAddress != address(0), "Agent not registered");
        require(
            msg.sender == agents[soulAddress].author || 
            msg.sender == owner(),
            "Unauthorized"
        );
        
        agents[soulAddress].version = version;
        agents[soulAddress].active = active;
        
        emit AgentUpdated(soulAddress, version, active);
    }

    /**
     * @notice Deactivate an agent
     * @param soulAddress The SoulAccount address
     */
    function deactivateAgent(address soulAddress) external {
        require(agents[soulAddress].soulAddress != address(0), "Agent not registered");
        require(
            msg.sender == agents[soulAddress].author || 
            msg.sender == owner(),
            "Unauthorized"
        );
        
        agents[soulAddress].active = false;
        
        emit AgentDeactivated(soulAddress, agents[soulAddress].rootId);
    }

    /**
     * @notice Get agent info by soul address
     * @param soulAddress The SoulAccount address
     */
    function getAgent(address soulAddress) external view returns (AgentInfo memory) {
        require(agents[soulAddress].soulAddress != address(0), "Agent not registered");
        return agents[soulAddress];
    }

    /**
     * @notice Get agent info by root ID
     * @param rootId The root identity
     */
    function getAgentByRootId(bytes32 rootId) external view returns (AgentInfo memory) {
        address soulAddress = rootIdToSoul[rootId];
        require(soulAddress != address(0), "Agent not found");
        return agents[soulAddress];
    }

    /**
     * @notice Get agent info by soul address (individual fields for compatibility)
     * @param soulAddress The SoulAccount address
     */
    function getAgentFields(address soulAddress) external view returns (
        address soulAddress_,
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
    ) {
        require(agents[soulAddress].soulAddress != address(0), "Agent not registered");
        AgentInfo memory info = agents[soulAddress];
        return (
            info.soulAddress,
            info.rootId,
            info.agentType,
            info.version,
            info.name,
            info.description,
            info.capabilities,
            info.author,
            info.chainId,
            info.requiresPaymaster,
            info.registeredAt,
            info.active
        );
    }

    /**
     * @notice Get agent info by root ID (individual fields for compatibility)
     * @param rootId The root identity
     */
    function getAgentByRootIdFields(bytes32 rootId) external view returns (
        address soulAddress,
        bytes32 rootId_,
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
    ) {
        address soulAddress_ = rootIdToSoul[rootId];
        require(soulAddress_ != address(0), "Agent not found");
        AgentInfo memory info = agents[soulAddress_];
        return (
            info.soulAddress,
            info.rootId,
            info.agentType,
            info.version,
            info.name,
            info.description,
            info.capabilities,
            info.author,
            info.chainId,
            info.requiresPaymaster,
            info.registeredAt,
            info.active
        );
    }

    /**
     * @notice Get all agents of a specific type
     * @param agentType The agent type
     */
    function getAgentsByType(string memory agentType) external view returns (address[] memory) {
        return agentsByType[agentType];
    }

    /**
     * @notice Get agents of a specific type with pagination
     * @param agentType The agent type
     * @param offset Starting index
     * @param limit Maximum number of results
     */
    function getAgentsByTypePaginated(
        string memory agentType,
        uint256 offset,
        uint256 limit
    ) external view returns (address[] memory) {
        address[] memory allAgents = agentsByType[agentType];
        uint256 total = allAgents.length;
        
        if (offset >= total) {
            return new address[](0);
        }
        
        uint256 end = offset + limit;
        if (end > total) {
            end = total;
        }
        
        uint256 resultSize = end - offset;
        address[] memory result = new address[](resultSize);
        
        for (uint256 i = 0; i < resultSize; i++) {
            result[i] = allAgents[offset + i];
        }
        
        return result;
    }

    /**
     * @notice Get count of agents by type
     * @param agentType The agent type
     */
    function getAgentCountByType(string memory agentType) external view returns (uint256) {
        return agentCountByType[agentType];
    }

    /**
     * @notice Check if an agent is registered and active
     * @param soulAddress The SoulAccount address
     */
    function isAgentActive(address soulAddress) external view returns (bool) {
        return agents[soulAddress].active && agents[soulAddress].soulAddress != address(0);
    }

    /**
     * @notice Get all registered agent types
     */
    function getRegisteredTypes() external view returns (string[] memory) {
        return registeredTypes;
    }

    /**
     * @notice Batch register agents (for factory integration)
     * @param soulAddresses Array of SoulAccount addresses
     * @param rootIds Array of root IDs
     * @param agentTypes Array of agent types
     * @param versions Array of versions
     * @param names Array of names
     * @param descriptions Array of descriptions
     * @param capabilities Array of capabilities arrays
     * @param authors Array of authors
     * @param chainIds Array of chain IDs
     * @param requiresPaymasters Array of paymaster requirements
     */
    function batchRegisterAgents(
        address[] memory soulAddresses,
        bytes32[] memory rootIds,
        string[] memory agentTypes,
        string[] memory versions,
        string[] memory names,
        string[] memory descriptions,
        string[][] memory capabilities,
        address[] memory authors,
        uint256[] memory chainIds,
        bool[] memory requiresPaymasters
    ) external {
        require(
            soulAddresses.length == rootIds.length &&
            soulAddresses.length == agentTypes.length &&
            soulAddresses.length == versions.length &&
            soulAddresses.length == names.length &&
            soulAddresses.length == descriptions.length &&
            soulAddresses.length == capabilities.length &&
            soulAddresses.length == authors.length &&
            soulAddresses.length == chainIds.length &&
            soulAddresses.length == requiresPaymasters.length,
            "Array length mismatch"
        );
        
        for (uint256 i = 0; i < soulAddresses.length; i++) {
            _registerAgent(
                soulAddresses[i],
                rootIds[i],
                agentTypes[i],
                versions[i],
                names[i],
                descriptions[i],
                capabilities[i],
                authors[i],
                chainIds[i],
                requiresPaymasters[i]
            );
        }
        
        emit BatchAgentsRegistered(soulAddresses, rootIds, agentTypes, soulAddresses.length);
    }
}
