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

- **Release Status**: **MAINNET PRODUCTION RELEASE IS STRICTLY BLOCKED** until administrative manager and reserve authorities are rotated on-chain to an uncompromised address via owner-controlled wallet signing.
- **Unsigned Migration Tool**: Run `python scripts/rotate_authority_txns.py --network mainnet --new-manager <TARGET_ADDR>` to generate unsigned rotation transactions for offline/hardware wallet signing.
- **Runbook**: See [`docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md`](docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md).

---

## 🌐 Verified On-Chain Deployments

| Network | Asset Name | Ticker | Asset ID | Confirmed Round | Transaction Hash | Explorer Link |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Algorand Testnet** | Qmoosa Equality | `QEQ` | [`774088414`](https://lora.algokit.io/testnet/asset/774088414) | `68171764` | `GDMORMEM...` | [Lora Testnet Asset](https://lora.algokit.io/testnet/asset/774088414) |
| **Algorand Mainnet** | Qmoosa Equality | `QEQ` | [`3737683297`](https://lora.algokit.io/mainnet/asset/3737683297) | `65891166` | `U5LVAFLK...` | [Lora Mainnet Asset](https://lora.algokit.io/mainnet/asset/3737683297) |
| **Testnet Treasury** | Community Escrow | `APP` | [`774088598`](https://lora.algokit.io/testnet/application/774088598) | `68171916` | `X3G65FE2...` | [Lora Treasury App](https://lora.algokit.io/testnet/application/774088598) |

---

## 🛡️ Reality Gate Protocol (Zero Simulation)

This project strictly operates under the **Reality Gate**:
- **Zero Simulation / Zero Mock**: Real Algorand blockchain RPC queries and real C-extension execution of NIST FIPS 204 **ML-DSA-65** post-quantum cryptography.
- **Fail-Closed Conjunction**: If any cryptographic proof, database integrity check, or security requirement is missing, verification halts closed with an explicit error code.

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

### Complete Verification Suite
```bash
python scripts/check.py
```

### Modular Audit Commands
- `python scripts/check.py --components`: Runs mathematical allocation and NIST ML-DSA-65 crypto tests.
- `python scripts/check.py --contracts`: Compiles and tests TEAL 8 smart contract security and anti-drain logic.
- `python scripts/check.py --api`: Tests SQLite persistent database, Pydantic validations, and API routes.
- `python scripts/check.py --onchain`: Queries live Algorand Mainnet and Testnet nodes for active ledger proofs.
- `python scripts/check.py --release`: Evaluates production release readiness (intentionally **FAILS CLOSED** with exit code 2 until Incident IR-2026-001 is resolved).

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

3. **Database Backup & Restoration**:
   ```bash
   # Create snapshot with SHA-256 checksum:
   python scripts/db_backup_restore.py backup

   # Restore snapshot:
   python scripts/db_backup_restore.py restore data/backups/qmoosa_db_<TIMESTAMP>.sqlite
   ```

---

## 📚 Technical Documentation Index

- [`docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md`](docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md) — Administrative key exposure response runbook.
- [`docs/OPERATIONAL_READINESS.md`](docs/OPERATIONAL_READINESS.md) — Infrastructure, backup, disaster recovery, and operational status.
- [`docs/MARKET_READINESS_REPORT.md`](docs/MARKET_READINESS_REPORT.md) — Liquidity, DEX trading, exchange listings, and legal analysis.
- [`docs/TOKENOMICS_AND_ISSUANCE.md`](docs/TOKENOMICS_AND_ISSUANCE.md) — Fixed ASA supply analysis, integer economics, and runway modeling.
- [`docs/INTEGRATIONS_ANALYSIS.md`](docs/INTEGRATIONS_ANALYSIS.md) — Technical specifications and limitations (x402, Conway, AI, PQC).
- [`docs/DESIGN.md`](docs/DESIGN.md) — Original core design document.
- [`STATUS.json`](STATUS.json) — Structured requirement-to-evidence matrix and blocker registry.
- [`wiki/`](wiki/) — Full offline documentation suite.
