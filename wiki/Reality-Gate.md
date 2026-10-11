# Reality Gate Specification

The **Reality Gate** is the core operational principle and architectural contract of the **Qmoosa Equality** ecosystem.

---

## 🛡️ Core Axiom: Elimination of Simulation and Mocks

In many software and Web3 prototypes, tests pass by stubbing RPC endpoints, mocking contract responses, and faking deployment confirmations. The **Reality Gate** categorically bans these practices:

1. **Never Ever Use Mocks or Stubs**: Unit and integration tests must run against actual mathematical and cryptographic logic, real network endpoints, or fail-closed error boundaries.
2. **Never Fake On-Chain Confirmations**: An asset, smart contract, or transaction cannot be reported as "deployed" without a real transaction hash (`tx_id`), verified block round (`confirmed-round`), and explorer-traceable record on the Algorand blockchain.
3. **Fail-Closed Conjunction**: If any prerequisite is missing (e.g. insufficient testnet funds, unreviewed contracts, missing independent audit), execution immediately halts with an explicit error code rather than fabricating success.

---

## 🚦 Reality Gate Lifecycle Stages

```
   [ Stage 0: Source & Primitives ]
               │
               ▼ (Passes all 11 component tests: ML-DSA-65, integer math, HTTPS)
   [ Stage 1: Algorand Testnet Gate ]
               │
               ▼ (Requires funded address >= 0.2 ALGO, broadcasts real ASA)
   [ Stage 2: Smart Contract & Escrow Gate ]
               │
               ▼ (Requires TEAL/PyTeal contracts, timelocks, multisig treasury)
   [ Stage 3: Release & Mainnet Gate ]
               │
               ▼ (Requires independent audit, chain confirmation, legal review)
```

### Stage 0: Source Prototype & Cryptographic Primitives
- Off-chain **ML-DSA-65** key generation and signature verification with tamper checks.
- Integer-only budget allocations with strictly zero rounding leakage.
- Enforced HTTPS-only network boundaries for AI and discovery providers.
- Status: **VERIFIED & ACTIVE**.

### Stage 1: Algorand Testnet Deployment Gate
- Execution script: `scripts/deploy_testnet.py`.
- Algod Node: Algorand Testnet (`https://testnet-api.algonode.cloud`).
- Gate Condition: Minimum account balance must be $\ge 0.2\text{ ALGO}$ to satisfy the Minimum Balance Requirement (MBR) and transaction fees.
- Result on insufficient funds: Explicit fail-closed rejection pointing to the official Algorand Testnet dispenser (`https://lora.algokit.io/testnet/fund`).
- Status: **GATE ACTIVE (Awaiting dispenser funding)**.

### Stage 2: Smart Contract & Treasury Governance Gate
- Standard ASAs have immutable totals. Ongoing community grant issuance requires either an application-managed balance ledger or epoch-based issuance contracts.
- Smart contracts must enforce multisig governance, dispute timelocks, and spending ceilings.
- Status: **BLOCKED (Documented in STATUS.json)**.

### Stage 3: Release & Mainnet Gate
- Running `python scripts/check.py --release` intentionally exits with code `2`.
- Why? A financial protocol intended for vulnerable populations must never claim "production readiness" through automated scripts without independent third-party audits, live deployment proofs, and community consent procedures.
- Status: **LOCKED BY DESIGN**.

---

## 📊 Truth Taxonomy

| Layer | Implementation | Simulation Status |
| :--- | :--- | :--- |
| **Post-Quantum Crypto** | NIST FIPS 204 `ML-DSA-65` via `pqcrypto` | Real C-extension execution; zero mocks |
| **Economic Math** | Pure integer arithmetic in basis points | Exact conservation ($sum == n$); zero floats |
| **Blockchain Client** | Algorand official SDK (`py-algorand-sdk`) | Real Algorand testnet node calls; zero mocks |
| **Release Readiness** | `scripts/check.py --release` | Deliberately fails closed until audited |
