# SAI Protocol — Phase 1: EOA Pipeline

Proves the full ERC-4337 UserOperation flow works against the real Base Sepolia
EntryPoint before any TEE code is written. A throwaway EOA key acts as the
`activeEnclaveKey` — the SoulAccount doesn't care where the key came from, only
that the signature is valid.

**Success = a UserOperation hash confirmed on Basescan.**

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in .env — see comments inside
```

You need:
- A throwaway EOA private key (generate one with `python -c "from eth_account import Account; a = Account.create(); print(a.key.hex())"`)
- That key funded with a small amount of Base Sepolia ETH (faucet: https://faucet.base.org)
- Your deployed SoulAccount proxy address (from the Foundry deploy script)
- A Pimlico API key (free tier at https://dashboard.pimlico.io)

---

## Run order

**Step 1 — Register the throwaway key as the soul's active enclave key**

```bash
python register_throwaway_key.py
```

This calls `rotateEnclaveKey()` on your SoulAccount with an empty proof.
Works if your SoulAccount points at a MockDstackVerifier (recommended for Phase 1).
For a real verifier, pass `--proof-file path/to/proof.hex`.

**Step 2 — Run the full UserOp pipeline**

```bash
python phase1_eoa_pipeline.py
```

This builds a UserOperation, signs it with the throwaway key, sends it to
Pimlico, and polls until it lands on-chain.

---

## What each file does

| File | Purpose |
|---|---|
| `phase1_eoa_pipeline.py` | Main pipeline: build → sign → submit → confirm |
| `register_throwaway_key.py` | Pre-req: register throwaway EOA as activeEnclaveKey |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |

---

## Troubleshooting

**"activeEnclaveKey doesn't match"**
Run `register_throwaway_key.py` first.

**"Rotation cooldown active"**
Wait 5 minutes after the last `rotateEnclaveKey` call and retry.

**"Hardware attestation failed"**
Your SoulAccount is pointing at the real Phala verifier, not a mock.
For Phase 1, deploy a SoulAccount with a MockDstackVerifier instead.

**"Soul account has no ETH"**
Fund the SoulAccount proxy address (not your EOA) with Base Sepolia ETH.
The EntryPoint pulls gas from the account itself during `validateUserOp`.

**Bundler rejects with gas error**
The gas estimate step updates the op automatically. If it still fails,
try increasing `callGasLimit` and `verificationGasLimit` manually in
`build_user_op()`.

---

## Once Phase 1 passes

You have proven:
- `validateUserOp` works against the real EntryPoint
- The bundler accepts and submits your ops
- Gas estimation and payment work correctly

Phase 2: swap the throwaway key for a real TEE-generated key attested by
the Phala dStack verifier. The pipeline code doesn't change — only where
the private key comes from.
