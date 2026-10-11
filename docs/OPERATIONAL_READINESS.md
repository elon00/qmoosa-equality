# Operational Readiness Report & Disaster Recovery Runbook

**System**: Qmoosa Equality Protocol (QEQ)  
**Lead Engineer & Security Review**: Automated Hardening Baseline  
**Evaluation Date**: 2026-10-12  

---

## 1. Operational Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │          FastAPI Backend (v2.0)        │
                      │  - Security Headers & Strict CORS      │
                      │  - Request Size Limit (1 MB)           │
                      │  - Address & Schema Validations        │
                      └───────┬────────────────────────┬───────┘
                              │                        │
               ┌──────────────▼──────────┐      ┌──────▼─────────────────┐
               │    SQLite/Postgres DB   │      │   Algorand L1 RPC      │
               │  - Persistent Grants    │      │  - AlgoNode Mainnet    │
               │  - Immutable Audit Logs │      │  - AlgoNode Testnet    │
               │  - Backup & Restore Ops │      │  - Pure L1 Verification│
               └─────────────────────────┘      └────────────────────────┘
```

---

## 2. Standard Operational Verification Command

To execute the complete technical verification suite (components, contracts, database, and live node checks):

```bash
python scripts/check.py
```

### Modular Checks:
- `python scripts/check.py --components`: Core math & NIST ML-DSA-65 tests.
- `python scripts/check.py --contracts`: Smart contract TEAL compilation & security tests.
- `python scripts/check.py --api`: Database schema, input validation & API tests.
- `python scripts/check.py --onchain`: Live Mainnet & Testnet ledger status queries.
- `python scripts/check.py --release`: Production release certification (fails closed if compromised key is active).

---

## 3. Database Maintenance & Backup Operations

### 3.1 Automated Snapshot Creation
```bash
python scripts/db_backup_restore.py backup
```
- Creates a timestamped `.sqlite` snapshot under `data/backups/`.
- Computes SHA-256 integrity checksum and records row counts in `.meta.json`.

### 3.2 Restoration from Backup
```bash
python scripts/db_backup_restore.py restore data/backups/qmoosa_db_<TIMESTAMP>.sqlite
```
- Verifies SHA-256 checksum before restoring.
- Overwrites live database file and restores tables atomically.

---

## 4. Incident Response & Key Rotation Runbook

As documented in [`docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md`](INCIDENT_RESPONSE_KEY_EXPOSURE.md):
1. **Never** input private keys in terminal or chat.
2. Run `python scripts/rotate_authority_txns.py --network mainnet --new-manager <SECURE_ADDR>` to generate unsigned `rotate-manager-mainnet.unsigned`.
3. Sign using owner's secure hardware/cold wallet and broadcast to Algorand MainNet.
4. Verify rotation with `python scripts/check.py --release`.

---

## 5. Deployment Rollback Procedures

1. **Backend / API Rollback**:
   - Revert application commit via git: `git revert <COMMIT_HASH>`
   - Re-run `python scripts/check.py` to ensure clean dependencies.
2. **Smart Contract Emergency Pause**:
   - The hardened treasury contract implements `toggle_pause`.
   - Admin account calls `toggle_pause` application transaction to freeze all proposal claims and token transfers immediately during an active exploit.
3. **ASA Freeze Safeguard Notice**:
   - QEQ ASA has `freeze = None` by architectural design. User balances cannot be frozen by administrators.

---

## 6. Operational Status Assessment

| Domain | Requirement | Evidence | Status |
| :--- | :--- | :--- | :--- |
| **Liveness & Health** | Working probes | `GET /api/health/live`, `GET /api/health/ready` | **PASS** |
| **Relational Storage** | ACID constraints | SQLite + SQLAlchemy with audit logging | **PASS** |
| **Smart Contracts** | TEAL 8 compilation | Verified against AlgoNode Testnet compiler | **PASS** |
| **Database Ops** | Backup & restore tested | `scripts/db_backup_restore.py` verified | **PASS** |
| **Key Administration** | Secure uncompromised admin | Incident IR-2026-001 active | **BLOCKED** |
| **Third-Party Audit** | Independent firm review | Not yet commissioned | **NOT IMPLEMENTED** |

**Conclusion**: Technical operations, database storage, and test harnesses are fully operational. Production release is **BLOCKED** until administrative key rotation is verified on-chain.
