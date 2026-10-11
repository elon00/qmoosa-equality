import unittest
from men.economics import allocate, issuance_budget
from men.integrations import request_json, require_payment_integration
from men.pqc import encode_manifest

class CoreTests(unittest.TestCase):
    def test_conservation(self):
        for n in (0, 1, 99, 10000, 2**64 - 1):
            self.assertEqual(sum(allocate(n).values()), n)
    def test_distribution(self):
        self.assertEqual(allocate(10000), dict(community_grants=5000, social_enterprises=2500, public_goods=1500, operations=1000))
    def test_bad_amounts(self):
        for value in (-1, True, 1.2, '3'):
            with self.assertRaises(ValueError): allocate(value)
    def test_funding_limit(self):
        self.assertEqual(issuance_budget(10000, 500, 100), 100)
    def test_dilution_limit(self):
        self.assertEqual(issuance_budget(10000, 500, 900), 500)
        with self.assertRaises(ValueError): issuance_budget(10000, 501, 900)
    def test_no_unfunded_issuance(self):
        self.assertEqual(issuance_budget(10000, 500, 0), 0)
    def test_no_plaintext_provider(self):
        with self.assertRaises(ValueError): request_json('http://example.com')
    def test_payment_fail_closed(self):
        with self.assertRaises(RuntimeError): require_payment_integration()
    def test_manifest_order(self):
        self.assertEqual(encode_manifest({'a': 1, 'b': 2}), encode_manifest({'b': 2, 'a': 1}))
    def test_manifest_change(self):
        self.assertNotEqual(encode_manifest({'a': 1}), encode_manifest({'a': 2}))

if __name__ == '__main__': unittest.main()
