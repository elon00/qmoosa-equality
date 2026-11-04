# Qmoosa Equality: Tokenomics & Issuance Architecture Specification

**Status**: PROPOSED POLICY / FIXED ON-CHAIN ASA  
**Asset ID (Mainnet)**: `3737683297`  
**Asset ID (Testnet)**: `774088414`  

---

## 1. Mathematical Baseline & Supply Verification

The on-chain ledger records:
- **Total Supply (Base Units)**: `1,000,000,000,000` (uint64)
- **Decimals**: `6`
- **Total Minted Supply**:
  $$\text{Total Supply} = \frac{1,000,000,000,000}{10^6} = 1,000,000.000000 \text{ QEQ}$$
- **Circulating Supply**: Currently **0 QEQ** (100% of supply is held by the reserve address, pending transfer into the hardened treasury escrow contract).

> [!IMPORTANT]
> **Definitive Supply Truth**: Under Algorand L1 consensus, an Algorand Standard Asset (ASA) has an **immutable total supply**. The total cannot be increased or printed on-chain without creating a completely new asset. Therefore, QEQ is currently a **fixed-supply token capped at 1,000,000 QEQ**, not an unlimited-supply currency.

---

## 2. Evaluation of Issuance Architectures

To address long-term community economic inclusion, three architectures are evaluated:

| Architecture | Mechanism | Dilution Risk | Wallet Compatibility | Governance Complexity | Migration Burden |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Model A: Fixed ASA + Treasury Escrow (Selected Baseline)** | Fixed 1,000,000 QEQ minted at genesis; 100% held in reserve and unlocked via stateful treasury contracts. | Zero unexpected dilution; capped forever. | 100% native Algorand wallet compatibility (Pera, Defly, Ledger). | Low: Admin/Multisig proposes grants; timelocked claims. | None for ASA; requires Treasury v2 on-chain deployment. |
| **Model B: Smart Contract Mintable Token (ARC-200)** | Application-managed balance ledger simulating ERC-20 on Algorand. Allows minting via contract logic. | Controlled by contract logic, but introduces bug/inflation risk. | Requires ARC-200 indexer and custom wallet support; limited DEX support. | High: DAO/Multisig manages minter keys. | High: Requires deploying application and migrating holders. |
| **Model C: Multi-Asset Epoch Series** | Discrete ASAs issued each funding epoch (e.g. `QEQ-2026`, `QEQ-2027`). | Isolated per epoch; no retroactive dilution. | Good for base transfers, but fragments liquidity across assets. | Moderate: Each asset requires separate configuration. | High: Separate liquidity pools and opt-ins required per epoch. |

**Engineering Recommendation**: **Model A** is selected as the baseline architecture. On-chain deployment currently includes only the ASA on Mainnet/Testnet; deploying the Hardened Treasury v2 contract and transferring reserve holdings into it are mandatory prerequisites for production release. Model B (ARC-200) should only be evaluated following an independent smart contract audit and widespread DEX ecosystem adoption.

---

## 3. Allocation Policy: Proposed vs. Enforced Status

The proposed token allocation across funded programs is:

```
  ┌─────────────────────────────────────────────────────────────┐
  │  Total Minted: 1,000,000 QEQ (1,000,000,000,000 base units)  │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
   Community Grants      Social Enterprises       Public Goods / Ops
   500,000 QEQ (50%)     250,000 QEQ (25%)        150,000 / 100,000 (15%/10%)
```

- **50% Community Grants (`5000 bps`)**: 500,000 QEQ dedicated to direct livelihood support, educational tools, and basic needs grants.
- **25% Social Enterprises (`2500 bps`)**: 250,000 QEQ allocated to cooperative capital and micro-enterprise loans.
- **15% Public Goods (`1500 bps`)**: 150,000 QEQ for community learning centers and open software.
- **10% Transparent Operations (`1000 bps`)**: 100,000 QEQ for auditing, node infrastructure, and operational overhead.

> [!WARNING]
> **Legal & Architectural Disclosure**: This allocation represents **Proposed Governance Policy**. Until reserve tokens are transferred into verified, timelocked on-chain smart contracts ([`contracts/hardened_treasury_app.py`](../contracts/hardened_treasury_app.py)), it is not cryptographically enforced by L1 consensus.

---

## 4. Financial Runway, Dilution, & Adverse Risk Modeling

Token issuance is a coordination mechanism, not revenue or collateral. Issuing tokens does not create economic value without real-world utility, grants, and enterprise survival.

### Dilution & Issuance Cap:
$$\text{Annual Issuance Budget} \le \min\left(\frac{\text{Previous Supply} \times 500}{10000}, \text{Verified Funding}\right)$$
The proposed annual new issuance ceiling is **5% (500 bps)** (applicable only to any future asset or epoch series, as the genesis ASA supply is mathematically fixed on-chain), with unfunded printing strictly forbidden.

### Runway Scenarios:
1. **Conservative Disbursement**: 50,000 QEQ disbursed per year $\rightarrow$ 20-year operational runway.
2. **Accelerated Inception**: 200,000 QEQ Year 1 bootstrap, followed by 50,000 QEQ/yr $\rightarrow$ 17-year runway.

### Adverse Scenarios & Mitigations:
- **Zero Liquidity / Pre-Market**: QEQ currently has no live AMM liquidity or fiat on-ramps. Grantees must not be promised cash conversion.
- **Price Volatility**: Tokens must not be treated as a stablecoin or guaranteed wage. Grants fund capacity, not speculative speculation.
- **Concentration Risk**: The reserve account initially holds 100% of supply. Mitigated by moving reserve into multisig governance and the hardened treasury contract.

---

## 5. ARC-3 Metadata Specification & Audit

The metadata file [`assets/qeq_arc3_metadata.json`](../assets/qeq_arc3_metadata.json) adheres to the **ARC-0003** specification:

```json
{
  "name": "Qmoosa Equality",
  "symbol": "QEQ",
  "unitName": "QEQ",
  "decimals": 6,
  "description": "Algorand economic-inclusion asset for Moolnivasi, SC, ST, OBC, minorities, and underserved communities.",
  "image": "https://raw.githubusercontent.com/elon00/qmoosa-equality/main/assets/qeq_logo.png",
  "properties": {
    "standard": "ARC-0003",
    "totalSupply": 1000000000000,
    "allocations": {
      "community_grants_bps": 5000,
      "social_enterprises_bps": 2500,
      "public_goods_bps": 1500,
      "operations_bps": 1000
    }
  }
}
```

**ARC-3 Audit Findings**:
1. **Name Length**: 15 bytes (under 32-byte ASA limit).
2. **Unit Name Length**: 3 bytes (under 8-byte ASA limit).
3. **Decimals**: 6 (Standard for Algorand ecosystem).
4. **Current On-Chain URL**: Currently points to `https://github.com/elon00/qmoosa-equality`.
5. **Next Step**: When manager authority is rotated, submit an `AssetConfigTxn` updating URL to append `#arc3` or point to an IPFS CID (`ipfs://...#arc3`).
