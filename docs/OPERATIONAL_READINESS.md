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
                      │  - Bearer Token Administrative Auth    │
                      │  - On-Chain Settlement Verification    │
                      │  - Request Size Limit (1 MB)           │
                      └───────┬────────────────────────┬───────┘
                              │                        │
               ┌──────────────▼──────────┐      ┌──────▼─────────────────┐
               │    SQLite/Postgres DB   │      │   Algorand L1 RPC      │
               │  - Persistent Grants    │      │  - AlgoNode Mainnet    │
               │  - Immutable Audit Logs │      │  - AlgoNode Testnet    │
               │  - Backup & Restore Ops │      │  - Live Indexer Checks │
               └─────────────────────────┘      └────────────────────────┘
```

---

## 2. Smart Contract Architecture & Deployed Baseline

### 2.1 Distinction Between Treasury v1 and Hardened Treasury v2
- **Deployed on Testnet (App #774088598)**:
  - Bytecode matches `contracts/treasury_app.py` (**Treasury v1 Prototype**).
  - Schema: `num_byte_slice: 1`, `num_uint: 4`.
  - Creator: `TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM`.
  - Limitations: Lacks dynamic balance querying, lacks reservation accounting, lacks dispute period cancellation, lacks anti-overcommit safeguards.
- **Hardened Treasury v2 (`contracts/hardened_treasury_app.py`)**:
  - Compiled reproducibly to TEAL 8 (4,965 bytes).
  - Schema: `num_byte_slice: 1`, `num_uint: 6`.
  - Hardened Logic:
    - **Liquid Balance Overcommit Protection**: Queries `AssetHolding.balance(CurrentApplicationAddress, asset_id)` and asserts `total_reserved + proposed_amount <= balance`.
    - **Beneficiary Opt-In Verification**: Asserts both application opt-in and QEQ ASA opt-in before allowing grant proposal.
    - **Dispute Timelock & Cancellation**: Admin can cancel suspicious grants within `dispute_period` rounds; beneficiary cannot claim until timelock expires.
    - **Anti-Drain Inner Txn Controls**: Enforces `fee = 0`, `RekeyTo = ZeroAddress`, `AssetCloseTo = ZeroAddress`.
    - **CloseOut Guard**: Fails closed if account has an active pending grant.
    - **ClearState Auto-Recovery**: Reclaims leaked reservation from `total_reserved` if account clears state.
  - **Status**: Tested across 12 semantic execution and attack tests in `tests/test_contracts.py`. **NOT YET DEPLOYED** on Testnet/Mainnet.

---

## 3. Administrative Authentication & Disbursement Verification

### 3.1 Reviewer Authentication Gate
- Endpoint: `PATCH /api/grants/proposals/{id}/review`
- Protection: Protected by `get_authenticated_admin` dependency. Requires `Authorization: Bearer <ADMIN_API_KEY>` or `X-Admin-Key` header.
- Unauthenticated requests fail with HTTP 401 Unauthorized.
- Reviewer identity is derived securely from authenticated credentials and written to immutable `AuditLog` table.

### 3.2 Live On-Chain Disbursement Verification Gate
- Endpoint: `PATCH /api/grants/proposals/{id}/disburse`
- Protection: Does NOT trust client-submitted transaction IDs blindly.
- Queries Algorand live Indexer (`/v2/transactions/{tx_id}`) and Algod node to verify:
  1. Transaction is confirmed (`confirmed-round > 0`).
  2. Transaction type is `axfer` (or application call containing inner `axfer`).
  3. Transferred asset matches expected QEQ ASA ID (`774088414` on Testnet, `3737683297` on Mainnet).
  4. Transferred receiver matches `proposal.beneficiary_address`.
  5. Transferred amount matches or exceeds `proposal.requested_amount_qeq * 10^6`.
- If verification fails or transaction is unconfirmed, endpoint halts with HTTP 400 Bad Request and does NOT transition proposal to `DISBURSED`.

---

## 4. Standard Operational Verification Command

To execute the complete reality gate verification suite:

```bash
python scripts/check.py
```

### Verification Flags:
- `python scripts/check.py --components`: Core economics math & NIST ML-DSA-65 post-quantum signature tests.
- `python scripts/check.py --contracts`: Smart contract TEAL compilation, semantic execution, and attack vector tests.
- `python scripts/check.py --api`: Database schema, input validation, administrative auth & on-chain verification tests.
- `python scripts/check.py --onchain`: Live Mainnet & Testnet Algorand node ledger queries.
- `python scripts/check.py --release`: Production release certification gate. Always runs all technical test suites first; verifies on-chain administrative authority rotation, account rekeying, and balance evacuation. Fails closed with exit code 2 if any compromised authority remains.

---

## 5. Incident Response & Key Rotation Checklist (IR-2026-001)

| Authority Position | Current Address / State | Required Secure State | Verification Method | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Mainnet ASA 3737683297 Manager** | `TPLMGGFN...` (Compromised) | Rotated to secure multisig / hardware wallet | Live Algod Asset Info | **BLOCKED** |
| **Mainnet ASA 3737683297 Reserve** | `TPLMGGFN...` (Compromised) | Rotated to secure multisig / cold wallet | Live Algod Asset Info | **BLOCKED** |
| **Testnet ASA 774088414 Manager** | `TPLMGGFN...` (Compromised) | Rotated to secure address | Live Algod Asset Info | **BLOCKED** |
| **Testnet ASA 774088414 Reserve** | `TPLMGGFN...` (Compromised) | Rotated to secure address | Live Algod Asset Info | **BLOCKED** |
| **Mainnet Account Rekeying** | `auth-addr` absent | Rekeyed to secure uncompromised address | Live Algod Account Info | **BLOCKED** |
| **Mainnet Account Balance** | 20.7734 ALGO present | Evacuated to secure destination | Live Algod Account Info | **BLOCKED** |

To generate unsigned rotation and rekey payloads for offline signing:
```bash
python scripts/rotate_authority_txns.py --network mainnet --new-manager <SECURE_ADDR>
python scripts/rotate_authority_txns.py --network mainnet --rekey-to <SECURE_ADDR>
```

---

## 6. Requirement-to-Evidence Matrix

| Domain | Requirement | Evidence | Status |
| :--- | :--- | :--- | :--- |
| **Liveness & Health** | Working probes | `GET /api/health/live`, `GET /api/health/ready` (HTTP 503 on node failure) | **PASS** |
| **Relational Storage** | ACID constraints & audit trail | SQLite + SQLAlchemy with `GrantProposal` and `AuditLog` models | **PASS** |
| **Database Ops** | Backup & restore tested | `scripts/db_backup_restore.py` verified with SHA-256 snapshots | **PASS** |
| **Admin Authorization** | Reviewer authentication | `PATCH /review` requires Bearer auth, sets verified reviewer | **PASS** |
| **Disbursement Gate** | On-chain ledger verification | `PATCH /disburse` verifies tx confirmation, asset, receiver & amount | **PASS** |
| **Contract Hardening** | Overcommit & anti-drain | TEAL 8 compiled; 12 execution tests pass (`tests/test_contracts.py`) | **PASS** |
| **Release Gate Logic** | Fail-closed multi-suite execution | `scripts/check.py --release` runs all suites, checks all 6 authorities | **PASS** |
| **Key Administration** | Secure uncompromised admin | Incident IR-2026-001 active on-chain | **BLOCKED** |
| **Treasury v2 Deployment**| Production contract deployed | Treasury v1 currently on Testnet; Treasury v2 not yet deployed | **BLOCKED** |
| **Third-Party Audit** | Independent firm review | Not yet commissioned | **NOT IMPLEMENTED** |

**Conclusion**: All engineering improvements, security middleware, contract hardening, and release gates are implemented and verified. Production release is strictly **BLOCKED** pending on-chain authority rotation and Treasury v2 deployment.
