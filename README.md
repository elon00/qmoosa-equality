# Qmoosa Equality (QEQ)

An independent Algorand economic-inclusion platform dedicated to supporting Moolnivasi, SC, ST, OBC, minorities, and underserved communities worldwide through transparent grants, livelihoods, social enterprises, and public goods.

**Repository**: `elon00/qmoosa-equality` | **Ticker**: `QEQ` | **Standard**: Algorand Standard Asset (ASA)  
**Mainnet Asset ID**: `3737683297` | **Testnet Asset ID**: `774088414` | **Treasury App ID**: `774088598`

---

## ⚖️ Legal & Independence Disclosures

- **Independent Project Notice**: Qmoosa Equality is an independent open-source community initiative with no affiliation to or endorsement from any external foundation or individuals.
- **No Financial Guarantees**: Token issuance alone does not eliminate poverty, ensure economic security, or generate wealth. QEQ does not offer, promise, or guarantee financial returns, yield, dividend payouts, or income.
- **Pre-Market Status**: QEQ is currently **unlisted** and has **zero secondary market liquidity**. It cannot be redeemed for fiat currency.

---

## 🚨 Security Incident Disclosure (IR-2026-001)

During initial deployment testing, the 25-word mnemonic phrase for the deploying account (`TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM`) was exposed in conversation context.

- **Release Status**: **MAINNET PRODUCTION RELEASE IS STRICTLY BLOCKED** until administrative manager and reserve authorities are rotated on-chain to an uncompromised address via owner-controlled wallet signing, and Hardened Treasury v2 is deployed.
- **Unsigned Migration Tool**: Run `python scripts/rotate_authority_txns.py --network mainnet --new-manager <TARGET_ADDR>` to generate unsigned rotation transactions for offline/hardware wallet signing.
- **Runbook**: See [`docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md`](docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md).

---

## 🌐 Verified On-Chain Deployments

| Network | Asset Name | Ticker | Asset ID | Confirmed Round | Transaction Hash | Explorer Link |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Algorand Testnet** | Qmoosa Equality | `QEQ` | [`774088414`](https://lora.algokit.io/testnet/asset/774088414) | `68171764` | `GDMORMEM...` | [Lora Testnet Asset](https://lora.algokit.io/testnet/asset/774088414) |
| **Algorand Mainnet** | Qmoosa Equality | `QEQ` | [`3737683297`](https://lora.algokit.io/mainnet/asset/3737683297) | `65891166` | `U5LVAFLK...` | [Lora Mainnet Asset](https://lora.algokit.io/mainnet/asset/3737683297) |
| **Testnet Treasury** | Community Escrow (Prototype v1) | `APP` | [`774088598`](https://lora.algokit.io/testnet/application/774088598) | `68171916` | `X3G65FE2...` | [Lora Treasury App](https://lora.algokit.io/testnet/application/774088598) |

*Notice: Testnet Application 774088598 is the prototype v1 (407 bytes approval bytecode). Hardened Treasury v2 (842 bytes TEAL 8 with Application Box Storage) is reproducibly compiled and validated via live Algod node compilation, but remains undeployed on-chain.*

---

## 🛡️ Reality Gate Protocol

This project strictly operates under the **Reality Gate**:
- **Verified On-Chain State**: Real Algorand blockchain node queries against Mainnet and Testnet nodes, live opcode compilation against Algod `/v2/teal/compile`, and byte-for-byte bytecode deployment audits.
- **Accurately Labeled Testing**: Off-chain specification state machines and test fixtures are explicitly labeled as specification models, while AVM runtime execution status is tracked truthfully (marked BLOCKED when LocalNet / Docker is unavailable).
- **Fail-Closed Release Gate**: All technical test suites and deployment gates must pass. If any cryptographic proof, database integrity check, bytecode match, or authority requirement is unverified, release certification halts closed with an explicit error code (code 2 for release blockers).

---

## 💻 Local Setup & Verification

Python 3.12 recommended:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.\.venv\Scripts\activate

python -m pip install -r requirements.txt
```

### Complete Technical Verification Suite
```bash
python scripts/check.py --components --contracts --api --onchain
```

### Modular Audit Commands
- `python scripts/check.py --components`: Runs mathematical allocation and NIST ML-DSA-65 crypto tests.
- `python scripts/check.py --contracts`: Compiles TEAL 8 smart contract on live Algod node, runs Box Storage specification model, and verifies bytecode reality gap.
- `python scripts/check.py --api`: Tests streaming request limits, fail-closed auth, canonical note binding, replay prevention, and database migrations.
- `python scripts/check.py --onchain`: Queries live Algorand Mainnet and Testnet nodes for active ledger proofs.
- `python scripts/check.py --bytecode`: Exact byte-for-byte bytecode audit of on-chain applications against compiled source.
- `python scripts/check.py --release`: Evaluates production release readiness (intentionally **FAILS CLOSED** with exit code 2 until Incident IR-2026-001 and Treasury v2 deployment are resolved).

---

## 🚀 Running the Production Backend & dApp

1. **Launch the Hardened API Server**:
   ```bash
   uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```
2. **Access the dApp Frontend**:
   Open `http://localhost:8000` in any web browser.
   - Live Mainnet / Testnet data switcher.
   - Pera Wallet and Defly opt-in generator.
   - Genuine Grant Application Portal connected to persistent SQLite database with audit logging.

3. **Database Migrations & Backup**:
   ```bash
   # Execute migrations with automated pre-audit and backup:
   python migrations/run_migrations.py

   # Create standalone snapshot with SHA-256 checksum:
   python scripts/db_backup_restore.py backup

   # Restore snapshot:
   python scripts/db_backup_restore.py restore data/backups/qmoosa_db_<TIMESTAMP>.sqlite
   ```

---

## 📚 Technical Documentation Index

- [`docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md`](docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md) — Administrative key exposure response runbook.
- [`docs/OPERATIONAL_READINESS.md`](docs/OPERATIONAL_READINESS.md) — Infrastructure, backup, disaster recovery, and operational status.
- [`docs/MARKET_READINESS_ASSESSMENT.md`](docs/MARKET_READINESS_ASSESSMENT.md) — Institutional economic analysis and market readiness assessment.
