# Qmoosa Equality

An experimental Algorand economic-inclusion project for Moolnivasi, SC, ST,
OBC, minorities, and underserved communities worldwide. An independent initiative
for economic inclusion; token issuance alone does not eliminate poverty.

**Repository**: `elon00/qmoosa-equality` | **Ticker**: `QEQ` | **Standard**: Algorand Standard Asset (ASA)

---

## 🛡️ Reality Gate Protocol (Zero Simulation)

This project strictly operates under the **Reality Gate**:
- **Zero Simulation / Zero Mock**: No synthetic RPC data, mock responses, or fake deployment claims are ever used.
- **Fail-Closed Conjunction**: If any cryptographic proof, funded on-chain balance, or security audit requirement is missing, execution halts closed with an explicit error code.
- **Post-Quantum Cryptography**: Real C-extension execution of NIST FIPS 204 **ML-DSA-65** for domain-separated manifest signing and tamper verification.

Detailed specifications can be found in the **[Official Wiki](wiki/Home.md)**:
- [Reality Gate Specification](wiki/Reality-Gate.md)
- [Algorand Testnet Deployment](wiki/Algorand-Testnet-Deployment.md)
- [Algorand Mainnet Deployment](wiki/Algorand-Mainnet-Deployment.md)
- [Post-Quantum Cryptography](wiki/Post-Quantum-Cryptography.md)
- [Tokenomics & Social Inclusion](wiki/Tokenomics-and-Inclusion.md)

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
python scripts/check.py
```

`python scripts/check.py --release` intentionally exits `2` while release is blocked, preventing false claims of production readiness. Passing component tests does not mean a deployment or financial system is safe.

---

## 🌐 Algorand Blockchain Deployment

### 1. Testnet Deployment (Stage 1 Gate)

The deployment script interacts with real Algorand Testnet nodes (`https://testnet-api.algonode.cloud`):

```powershell
python scripts/deploy_testnet.py --mnemonic "YOUR_25_WORD_MNEMONIC"
```

> **Reality Gate Check**:
> The deploying account must have at least **0.2 ALGO** on Testnet. If the account balance is `0.0 ALGO`, the script refuses to simulate deployment and outputs the official dispenser link:
> **Fund free Testnet ALGO**: [https://lora.algokit.io/testnet/fund](https://lora.algokit.io/testnet/fund)

### 2. Mainnet Deployment (Stage 3 Gate)

Deploying to Mainnet permanently creates an immutable ASA on the public Algorand blockchain and consumes real ALGO for the Minimum Balance Requirement (MBR) and network fees:

```powershell
python scripts/deploy_mainnet.py --mnemonic "YOUR_25_WORD_MNEMONIC" --confirm-mainnet
```

> **Mainnet Safeguards**:
> - Requires explicit `--confirm-mainnet` flag.
> - Verifies live genesis `mainnet-v1.0` and queries live Mainnet balance.
> - Fixed supply of 1,000,000 QEQ (1,000,000,000,000 base units at 6 decimals).
> - Freeze and Clawback addresses are permanently set to `None` to guarantee non-custodial and censorship-resistant transfers.

---

## 🔍 What Exists Today

- **Integer allocation and funded issuance-budget calculations**: Strict integer math with remainder allocation to community grants ($sum \equiv n$).
- **Real off-chain ML-DSA-65 signature adapter**: Implemented with `pqcrypto` and verified against document tampering.
- **HTTPS adapters**: Secure client for OpenAI-compatible chat providers and x402 discovery.
- **Algorand Testnet & Mainnet deployment scripts**: Real on-chain ASA creation scripts using official Algorand SDK.
- **Fail-closed CI/CD verification**: GitHub Actions workflows validating component tests and release blockers.
- **Complete Reality Gate Wiki documentation**: Comprehensive architectural guides in `wiki/`.

---

## ⚠️ What Does Not Exist Yet

Grant/treasury smart contracts (TEAL/PyTeal), unlimited issuance contract, end-user frontend,
multi-chain wallet signing, Conway runtime integration, x402 settlement,
production chatbot routing, independent security audit and live deployments.
See [`STATUS.json`](STATUS.json). No fake RPC responses, asset IDs or success manifests are supplied.

---

## 🔐 Security Boundaries

- Never paste wallet seeds into chat or commit them to git.
- Application signatures do not replace Algorand transaction signatures or make the blockchain itself PQ-safe.
- AI must never receive custody or autonomously approve beneficiaries or funds.
- Standard ASA supply is fixed at creation; an unlimited-supply model requires custom smart contract architecture.

See [`docs/DESIGN.md`](docs/DESIGN.md) for full tokenomics and implementation specifications.
