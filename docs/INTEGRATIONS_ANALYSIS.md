# External Integrations: Technical Specifications, Evidence, & Limitations

This document provides a rigorous, evidence-based audit of all third-party integrations in **Qmoosa Equality (QEQ)**.

---

## 1. x402 Bazaar (Micropayments & Resource Discovery)

- **Official Specification**: [x402 Specification v2](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md) & [Bazaar Extension](https://github.com/x402-foundation/x402/blob/main/docs/extensions/bazaar.mdx).
- **Supported Versions**: Protocol version 2.0.
- **Implementation in Code**: [`men/integrations.py`](../men/integrations.py) (`bazaar_catalog()`, `supported_payments()`, `require_payment_integration()`).
- **Test Evidence**:
  - `tests/test_core.py::CoreTests::test_payment_fail_closed` verifies that unverified payment access immediately raises `RuntimeError`.
  - `tests/test_core.py::CoreTests::test_no_plaintext_provider` verifies that non-HTTPS URLs are rejected.
- **Current Limitations & Truth Assessment**:
  - The specific third-party hosted facilitators reviewed default to EVM/Solana networks; however, Algorand V2 direct-payment verification and settlement schemes (as documented in `@x402/avm`) settle via atomic transaction groups directly to `payTo` addresses on Mainnet and Testnet.
  - An HTTP `402 Payment Required` response header alone is not protocol compliance. Verification requirements depend on the scheme: direct-payment schemes require on-chain transaction confirmation, exact recipient and amount matches, and durable replay protection, while escrow-mediated schemes also require on-chain contract clearance.
  - **Status**: **NOT IMPLEMENTED ON-CHAIN (FAIL-CLOSED BOUNDARY ENFORCED)**.

---

## 2. Conway Automaton (Autonomous Workflow Engine)

- **Upstream Repository**: [Conway-Research/automaton](https://github.com/Conway-Research/automaton).
- **Pinned Commit**: Commit `5a9e2f4` (reviewed 2026-10-11).
- **Sandbox Architecture**:
  - If instantiated, the automaton runner must be deployed inside an isolated Docker/gVisor worker with no outbound internet access except to pre-whitelisted Algorand RPC endpoints.
  - Self-replication, dynamic code execution, and filesystem write access outside a designated scratch volume are strictly disabled.
  - The worker **MUST NEVER** hold private keys, mnemonics, or treasury administration authority.
- **Status**: **ARCHITECTURE PINNED / EXECUTION DISALLOWS TREASURY CUSTODY**.

---

## 3. Multi-Model AI Adapters

- **Specification**: OpenAI-compatible HTTPS Chat Completions API.
- **Implementation in Code**: [`men/integrations.py`](../men/integrations.py) (`chat()`).
- **Safety & Boundary Rules**:
  - Maximum message size: 12,000 characters.
  - Hardcoded System Prompt: *"Explain inclusion and project services. Never promise returns, determine caste, or authorize payments."*
  - Strict HTTPS validation; connection timeout of 30 seconds.
- **Privacy Standard**:
  - Beneficiary names, caste, religion, personal identifying information (PII), or wallet seed phrases must **NEVER** be transmitted to external model providers.
- **Status**: **VERIFIED HTTPS ADAPTER (NON-CUSTODIAL ASSISTANT ONLY)**.

---

## 4. Multi-Crypto Wallet Interfaces

- **Standards**:
  - Algorand Transaction Signing (ARC-0001, ARC-0025).
  - Pera Wallet Connect & Defly Wallet deep-link protocols.
- **Implementation**:
  - [`scripts/prepare_asset.py`](../scripts/prepare_asset.py), [`scripts/rotate_authority_txns.py`](../scripts/rotate_authority_txns.py).
  - Generates binary `msgpack_encode(txn)` unsigned payloads.
  - Frontend provides direct Asset ID deep-links: `https://perawallet.app/qr/?data=algorand%3A%2F%2F<asset_id>`.
- **Safety Standard**:
  - The platform never asks for, receives, or stores user private keys or passphrases.
  - Transactions must be signed exclusively within the user's secure wallet client, with full visibility into sender, receiver, asset, amount, and fee.
- **Status**: **ACTIVE USER-CONTROLLED TRANSACTION WORKFLOW**.

---

## 5. Post-Quantum Cryptography (PQC)

- **Specification**: **NIST FIPS 204** (Module-Lattice-Based Digital Signature Standard, ML-DSA).
- **Scheme**: **ML-DSA-65** (Security Category 3).
- **Implementation in Code**: [`men/pqc.py`](../men/pqc.py) via native `pqcrypto.sign.ml_dsa_65` C-extensions.
- **Security Features**:
  - Domain separation prefix: `b'QMOOSA-EQUALITY-MANIFEST-v1\x00'`.
  - Canonical JSON serialization: `sort_keys=True`, `separators=(',', ':')`, `allow_nan=False`.
- **Test Evidence**:
  - `tests/test_crypto.py::CryptographicTests::test_real_signature_and_tampering` verifies:
    - Real keypair generation and manifest signing.
    - Successful signature verification with authentic public key.
    - Immediate rejection upon single-field document tampering.
    - Immediate rejection upon key mismatch.
- **Limitations & Disclosures**:
  - ML-DSA-65 signatures currently validate **off-chain manifests** (grant proposals, release manifests).
  - Algorand Layer 1 consensus natively uses Ed25519; application-level PQC does **NOT** make the underlying Algorand blockchain quantum-resistant.
  - The implementation is not a claim of NIST CMVP / FIPS 140-3 cryptographic module certification.
- **Status**: **VERIFIED OFF-CHAIN PQC ENGINE**.
