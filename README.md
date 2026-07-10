# SAI Protocol

**Sovereign AI Infrastructure for Autonomous Agents**

SAI Protocol is a decentralized infrastructure for deploying, managing, and coordinating autonomous AI agents in Trusted Execution Environments (TEEs). By combining ERC-4337 account abstraction, hardware attestation, and on-chain agent registries, SAI enables truly sovereign AI agents that can execute complex strategies, communicate securely, and operate with verifiable integrity.

## Status

- **Phase 1**: ✅ ERC-4337 Soul Infrastructure (Complete)
- **Phase 2**: ✅ TEE Integration (Complete)
- **Phase 3**: ✅ Agent Registry & Communication (Complete)
- **Phase 4**: ✅ Market Data & Strategy (Complete)
- **Test Coverage**: 53/53 tests passing (100%)

## Documentation

- [Project Report & PRD](./PROJECT_REPORT.md) - Comprehensive project overview and technical specifications
- [Security Audit Report](./AUDIT_REPORT.md) - Security audit findings and recommendations
- [Whitepaper](./WHITEPAPER.md) - Detailed protocol documentation
- [Phase 1 README](./pipeline/phase1_README.md) - ERC-4337 implementation guide

## Quick Start

### Prerequisites

- Node.js 16+
- Python 3.9+
- Foundry (forge, cast, anvil)
- Base Sepolia ETH for testing

### Smart Contract Development

```bash
# Install Foundry
curl -L https://foundry.paradigm.xyz | bash

# Build contracts
forge build

# Run tests
forge test

# Format code
forge fmt

# Deploy to testnet
forge script script/Deploy.s.sol:DeployScript \
  --rpc-url $BASE_SEPOLIA_RPC \
  --private-key $PRIVATE_KEY \
  --broadcast
```

### Python SDK Installation

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r pipeline/requirements.txt
pip install -r sdk/requirements.txt
```

### SDK Usage

```python
from sai_protocol.sdk import SoulManager, AgentDiscovery
from web3 import Web3

# Initialize Web3
w3 = Web3(Web3.HTTPProvider("https://sepolia.base.org"))

# Initialize SDK
soul_manager = SoulManager(
    w3=w3,
    factory_address="0x...",
    registry_address="0x...",
    private_key="your_private_key"
)

# Deploy soul
soul = soul_manager.spawn_soul(
    compose_hash="0x...",
    human_guardian="0x..."
)

# Register agent
soul_manager.register_agent(
    soul_address=soul["soul_address"],
    root_id=soul["root_id"],
    agent_type="trading",
    version="1.0.0",
    name="My Trading Agent",
    description="Autonomous trading agent",
    capabilities=["market_data_ingestion", "strategy_evaluation"],
    chain_id=84532
)
```

## Architecture

### Smart Contracts

- **SoulAccount**: ERC-4337 smart contract wallet with hardware attestation
- **SoulFactory**: Factory for deploying soul instances using minimal proxy pattern
- **AgentRegistry**: Decentralized registry for agent discovery and metadata
- **AgentMessaging**: Secure agent-to-agent communication protocol
- **AgentTemplate**: Marketplace for agent configurations and deployments

### Python SDK

- **SoulManager**: High-level interface for soul deployment and management
- **AgentDiscovery**: Agent discovery, messaging, and template management
- **Trading Agents**: Decision engine, trade execution, and monitoring
- **Enclave Components**: Key management and orchestrator for TEE deployment

### Technology Stack

- **Smart Contracts**: Solidity 0.8.20+, OpenZeppelin v5, Foundry
- **TEE Integration**: Phala dStack v2, Hardware Attestation
- **Python SDK**: Web3.py, eth-account, requests
- **Infrastructure**: Base Sepolia, Pimlico Bundler, ERC-4337

## Project Structure

```
sai-protocol/
├── src/                    # Solidity smart contracts
│   ├── SoulAccount.sol
│   ├── SoulFactory.sol
│   ├── AgentRegistry.sol
│   ├── AgentMessaging.sol
│   └── AgentTemplate.sol
├── agent/                  # Core agent framework
│   └── base_agent.py      # Abstract base class for all agents
├── agents/                 # Specialized agents
│   └── trading/           # Trading agent implementation
│       ├── trading_agent.py
│       ├── decision_engine.py
│       ├── market_data_feed.py
│       ├── strategy_engine.py
│       ├── risk_manager.py
│       ├── trade_executor.py
│       ├── trade_monitor.py
│       ├── signal_processor.py
│       ├── market_signal.py
│       └── trade_encoder.py
├── enclave/               # TEE components
│   ├── key_manager.py
│   └── orchestrator.py
├── sdk/                   # Python SDK
│   ├── soul_manager.py
│   └── agent_discovery.py
├── pipeline/              # Deployment scripts
│   ├── phase1_eoa_pipeline.py
│   ├── spawn_soul.py
│   ├── env.example
│   └── requirements.txt
├── config.py              # Centralized configuration management
└── .env                   # Environment variables (not committed)
└── test/                  # Foundry tests
```

## Features

### Phase 1: ERC-4337 Soul Infrastructure
- ✅ ERC-4337 compliant smart contract wallets
- ✅ Hardware attestation integration
- ✅ Ephemeral key rotation with cooldown
- ✅ Guardian circuit-breaker for emergency recovery
- ✅ Minimal proxy deployment for gas efficiency

### Phase 2: TEE Integration
- ✅ Ephemeral ECDSA keypair generation
- ✅ Hardware attestation quote fetching
- ✅ Automatic key rotation heartbeat
- ✅ Secure memory handling
- ✅ Health check endpoints

### Phase 3: Agent Registry & Communication
- ✅ Agent metadata registration and discovery
- ✅ Type-based and capability-based search
- ✅ Secure agent-to-agent messaging
- ✅ Payment integration with pull payment pattern
- ✅ Template marketplace with revenue sharing

### Phase 4: Market Data & Strategy (Complete)
- ✅ Market data ingestion from multiple sources (Polymarket, CEX)
- ✅ Strategy engine with multiple strategies (arbitrage, trend following)
- ✅ Trade execution on Polymarket CLOB
- ✅ Risk management system (position sizing, stop-loss, drawdown protection)
- ✅ Decision engine with multi-strategy combination
- ✅ Trade monitoring and confirmation
- ✅ Signal processing with technical indicators

## Security

The protocol implements multiple layers of security:

1. **Hardware Attestation**: Code integrity verified by TEE hardware
2. **Smart Contract Security**: OpenZeppelin audited contracts, reentrancy guards
3. **Key Management**: Ephemeral keys with automatic rotation
4. **Economic Security**: Guardian circuit-breaker, payment verification
5. **Network Security**: ERC-4337 bundler integration, rate limiting

**Security Audit**: See [AUDIT_REPORT.md](./AUDIT_REPORT.md) for detailed findings

## Testing

```bash
# Run all smart contract tests
forge test

# Run tests with gas snapshots
forge test --gas-report

# Run specific test contract
forge test --match-contract SoulAccountTest

# Run Python tests (when available)
pytest tests/
```

**Test Coverage**: 53/53 tests passing (100%)

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`forge test`)
5. Format code (`forge fmt`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## License

MIT License - See LICENSE file for details

## Support

- **Documentation**: [PROJECT_REPORT.md](./PROJECT_REPORT.md)
- **Issues**: GitHub Issues
- **Discord**: [Join our Discord](https://discord.gg/sai-protocol)

## Roadmap

- **Q3 2026**: Complete Phase 4 (Market Data & Strategy)
- **Q4 2026**: Testnet launch, Phase 5 (Cross-Chain Operations)
- **Q1 2027**: Mainnet launch,  1000 active agents target
- **Q2 2027**: Phase 7 (Governance Integration)
- **Q3 2027**: Phase 8 (Economic Expansion)

---

**Built with ❤️ for the future of autonomous agents**
