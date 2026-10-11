# Tokenomics & Social Inclusion

The economic design of **Qmoosa Equality** (`QEQ`) is built specifically for transparent economic inclusion of Moolnivasi, Scheduled Castes (SC), Scheduled Tribes (ST), Other Backward Classes (OBC), minority groups, and vulnerable communities worldwide.

---

## 🎯 Purpose and Mission

- **Real Economic Inclusion**: Token issuance alone does not eliminate poverty. The system prioritizes funding real community livelihood grants, social enterprise capital, vocational training, and transparent public goods.
- **Surplus Reinvestment**: Social enterprises supported by the platform reinvest surplus revenue into community outcomes.
- **No Speculative Promises**: QEQ is an inclusion and utility coordination mechanism, not a get-rich-quick instrument or yield-farming token.

---

## 💰 Integer Allocation Model

All budget allocations are calculated in integer basis points ($1 \text{ bps} = 0.01\%$) with strictly **zero floating-point arithmetic**:

| Category | Share | Basis Points (bps) | Description |
| :--- | :--- | :--- | :--- |
| **Community Grants** | **50%** | `5000` | Direct livelihood & education grants (+ any remainder) |
| **Social Enterprises** | **25%** | `2500` | Micro-enterprise and cooperative development capital |
| **Public Goods** | **15%** | `1500` | Open educational resources, local community amenities |
| **Operations** | **10%** | `1000` | Transparent operational, technical, and auditing costs |

### Conservation Law:
$$\sum \text{Allocated Units} \equiv \text{Total Funded Units}$$
Any remainder from integer division is automatically allocated to `community_grants` to guarantee zero loss or fractional leakage.

---

## 🔒 Dilution Ceiling & Funding Constraints

1. **5% Annual Dilution Ceiling**: Annual new issuance budget is strictly capped at $500\text{ bps}$ ($5\%$) of the previous circulating supply.
2. **Funded Issuance Constraint**: New tokens can only be minted up to the amount backed by real verifiable funding:
   $$\text{issuance\_budget} = \min\left(\frac{\text{previous\_supply} \times \text{annual\_bps}}{10000}, \text{funded\_units}\right)$$
   Unfunded printing is rejected with a `0` allocation.

---

## 🔏 Privacy & Ethics Standard

- **No On-Chain Identity/Caste Tagging**: Sensitive personal identities, caste categories, and religious affiliations are **strictly prohibited** from being published on-chain, even as deterministic hashes.
- **Encrypted Off-Chain Verification**: Partner-verified eligibility documents remain encrypted off-chain with strict right-to-deletion and appeal workflows.
- **Accountable Human Governance**: AI models never have automated authority to accept/deny claims or disburse community funds.
