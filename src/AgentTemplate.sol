// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title AgentTemplate
 * @notice Marketplace for agent templates and one-click deployment
 * @dev Enables template creators to share agent configurations and monetize deployments
 * 
 * Features:
 * - Template registration with metadata
 * - Version control for templates
 * - Usage tracking and revenue sharing
 * - Template discovery and search
 * - One-click deployment integration
 * - Role-based access control for template management
 */
contract AgentTemplate is Ownable, AccessControl, ReentrancyGuard {
    
    // Role definitions for fine-grained access control
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant MODERATOR_ROLE = keccak256("MODERATOR_ROLE");
    bytes32 public constant CREATOR_ROLE = keccak256("CREATOR_ROLE");
    
    // Template structure
    struct Template {
        uint256 id;
        address creator;
        string name;
        string description;
        string agentType;           // e.g., "trading", "governance", "service"
        string version;
        string[] capabilities;
        string configHash;           // Hash of the configuration
        uint256 deploymentFee;      // Fee for using this template
        uint256 revenueShare;       // Percentage (0-100) that goes to creator
        uint256 totalDeployments;
        uint256 totalRevenue;
        bool active;
        uint256 createdAt;
    }
    
    // Deployment record
    struct Deployment {
        uint256 templateId;
        address deployer;
        address soulAddress;
        uint256 timestamp;
        uint256 feePaid;
    }
    
    // Mapping from template ID to template
    mapping(uint256 => Template) public templates;
    
    // Mapping from creator to their template IDs
    mapping(address => uint256[]) public templatesByCreator;
    
    // Mapping from agent type to template IDs
    mapping(string => uint256[]) public templatesByType;
    
    // Mapping from name to template IDs (for search functionality)
    mapping(string => uint256[]) public templatesByName;
    
    // Mapping from deployment ID to deployment record
    mapping(uint256 => Deployment) public deployments;
    
    // Mapping from soul address to deployment ID
    mapping(address => uint256) public soulToDeployment;
    
    // Counters
    uint256 public templateCounter;
    uint256 public deploymentCounter;
    
    // Platform fee percentage
    uint256 public platformFeePercentage = 10; // 10%
    
    // Events
    event TemplateRegistered(
        uint256 indexed templateId,
        address indexed creator,
        string agentType,
        string version,
        uint256 deploymentFee
    );
    
    event TemplateUpdated(
        uint256 indexed templateId,
        string version,
        uint256 deploymentFee,
        bool active
    );
    
    event TemplateDeactivated(
        uint256 indexed templateId,
        address indexed creator
    );
    
    event TemplateDeployed(
        uint256 indexed deploymentId,
        uint256 indexed templateId,
        address indexed deployer,
        address soulAddress,
        uint256 feePaid
    );
    
    event RevenueDistributed(
        uint256 indexed templateId,
        address indexed creator,
        uint256 creatorAmount,
        uint256 platformAmount
    );
    
    event PlatformFeeUpdated(uint256 newPercentage);
    
    constructor() Ownable(msg.sender) {
        // Set up default admin roles
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(ADMIN_ROLE, msg.sender);
        _grantRole(CREATOR_ROLE, msg.sender);
    }
    
    /**
     * @notice Register a new agent template
     * @param name Template name
     * @param description Template description
     * @param agentType Type of agent (trading, governance, service, etc.)
     * @param version Template version
     * @param capabilities List of capabilities
     * @param configHash Hash of the template configuration
     * @param deploymentFee Fee for using this template
     * @param revenueShare Percentage of fee that goes to creator (0-100)
     */
    function registerTemplate(
        string memory name,
        string memory description,
        string memory agentType,
        string memory version,
        string[] memory capabilities,
        string memory configHash,
        uint256 deploymentFee,
        uint256 revenueShare
    ) external onlyRole(CREATOR_ROLE) {
        require(revenueShare <= 100, "Revenue share cannot exceed 100");
        require(bytes(name).length > 0, "Name cannot be empty");
        require(bytes(agentType).length > 0, "Agent type cannot be empty");
        require(bytes(configHash).length > 0, "Config hash cannot be empty");
        
        templateCounter++;
        uint256 templateId = templateCounter;
        
        templates[templateId] = Template({
            id: templateId,
            creator: msg.sender,
            name: name,
            description: description,
            agentType: agentType,
            version: version,
            capabilities: capabilities,
            configHash: configHash,
            deploymentFee: deploymentFee,
            revenueShare: revenueShare,
            totalDeployments: 0,
            totalRevenue: 0,
            active: true,
            createdAt: block.timestamp
        });
        
        templatesByCreator[msg.sender].push(templateId);
        templatesByType[agentType].push(templateId);
        templatesByName[name].push(templateId);
        
        emit TemplateRegistered(templateId, msg.sender, agentType, version, deploymentFee);
    }
    
    /**
     * @notice Update an existing template
     * @param templateId ID of the template to update
     * @param version New version
     * @param deploymentFee New deployment fee
     * @param active Whether the template is active
     */
    function updateTemplate(
        uint256 templateId,
        string memory version,
        uint256 deploymentFee,
        bool active
    ) external {
        Template storage template = templates[templateId];
        require(template.id != 0, "Template does not exist");
        
        // Allow creator to update their own templates, or admins/moderators to update any template
        bool isCreator = template.creator == msg.sender;
        bool isAdmin = hasRole(ADMIN_ROLE, msg.sender);
        bool isModerator = hasRole(MODERATOR_ROLE, msg.sender);
        
        require(isCreator || isAdmin || isModerator, "Not authorized to update template");
        
        template.version = version;
        template.deploymentFee = deploymentFee;
        
        // Emit deactivation event if template is being deactivated
        if (template.active && !active) {
            emit TemplateDeactivated(templateId, template.creator);
        }
        
        template.active = active;
        
        emit TemplateUpdated(templateId, version, deploymentFee, active);
    }
    
    /**
     * @notice Record a deployment of a template
     * @param templateId ID of the template being deployed
     * @param soulAddress Address of the deployed soul
     */
    function recordDeployment(uint256 templateId, address soulAddress) external payable nonReentrant {
        Template storage template = templates[templateId];
        require(template.id != 0, "Template does not exist");
        require(template.active, "Template is not active");
        require(msg.value >= template.deploymentFee, "Insufficient deployment fee");
        require(soulToDeployment[soulAddress] == 0, "Soul already deployed from a template");
        
        deploymentCounter++;
        uint256 deploymentId = deploymentCounter;
        
        // Calculate revenue distribution
        uint256 creatorAmount = (msg.value * template.revenueShare) / 100;
        uint256 platformAmount = (msg.value * platformFeePercentage) / 100;
        
        // Record deployment
        deployments[deploymentId] = Deployment({
            templateId: templateId,
            deployer: msg.sender,
            soulAddress: soulAddress,
            timestamp: block.timestamp,
            feePaid: msg.value
        });
        
        soulToDeployment[soulAddress] = deploymentId;
        
        // Update template stats
        template.totalDeployments++;
        template.totalRevenue += msg.value;
        
        // Distribute revenue
        if (creatorAmount > 0) {
            (bool success, ) = payable(template.creator).call{value: creatorAmount}("");
            require(success, "Creator transfer failed");
        }
        if (platformAmount > 0) {
            (bool success, ) = payable(owner()).call{value: platformAmount}("");
            require(success, "Platform transfer failed");
        }
        
        emit TemplateDeployed(deploymentId, templateId, msg.sender, soulAddress, msg.value);
        emit RevenueDistributed(templateId, template.creator, creatorAmount, platformAmount);
    }
    
    /**
     * @notice Get template details
     * @param templateId ID of the template
     */
    function getTemplate(uint256 templateId) external view returns (Template memory) {
        require(templates[templateId].id != 0, "Template does not exist");
        return templates[templateId];
    }

    /**
     * @notice Get template details (individual fields for compatibility)
     * @param templateId ID of the template
     */
    function getTemplateFields(uint256 templateId) external view returns (
        uint256 id,
        address creator,
        string memory name,
        string memory description,
        string memory agentType,
        string memory version,
        string[] memory capabilities,
        string memory configHash,
        uint256 deploymentFee,
        uint256 revenueShare,
        uint256 totalDeployments,
        uint256 totalRevenue,
        bool active,
        uint256 createdAt
    ) {
        require(templates[templateId].id != 0, "Template does not exist");
        Template memory template = templates[templateId];
        return (
            template.id,
            template.creator,
            template.name,
            template.description,
            template.agentType,
            template.version,
            template.capabilities,
            template.configHash,
            template.deploymentFee,
            template.revenueShare,
            template.totalDeployments,
            template.totalRevenue,
            template.active,
            template.createdAt
        );
    }
    
    /**
     * @notice Get templates by creator
     * @param creator Address of the creator
     */
    function getTemplatesByCreator(address creator) external view returns (uint256[] memory) {
        return templatesByCreator[creator];
    }
    
    /**
     * @notice Get templates by type
     * @param agentType Type of agent
     */
    function getTemplatesByType(string memory agentType) external view returns (uint256[] memory) {
        return templatesByType[agentType];
    }
    
    /**
     * @notice Get templates by name
     * @param name Template name
     */
    function getTemplatesByName(string memory name) external view returns (uint256[] memory) {
        return templatesByName[name];
    }
    
    /**
     * @notice Get deployment details
     * @param deploymentId ID of the deployment
     */
    function getDeployment(uint256 deploymentId) external view returns (Deployment memory) {
        return deployments[deploymentId];
    }

    /**
     * @notice Get deployment details (individual fields for compatibility)
     * @param deploymentId ID of the deployment
     */
    function getDeploymentFields(uint256 deploymentId) external view returns (
        uint256 templateId,
        address deployer,
        address soulAddress,
        uint256 timestamp,
        uint256 feePaid
    ) {
        Deployment memory deployment = deployments[deploymentId];
        return (
            deployment.templateId,
            deployment.deployer,
            deployment.soulAddress,
            deployment.timestamp,
            deployment.feePaid
        );
    }
    
    /**
     * @notice Get deployment by soul address
     * @param soulAddress Address of the soul
     */
    function getDeploymentBySoul(address soulAddress) external view returns (Deployment memory) {
        uint256 deploymentId = soulToDeployment[soulAddress];
        require(deploymentId != 0, "No deployment found for this soul");
        return deployments[deploymentId];
    }

    /**
     * @notice Get deployment by soul address (individual fields for compatibility)
     * @param soulAddress Address of the soul
     */
    function getDeploymentBySoulFields(address soulAddress) external view returns (
        uint256 templateId,
        address deployer,
        address soulAddress_,
        uint256 timestamp,
        uint256 feePaid
    ) {
        uint256 deploymentId = soulToDeployment[soulAddress];
        require(deploymentId != 0, "No deployment found for this soul");
        Deployment memory deployment = deployments[deploymentId];
        return (
            deployment.templateId,
            deployment.deployer,
            deployment.soulAddress,
            deployment.timestamp,
            deployment.feePaid
        );
    }
    
    /**
     * @notice Update platform fee percentage
     * @param newPercentage New platform fee percentage (0-100)
     */
    function setPlatformFeePercentage(uint256 newPercentage) external onlyRole(ADMIN_ROLE) {
        require(newPercentage <= 100, "Percentage cannot exceed 100");
        platformFeePercentage = newPercentage;
        emit PlatformFeeUpdated(newPercentage);
    }
    
    /**
     * @notice Grant a role to an account
     * @param role The role to grant
     * @param account The account to grant the role to
     */
    function grantRole(bytes32 role, address account) public override onlyRole(DEFAULT_ADMIN_ROLE) {
        _grantRole(role, account);
        emit RoleGranted(role, account, msg.sender);
    }
    
    /**
     * @notice Revoke a role from an account
     * @param role The role to revoke
     * @param account The account to revoke the role from
     */
    function revokeRole(bytes32 role, address account) public override onlyRole(DEFAULT_ADMIN_ROLE) {
        _revokeRole(role, account);
        emit RoleRevoked(role, account, msg.sender);
    }
    
    /**
     * @notice Check if an account has a specific role
     * @param role The role to check
     * @param account The account to check
     */
    function hasRoleCustom(bytes32 role, address account) external view returns (bool) {
        return hasRole(role, account);
    }
    
    /**
     * @notice Get total templates
     */
    function getTotalTemplates() external view returns (uint256) {
        return templateCounter;
    }
    
    /**
     * @notice Get total deployments
     */
    function getTotalDeployments() external view returns (uint256) {
        return deploymentCounter;
    }
}
