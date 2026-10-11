"""Optional off-chain ML-DSA-65; not a FIPS validated product or chain upgrade."""
import json

def encode_manifest(manifest):
    return b'QMOOSA-EQUALITY-MANIFEST-v1\x00' + json.dumps(
        manifest, sort_keys=True, separators=(',', ':'), allow_nan=False
    ).encode()

def sign_manifest(secret_key, manifest):
    from pqcrypto.sign.ml_dsa_65 import sign
    return sign(secret_key, encode_manifest(manifest))

def verify_manifest(public_key, manifest, signature):
    from pqcrypto import InvalidSignatureError
    from pqcrypto.sign.ml_dsa_65 import verify
    try:
        verify(public_key, encode_manifest(manifest), signature)
        return True
    except InvalidSignatureError:
        return False
