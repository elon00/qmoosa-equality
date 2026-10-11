# Algorand Mainnet Deployment Specification

Deploying to **Algorand Mainnet** represents Stage 3 of the **Reality Gate**. Unlike Testnet, Mainnet transactions permanently record immutable assets on the global public ledger and consume real financial value.

---

## ⚠️ Reality Gate Rules for Mainnet Deployment

Under the non-negotiable **Zero Simulation / Zero Mock** rule:

1. **Testnet Precedent Required**: Mainnet deployment should only proceed after successful verification on Testnet.
2. **Immutable Supply Notice**: A standard Algorand Standard Asset (ASA) has an **immutable total supply** set at creation time. An unlimited-issuance economic model cannot be represented by a standard ASA; it requires custom smart contracts (TEAL/PyTeal).
3. **Financial Responsibility**: ASA creation on Mainnet locks a Minimum Balance Requirement (MBR) of 0.1 ALGO and incurs transaction network fees.
4. **Deployer Identity**: The deploying account must have real Mainnet ALGO balance.

---

## 📋 Asset Parameters (Mainnet Proposal)

| Parameter | Value | Details |
| :--- | :--- | :--- |
| **Asset Name** | `Qmoosa Equality` | Official on-chain asset name |
| **Unit Name** | `QEQ` | On-chain ticker symbol |
| **Decimals** | `6` | 1 QEQ = 1,000,000 base units |
| **Total Supply** | `1,000,000,000,000` | 1,000,000 QEQ base units |
| **Default Frozen** | `false` | Freely transferable upon opt-in |
| **Manager Address** | Deployer Address | Allows updating metadata/reserve |
| **Reserve Address** | Deployer Address | Holding address for unreleased supply |
| **Freeze Address** | `None` | Unfreezable (non-custodial protection) |
| **Clawback Address**| `None` | Unclawbackable (censorship resistant) |
| **URL** | `https://github.com/elon00/qmoosa-equality` | Repository audit link |

---

## 🚀 Execution Script (`scripts/deploy_mainnet.py`)

```powershell
python scripts/deploy_mainnet.py --mnemonic "YOUR_25_WORD_MNEMONIC" --confirm-mainnet
```

### Reality Gate Safety Safeguard:
The deployment script requires the explicit flag `--confirm-mainnet` and interactive confirmation to avoid accidental mainnet transactions. It checks the live Mainnet balance using AlgoNode Mainnet (`https://mainnet-api.algonode.cloud`) and verifies the genesis ID `mainnet-v1.0`.
