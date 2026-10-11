# Operational Readiness Report & Disaster Recovery Runbook

**System**: Qmoosa Equality Protocol (QEQ)  
**Lead Engineer & Security Review**: Production Security Baseline  
**Evaluation Date**: 2026-10-12  
**Production Release Status**: **STRICTLY BLOCKED** (Fail-Closed Gate, Exit Code 2)  
**AVM Runtime Execution Status**: **BLOCKED** (Docker daemon / LocalNet infrastructure unavailable)  

---

## 1. Operational Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │            FastAPI Backend (v2.0)            │
                      │  - Pure ASGI Streaming Request Limit (1 MB)  │
                      │  - Security Headers (HSTS, CSP, FrameOptions)│
                      │  - Fail-Closed Admin Auth (HMAC-SHA256, 503) │
                      │  - Immutable Server-Derived Reviewer ID      │
                      │  - Canonical Note Settlement Protocol        │
                      │  - Normalized Payment Validation Engine      │
                      └──────────────┬────────────────────────┬──────┘
                                     │                        │
                      ┌──────────────▼──────────┐      ┌──────▼─────────────────┐
                      │    SQLite / Postgres    │      │   Algorand L1 Nodes    │
                      │  - Atomic Transactions  │      │  - AlgoNode Mainnet    │
                      │  - Unique Settlement DB │      │  - AlgoNode Testnet    │
                      │  - Relational Audit Log │      │  - Live Indexer Checks │
                      │  - Automated Migrations │      │  - TEAL 8 Node Compile │
                      │  - Point-in-Time Backup │      │  - Bytecode Verification│
                      └─────────────────────────┘      └────────────────────────┘
```

---

## 2. Hardened Smart Contract Architecture (Box Storage)

### 2.1 Distinction Between Deployed Prototype (v1) and Hardened Treasury v2
- **Deployed on Testnet (App #774088598)**:
  - Bytecode matches `contracts/treasury_app.py` (**Treasury v1 Prototype**).
  - Bytecode Length: 407 bytes (approval program).
  - Bytecode Hash: `C3JX3X2MOYFMDTX3JTOTDJ7TAUKRKVT5B6NVC6WB4LWSQZGYEYBV4OMIWY`.
  - Schema: `num_byte_slice: 1`, `num_uint: 4`.
  - Creator: `TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM` (Compromised).
  - Audit Finding: Lacks solvency checks, lacks reservation accounting, lacks dispute cancellation, and creator key is compromised.
- **Hardened Treasury v2 (`contracts/hardened_treasury_app.py`)**:
  - Architecture: **Application Box Storage** (TEAL 8).
  - Storage Layout: 50 bytes per grant box, keyed by the unique `grant_id`:
    - `[0:8]`: `amount` (uint64)
    - `[8:16]`: `unlock_round` (uint64 timelock)
    - `[16:17]`: `claimed` (1 byte flag: 0=active, 1=claimed)
    - `[17:18]`: `cancelled` (1 byte flag: 0=active, 1=cancelled)
    - `[18:50]`: `beneficiary` (32 bytes public key)
  - Compiled Bytecode: 842 bytes approval program, 4 bytes clear state program.
  - Bytecode Hash: `KYGJKRM6XQLLMOFODXFETKMZR7FCPEKMLFSARY7SHAT3JNG5MEJQZGJXDU`.
  - Core Invariants:
    1. **Box Storage Immunity**: Grant obligations are stored in application-owned boxes. User account lifecycle actions (`ClearState`, `CloseOut`) cannot delete, orphan, or corrupt reservation accounting.
    2. **Solvency & Anti-Overcommit**: `total_reserved + proposed_amount <= AssetHolding.balance(app_address, asset_id)`.
    3. **Exact Settlement Binding**: Inner asset disbursement emits the canonical settlement note: `qeq:grant:v1:<network>:<asset_id>:<grant_id>`.
    4. **Anti-Drain Controls**: Inner transactions enforce `fee = 0`, `rekey_to = zero_address`, and `asset_close_to = zero_address`.
    5. **Dispute Timelock**: Admin can cancel disputed grants ONLY during the dispute period before `unlock_round`. Once `unlock_round` passes, the grant belongs exclusively to the beneficiary.
  - **Deployment Status**: Validated via live Algod node `/v2/teal/compile` and off-chain specification models (`tests/test_contracts.py`). **NOT YET DEPLOYED ON-CHAIN**.

### 2.2 Exact Bytecode Verification vs Schema Matching
The verification engine rejects schema-only matching. `scripts/verify_deployment.py` and `scripts/check.py` query the on-chain application bytecode byte-for-byte:
- App #774088598 is identified as the unmigrated prototype because its 407-byte bytecode does not match the 842-byte compiled Treasury v2 bytecode.
- Bytecode verification prevents deploying or certifying mismatched prototypes.

---

## 3. Backend Hardening & Settlement Protocol

### 3.1 Streaming Request Body Limit Middleware
Implemented as a pure ASGI middleware (`backend/middleware.py`):
- Intercepts incoming HTTP chunk streams mid-flight without buffering entire payloads in memory.
- Validates `Content-Length` headers upfront (rejects negative or non-numeric headers with HTTP 400).
- If streamed bytes exceed 1 MB (1,048,576 bytes), immediately aborts downstream execution and emits HTTP 413 (`Content Too Large`).
- Injects standard production security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Content-Security-Policy`.

### 3.2 Administrative Authentication & Operator Derivation
- Implemented in `backend/auth.py`.
- Compares credentials using constant-time `hmac.compare_digest`.
- **Fail-Closed**: If `ADMIN_API_KEY` is unset, empty, or whitespace-only, all administrative operations fail immediately with HTTP 503 (`Service Unavailable`).
- **Immutable Server-Side Operator Identity**: Reviewer identity is derived exclusively from server-side configuration (`ADMIN_OPERATOR_IDENTITY`). Any incoming caller headers (such as `X-Admin-Identity`) are strictly ignored.

### 3.3 Settlement Verification & Canonical Note Binding
- Implemented in `backend/settlement.py` and `backend/grants.py`.
- **Treasury Allowlist Security**: An empty treasury allowlist fails closed with HTTP 503. Compromised address `TPLMGGFN...` is explicitly banned.
- **Mandatory Canonical Note Protocol**: The on-chain transaction note must strictly conform to:
  ```
  qeq:grant:v1:<network>:<asset_id>:<grant_id>
  ```
  Unrelated notes, missing notes, invalid base64 encoding, or notes binding to different grants/networks/assets are rejected with HTTP 400.
- **Normalized 10-Point Payment Checklist**:
  1. Transaction confirmed on-chain (`confirmed-round > 0`).
  2. Transaction ID matches queried record.
  3. Network genesis hash matches expected network (`mainnet` or `testnet`).
  4. Asset ID matches expected QEQ ASA ID.
  5. Asset receiver matches registered grant beneficiary.
  6. Asset amount matches or exceeds requested grant amount (base units).
  7. Sender matches authorized treasury address allowlist.
  8. Canonical note correctly decoded and strictly bound to grant ID.
  9. Inner transaction path correctly verified if payment was an inner transaction.
  10. Asset close-to and rekey fields are empty (no wallet drain).
- **Relational Replay Protection**:
  Database table `grant_settlements` enforces a unique constraint on `(network_identity, root_transaction_id, inner_transaction_path)` and a unique constraint on `grant_id`. Replay attempts return HTTP 409 (`Conflict`).

### 3.4 Relational Storage & Versioned Migration Pipeline
- Relational schema defined in `backend/db.py`: `GrantProposal`, `GrantSettlement`, `AuditLog`.
- Transitions follow a strict finite-state machine (`VALID_TRANSITIONS`). Terminal states (`DISBURSED`, `REJECTED`, `CANCELLED`) cannot transition back to `APPROVED`.
- Versioned migrations in `migrations/run_migrations.py`:
  1. **Pre-Migration Integrity Audit**: Aborts before modifying tables if duplicate transaction IDs or corrupt records exist.
  2. **Automated Point-in-Time Backup**: Creates a verified SQLite backup with SHA-256 checksum in `data/backups/`.
  3. **DDL Application**: Adds `network`, `asset_id`, unique partial index on `onchain_tx_id`, and creates `grant_settlements`.
  4. **Post-Migration Verification**: Asserts that indexes and constraints are active on the live engine. Tested via `tests/integration/test_migrations.py`.

---

## 4. Operational Verification Commands

To run all automated technical tests:
```bash
python scripts/check.py --components --contracts --api --onchain
```

### Verification Flags:
- `--components`: Core economics math & NIST ML-DSA-65 post-quantum signature tests.
- `--contracts`: Smart contract TEAL compilation against live Algod node, off-chain specification models, and bytecode reality-gap checks.
- `--api`: Database schema, streaming limits, fail-closed auth, reviewer derivation, replay prevention, and disbursement verification.
- `--onchain`: Live Mainnet & Testnet Algorand node ledger queries.
- `--bytecode`: Exact byte-for-byte comparison of live application bytecode against compiled source bytecode.
- `--avm`: Verifies AVM runtime environment status.
- `--release`: Production release certification gate. Executes all test suites, verifies bytecode, and enforces incident authority rotation. Fails closed with exit code 2 if any release blocker remains.

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
| **Treasury Contract Deployment** | App #774088598 is v1 (407 bytes) | Hardened Treasury v2 deployed (842 bytes, uncompromised creator) | Bytecode comparison | **BLOCKED** |

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
| **Streaming Request Limits** | Pure ASGI chunk interception | `backend/middleware.py` rejects >1 MB with HTTP 413 without full memory buffering | **PASS** |
| **Relational Storage** | ACID constraints & audit trail | SQLite + SQLAlchemy with `GrantProposal`, `GrantSettlement`, and `AuditLog` models | **PASS** |
| **Database Migrations** | Safe DDL with automated backup | `migrations/run_migrations.py` pre-audit, backup snapshot, verified in `test_migrations.py` | **PASS** |
| **Admin Authorization** | Fail-closed auth (no default secrets) | Rejects missing `ADMIN_API_KEY` with HTTP 503; sets server-derived reviewer ID | **PASS** |
| **Settlement Gate** | Exact canonical note binding & anti-replay | Checks confirmation, authorized sender, note format `qeq:grant:v1:...`, unique tx ID | **PASS** |
| **Contract Hardening** | Application Box Storage & solvency | TEAL 8 compiled; 13 specification and live node AVM compile tests pass | **PASS** |
| **Deployment Verification**| Exact bytecode byte-for-byte check | `scripts/verify_deployment.py` compares bytecode; proves v1 prototype is deployed | **PASS** |
| **AVM Runtime Execution** | Real AVM execution environment | Checked via `check_avm_runtime_status()`; Docker/LocalNet unavailable | **BLOCKED** |
| **Release Gate Logic** | Fail-closed multi-suite execution | `scripts/check.py --release` runs all suites, checks approved address & Treasury v2 (exit code 2) | **PASS** |
| **Key Administration** | Secure approved admin | Incident IR-2026-001 active on-chain; approved target address not yet set | **BLOCKED** |
| **Treasury v2 Deployment**| Production contract deployed | Treasury v1 currently on Testnet; Treasury v2 not yet deployed | **BLOCKED** |
| **Third-Party Audit** | Independent firm review | Not yet commissioned | **NOT IMPLEMENTED** |

---

## 7. Operational Conclusion

All code-level hardening, request limit enforcement, fail-closed authentication, canonical settlement verification, relational data modeling, database migrations, and smart contract Box Storage upgrades are fully implemented, verified, and backed by automated tests.

Production release certification remains **STRICTLY BLOCKED** (exit code 2) until the asset owner performs on-chain authority rotation, rekeys the compromised account, evacuates remaining ALGO funds, and deploys Hardened Treasury v2 using an uncompromised creator key.
