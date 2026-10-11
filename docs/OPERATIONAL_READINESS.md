# Operational Readiness Report & Disaster Recovery Runbook

**System**: Qmoosa Equality Protocol (QEQ)  
**Lead Engineer & Security Review**: Automated Hardening Baseline  
**Evaluation Date**: 2026-10-12  
**Production Release Status**: **STRICTLY BLOCKED** (Fail-Closed Gate)  

---

## 1. Operational Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │          FastAPI Backend (v2.0)        │
                      │  - Security Headers & Strict CORS      │
                      │  - Fail-Closed Admin Auth (No Defaults)│
                      │  - Immutable Server-Derived Reviewer ID│
                      │  - On-Chain Settlement Verification    │
                      │  - Durable Replay & Sender Check       │
                      │  - Request Size Limit (1 MB)           │
                      └───────┬────────────────────────┬───────┘
                              │                        │
               ┌──────────────▼──────────┐      ┌──────▼─────────────────┐
               │    SQLite/Postgres DB   │      │   Algorand L1 RPC      │
               │  - Persistent Grants    │      │  - AlgoNode Mainnet    │
               │  - Unique On-Chain Tx ID│      │  - AlgoNode Testnet    │
               │  - Immutable Audit Logs │      │  - Live Indexer Checks │
               │  - Backup & Restore Ops │      │  - AVM Compiler Check  │
               └─────────────────────────┘      └────────────────────────┘
```

---

## 2. Smart Contract Architecture & Deployed Baseline

### 2.1 Distinction Between Deployed Prototype (v1) and Hardened Treasury (v2)
- **Deployed on Testnet (App #774088598)**:
  - Bytecode matches `contracts/treasury_app.py` (**Treasury v1 Prototype**).
  - Schema: `num_byte_slice: 1`, `num_uint: 4`.
  - Creator: `TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM`.
  - Limitations: Lacks dynamic balance querying, lacks reservation accounting, lacks dispute period cancellation, lacks anti-overcommit safeguards.
- **Hardened Treasury v2 (`contracts/hardened_treasury_app.py`)**:
  - Compiled reproducibly to TEAL 8 (4,965 bytes). Tested via live Algod node `/v2/teal/compile`.
  - Schema: `num_byte_slice: 1`, `num_uint: 6`.
  - Hardened Logic:
    - **Liquid Balance Overcommit Protection**: Queries `AssetHolding.balance(CurrentApplicationAddress, asset_id)` and asserts `total_reserved + proposed_amount <= balance`.
    - **Beneficiary Opt-In Verification**: Asserts both application opt-in and QEQ ASA opt-in before allowing grant proposal.
    - **Dispute Timelock & Cancellation**: Admin can cancel suspicious grants within `dispute_period` rounds; beneficiary cannot claim until timelock expires.
    - **Anti-Drain Inner Txn Controls**: Enforces `fee = 0`, `RekeyTo = ZeroAddress`, `AssetCloseTo = ZeroAddress`.
    - **CloseOut Guard**: Fails closed if account has an active pending grant.
    - **ClearState Auto-Recovery**: Reclaims leaked reservation from `total_reserved` if account clears state.
  - **Status**: Verified in live AVM node compilation and off-chain specification test suites (`tests/test_contracts.py`). **NOT YET DEPLOYED** on Testnet/Mainnet. Hardened v2 deployment is a mandatory blocker for production release.

---

## 3. Administrative Authentication & Settlement Verification

### 3.1 Zero-Default Admin Authentication Gate
- Protection: Protected by `get_authenticated_admin` dependency.
- **No Hardcoded Fallback**: If `ADMIN_API_KEY` is not explicitly set in the host environment, all administrative endpoints fail closed immediately with HTTP 503 (`Service Unavailable`).
- **Immutable Server-Side Reviewer Identity**: Reviewer identity is derived exclusively from server-side verified configuration (`ADMIN_OPERATOR_IDENTITY`). Request headers (such as `x-admin-identity`) from callers are strictly ignored and cannot spoof or override reviewer identity in audit logs.

### 3.2 Live On-Chain Settlement Verification & Anti-Replay Gate
- Endpoint: `PATCH /api/grants/proposals/{id}/disburse`
- Protection:
  1. **Durable Replay Protection**: `onchain_tx_id` has a database-level `UNIQUE` constraint in `GrantProposal`. The endpoint checks if `tx_id` has already been recorded for any other proposal, returning HTTP 409 (`Conflict`) on replay attempts.
  2. **Authorized Treasury Sender Enforcement**: Transaction sender (or inner transaction sender) must match the authorized treasury address list (`AUTHORIZED_TREASURY_ADDRESSES`). Transfers from arbitrary third-party accounts are rejected with HTTP 400.
  3. **Specific Grant Binding**: If a transaction `note` is present, it is decoded and verified against `proposal_id` (e.g. `qeq:grant:{proposal_id}`). Mismatches reject with HTTP 400.
  4. **Ledger Confirmation**: Queries Algorand Indexer & Algod node to confirm `confirmed-round > 0`.
  5. **Asset & Beneficiary Match**: Asserts transferred asset matches expected QEQ ASA ID (`774088414` on Testnet, `3737683297` on Mainnet) and receiver matches registered beneficiary.
  6. **Amount Match**: Asserts transferred amount in base units meets or exceeds requested amount (`requested_amount_qeq * 10^6`).

---

## 4. Standard Operational Verification Command

To execute the complete reality gate verification suite:

```bash
python scripts/check.py
```

### Verification Flags:
- `python scripts/check.py --components`: Core economics math & NIST ML-DSA-65 post-quantum signature tests.
- `python scripts/check.py --contracts`: Smart contract TEAL compilation against live Algod node, off-chain specification models, and reality-gap checks.
- `python scripts/check.py --api`: Database schema, input validation, fail-closed auth, reviewer spoof protection, replay prevention, and disbursement verification.
- `python scripts/check.py --onchain`: Live Mainnet & Testnet Algorand node ledger queries.
- `python scripts/check.py --release`: Production release certification gate. Always runs all technical test suites first; verifies on-chain administrative authority rotation to owner's approved safe address, account rekeying, balance evacuation, and Treasury v2 on-chain deployment. Fails closed with exit code 2 if any blocker remains.

---

## 5. Incident Response & Key Rotation Checklist (IR-2026-001)

| Authority Position | Current Address / State | Required Secure State | Verification Method | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Mainnet ASA 3737683297 Manager** | `TPLMGGFN...` (Compromised) | Rotated to owner's approved secure address | Live Algod Asset Info | **BLOCKED** |
| **Mainnet ASA 3737683297 Reserve** | `TPLMGGFN...` (Compromised) | Rotated to owner's approved secure address | Live Algod Asset Info | **BLOCKED** |
| **Testnet ASA 774088414 Manager** | `TPLMGGFN...` (Compromised) | Rotated to owner's approved secure address | Live Algod Asset Info | **BLOCKED** |
| **Testnet ASA 774088414 Reserve** | `TPLMGGFN...` (Compromised) | Rotated to owner's approved secure address | Live Algod Asset Info | **BLOCKED** |
| **Mainnet Account Rekeying** | `auth-addr` absent | Rekeyed to owner's approved secure address | Live Algod Account Info | **BLOCKED** |
| **Mainnet Account Balance** | 20.7734 ALGO present | Evacuated to secure destination (< 1 ALGO) | Live Algod Account Info | **BLOCKED** |
| **Treasury Contract Deployment** | App #774088598 is v1 (4 uints) | Hardened Treasury v2 deployed (6 uints, uncompromised creator) | Live Algod App Info | **BLOCKED** |

To generate unsigned rotation and rekey payloads for offline signing:
```bash
python scripts/rotate_authority_txns.py --network mainnet --new-manager <APPROVED_SECURE_ADDR>
python scripts/rotate_authority_txns.py --network mainnet --rekey-to <APPROVED_SECURE_ADDR>
```

---

## 6. Requirement-to-Evidence Matrix

| Domain | Requirement | Evidence | Status |
| :--- | :--- | :--- | :--- |
| **Liveness & Health** | Working probes | `GET /api/health/live`, `GET /api/health/ready` (HTTP 503 on node failure) | **PASS** |
| **Relational Storage** | ACID constraints & audit trail | SQLite + SQLAlchemy with `GrantProposal` and `AuditLog` models | **PASS** |
| **Database Ops** | Backup & restore tested | `scripts/db_backup_restore.py` verified with SHA-256 snapshots | **PASS** |
| **Admin Authorization** | Fail-closed auth (no default secrets) | Rejects missing `ADMIN_API_KEY` with HTTP 503; sets server-derived reviewer ID | **PASS** |
| **Disbursement Gate** | On-chain verification & anti-replay | Checks confirmation, authorized sender, grant note binding, unique tx ID | **PASS** |
| **Contract Hardening** | Overcommit & anti-drain | TEAL 8 compiled; 12 specification and live node AVM compile tests pass | **PASS** |
| **Release Gate Logic** | Fail-closed multi-suite execution | `scripts/check.py --release` runs all suites, checks approved address & Treasury v2 | **PASS** |
| **Key Administration** | Secure approved admin | Incident IR-2026-001 active on-chain; approved target address not yet set | **BLOCKED** |
| **Treasury v2 Deployment**| Production contract deployed | Treasury v1 currently on Testnet; Treasury v2 not yet deployed | **BLOCKED** |
| **Third-Party Audit** | Independent firm review | Not yet commissioned | **NOT IMPLEMENTED** |

**Conclusion**: Technical operations, database persistence, reviewer authentication, on-chain disbursement checks, and smart contract protections are implemented and verified. Production release remains strictly **BLOCKED** pending on-chain authority rotation to an approved address and on-chain deployment of Hardened Treasury v2.
