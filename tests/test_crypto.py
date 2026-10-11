import unittest
from pqcrypto.sign.ml_dsa_65 import keygen
from men.pqc import sign_manifest, verify_manifest

class CryptographicTests(unittest.TestCase):
    def test_real_signature_and_tampering(self):
        public, secret = keygen()
        document = {'project': 'Qmoosa Equality', 'network': 'testnet', 'nonce': '1'}
        signature = sign_manifest(secret, document)
        self.assertTrue(verify_manifest(public, document, signature))
        self.assertFalse(verify_manifest(public, {**document, 'network': 'mainnet'}, signature))
        other, _ = keygen()
        self.assertFalse(verify_manifest(other, document, signature))
