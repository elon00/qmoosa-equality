# Post-Quantum Cryptography (ML-DSA-65)

**Qmoosa Equality** incorporates post-quantum cryptographic primitives to guarantee long-term data integrity and manifest authenticity beyond the lifespan of classical public-key cryptography (RSA/ECDSA).

---

## 🔬 Standards & Algorithm

- **Algorithm**: **ML-DSA-65** (Module-Lattice-Based Digital Signature Standard).
- **Specification**: **NIST FIPS 204** (derived from CRYSTALS-Dilithium).
- **Security Level**: NIST Security Category 3 (equivalent to AES-192 brute-force security).
- **Implementation**: Real binary extension via the `pqcrypto` package (`pqcrypto.sign.ml_dsa_65`).

---

## 🛡️ Manifest Canonicalization & Domain Separation

To prevent cross-protocol signature forgery and canonical JSON parsing ambiguities, every signed payload is strictly domain-separated:

```python
def encode_manifest(manifest):
    return b'QMOOSA-EQUALITY-MANIFEST-v1\x00' + json.dumps(
        manifest, sort_keys=True, separators=(',', ':'), allow_nan=False
    ).encode()
```

### Properties:
1. **Domain Separator**: `b'QMOOSA-EQUALITY-MANIFEST-v1\x00'` ensures signatures cannot be replayed into other systems or formats.
2. **Canonical JSON**:
   - `sort_keys=True` ensures deterministic dictionary key order.
   - `separators=(',', ':')` eliminates variable whitespace differences.
   - `allow_nan=False` prevents non-standard floating point serialization issues.

---

## 🧪 Real Verification Test Suite

Tested in `tests/test_crypto.py`:
- Generates real keypair: `public_key, secret_key = keygen()`
- Signs canonical manifest: `sig = sign_manifest(secret_key, doc)`
- Verifies authenticity: `verify_manifest(public_key, doc, sig) == True`
- Proves tamper resistance: Any modification to the document (e.g., `'network': 'mainnet'`) produces `False`.
- Proves key mismatch resistance: An unauthorized key produces `False`.
