// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/proxy/Clones.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

interface ISoulAccount {
    function initialize(
        bytes32 _rootId,
        bytes32 _composeHash,
        address _humanGuardian,
        address _deployer
    ) external;
}

contract SoulFactory is Ownable {
    // The master implementation of the SoulAccount to clone
    address public immutable soulAccountImplementation;
    
    // Global tracking of all spawned digital souls
    mapping(bytes32 => address) public souls;
    uint256 public totalSoulsSpawned;

    event SoulSpawned(
        address indexed soulAddress, 
        bytes32 indexed rootId, 
        address indexed creator, 
        bytes32 modelHash
    );

    constructor(address _implementation) Ownable(msg.sender) {
        require(_implementation != address(0), "Invalid implementation");
        soulAccountImplementation = _implementation;
    }

    /**
     * @notice Spawns a unique, sovereign digital identity (Soul)
     * @param composeHash The cryptographic fingerprint of the AI model/docker image allowed
     * @param humanGuardian Optional time-locked multisig address for recovery/circuit-breaker
     */
    function spawnSoul(
        bytes32 composeHash,
        address humanGuardian
    ) external returns (address soul) {
        // Validate compose hash format (must be non-zero)
        require(composeHash != bytes32(0), "SoulFactory: Invalid compose hash");

        // Generate a fundamentally unique Root Identity
        bytes32 rootId = keccak256(
            abi.encodePacked(msg.sender, block.timestamp, totalSoulsSpawned, composeHash)
        );
        require(souls[rootId] == address(0), "Soul already exists");

        // Deploy clone using BIP-1167 minimal proxy pattern to save gas
        soul = Clones.clone(soulAccountImplementation);
        
        // Initialize the sovereign account state
        ISoulAccount(soul).initialize(rootId, composeHash, humanGuardian, address(this));

        // Register the entity globally
        souls[rootId] = soul;
        totalSoulsSpawned++;

        emit SoulSpawned(soul, rootId, msg.sender, composeHash);
    }
}