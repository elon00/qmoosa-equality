# Algorand Testnet Deployment Guide

Under the **Reality Gate** protocol, deployment to Algorand Testnet must execute against live blockchain nodes using real accounts. Simulated deployments, mock responses, or fake transaction IDs are strictly forbidden.

---

## 🛠️ Prerequisites

1. **Python Environment**:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate       # Windows
   pip install -r requirements.txt
   ```
2. **Funded Algorand Testnet Account**:
   - The deploying account must have at least **0.2 ALGO** on Testnet to cover the Minimum Balance Requirement (MBR) of 0.1 ALGO for ASA creation plus transaction fees (0.001 ALGO).
   - Testnet Address: `TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM`

---

## 🚰 Funding Testnet Account (Free)

1. Open the official [Algorand Testnet Dispenser (Lora)](https://lora.algokit.io/testnet/fund).
2. Paste the target address:
   ```text
   TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM
   ```
3. Complete the verification and click **Dispense**.
4. 10 Testnet ALGO will be credited to the account within seconds.

---

## 🚀 Running the Real Deployment

Run the automated deployment script:

```powershell
python scripts/deploy_testnet.py --mnemonic "YOUR_25_WORD_MNEMONIC"
```

Or set the environment variable:
```powershell
$env:ALGORAND_MNEMONIC = "YOUR_25_WORD_MNEMONIC"
python scripts/deploy_testnet.py
```

### Reality Gate Execution Sequence
1. **Network Check**: Connects to AlgoNode Testnet (`https://testnet-api.algonode.cloud`) and verifies genesis ID `testnet-v1.0`.
2. **On-Chain Balance Check**: Queries the real account balance. If balance is below 0.2 ALGO, it immediately halts fail-closed without broadcasting.
3. **Asset Creation**: Generates and signs an Algorand Standard Asset (`AssetConfigTxn`) creation for **Qmoosa Equality (`QEQ`)** with 1,000,000 tokens (6 decimals = 1,000,000,000,000 base units).
4. **Broadcast & Confirmation**: Broadcasts the signed transaction to the blockchain pool and waits for block finality (`transaction.wait_for_confirmation`).
5. **Ledger Verification**: Prints the on-chain Asset ID, confirmed round, transaction hash, and Lora Explorer URL. Updates `STATUS.json`.
