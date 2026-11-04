# Security Incident Response: Administrative Key Exposure (IR-2026-001)

**Severity**: CRITICAL  
**Status**: ACTIVE MITIGATION / RELEASE BLOCKED  
**Affected Account**: `TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM`  
**Classification**: Administrative Secret Compromise via Session Transcript Exposure  

---

## 1. Executive Summary

During prior deployment interactions, the 25-word mnemonic phrase for the deploying Algorand account was exposed in conversation context. Under industry security standards and the **Reality Gate Protocol**, this account must be permanently treated as **COMPROMISED**.

**Mainnet release is strictly BLOCKED** until all administrative privileges, reserve holdings, and contract administration are formally migrated or rekeyed to an uncompromised address controlled solely by the repository owner (preferably a multisignature account or hardware-backed signer).

---

## 2. Blast Radius & Privilege Inventory

| Resource | Network | Identifier | Role Held by Compromised Key | Impact |
| :--- | :--- | :--- | :--- | :--- |
| **QEQ Asset** | Mainnet | `3737683297` | Manager, Reserve, Creator | Attacker with key could change manager/reserve |
| **QEQ Asset** | Testnet | `774088414` | Manager, Reserve, Creator | Attacker with key could alter testnet metadata |
| **Treasury Contract** | Testnet | `774088598` | Admin, Creator | Attacker could call admin-gated methods |
| **Native ALGO** | Mainnet | `TPLMGGFN...` | Account Owner | ~20.67 ALGO balance at risk |
| **Native ALGO** | Testnet | `TPLMGGFN...` | Account Owner | ~9.79 ALGO balance at risk |

*Note: For both ASAs, `freeze` and `clawback` were permanently set to `None` upon creation, meaning token balances cannot be frozen or seized.*

---

## 3. Remediation & Migration Protocol

To secure the protocol without exposing any secrets, all operations must follow an **offline, owner-controlled signing process**. No private keys or recovery phrases should ever be entered into chat, shell history, or version control.

### Option A: Rekeying (Recommended by Algorand Architecture)
Algorand provides native L1 **Account Rekeying**, allowing the account `TPLMGGFN...` to delegate authorization entirely to an uncompromised Target Address, permanently stripping the exposed private key of all authority while preserving the public address.

1. Generate a new, secure Algorand account offline (e.g. Ledger or 2-of-3 Multisig: Target Address `SECURE_TARGET_ADDR`).
2. Submit an unsigned Rekey transaction:
   ```bash
   python scripts/rotate_authority_txns.py --rekey-to SECURE_TARGET_ADDR --network mainnet
   ```
3. Sign the resulting `rekey-mainnet.unsigned` transaction in your secure wallet and broadcast it.
4. After confirmation, the exposed mnemonic is cryptographically disabled from signing any future transactions for `TPLMGGFN...`.

### Option B: Manager & Reserve Asset Reconfiguration
If the owner prefers to migrate the Asset Manager authority directly:
1. Generate unsigned `AssetConfigTxn`:
   ```bash
   python scripts/rotate_authority_txns.py --new-manager SECURE_TARGET_ADDR --network mainnet
   ```
2. Review the transaction parameters:
   - `Asset ID`: `3737683297`
   - `Sender`: `TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM`
   - `New Manager`: `SECURE_TARGET_ADDR`
   - `New Reserve`: `SECURE_TARGET_ADDR`
3. Sign offline and broadcast.

### Option C: Treasury Application Hardening & Redeployment
Application `774088598` was created with `admin = TPLMGGFN...` in global state without an administrative rotation subroutine.
- The hardened v2 contract ([`contracts/hardened_treasury_app.py`](../contracts/hardened_treasury_app.py)) includes explicit `rotate_admin(new_admin)`, reservation accounting, and per-grant limits.
- Deploy the hardened contract using `SECURE_TARGET_ADDR` on Testnet.

---

## 4. Verification Checkpoint (Release Gate Rule)

Mainnet deployment readiness and production release verification will remain **FAIL-CLOSED (BLOCKED)** until:
1. `mainnet_manager != TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM` OR on-chain rekey evidence is verified.
2. The remaining Mainnet ALGO balance is transferred to the secure owner address.
3. An independent security review verifies the rotation on-chain.
