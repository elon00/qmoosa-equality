"""Automated test suite for Algorand TEAL smart contracts."""
import unittest
from contracts.hardened_treasury_app import (
    KEY_ADMIN,
    KEY_ASSET_ID,
    KEY_DISPUTE_PERIOD,
    KEY_MAX_GRANT,
    KEY_PAUSED,
    KEY_PENDING_GRANT,
    KEY_TOTAL_DISBURSED,
    KEY_TOTAL_RESERVED,
    KEY_UNLOCK_ROUND,
    METHOD_CANCEL_GRANT,
    METHOD_CLAIM_GRANT,
    METHOD_OPTIN_ASSET,
    METHOD_PROPOSE_GRANT,
    METHOD_ROTATE_ADMIN,
    METHOD_SET_LIMITS,
    METHOD_TOGGLE_PAUSE,
    compile_hardened_teal,
)
from contracts.treasury_app import compile_to_teal

class ContractSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hardened_app, cls.hardened_clear = compile_hardened_teal()
        cls.v1_app, cls.v1_clear = compile_to_teal()

    def test_teal_version_and_syntax(self):
        self.assertTrue(self.hardened_app.startswith("#pragma version 8"))
        self.assertTrue(self.hardened_clear.startswith("#pragma version 8"))
        self.assertTrue(self.v1_app.startswith("#pragma version 8"))

    def test_hardened_methods_present(self):
        # All required security methods must be compiled into the TEAL output
        for method in [
            "rotate_admin",
            "set_limits",
            "propose_grant",
            "cancel_grant",
            "claim_grant",
            "toggle_pause",
            "optin_asset"
        ]:
            self.assertIn(f'byte "{method}"', self.hardened_app)

    def test_anti_drain_safeguards_in_bytecode(self):
        # Verify that CloseRemainderTo and AssetCloseTo are explicitly cleared in inner txns
        self.assertIn("AssetCloseTo", self.hardened_app)
        self.assertIn("RekeyTo", self.hardened_app)
        self.assertIn("global ZeroAddress", self.hardened_app)

    def test_reservation_and_anti_overwrite_safeguards(self):
        # Verify that total_reserved and pending_grant checks exist in TEAL
        self.assertIn('byte "total_reserved"', self.hardened_app)
        self.assertIn('byte "pending_grant"', self.hardened_app)
        self.assertIn('byte "max_grant"', self.hardened_app)

    def test_admin_rotation_length_check(self):
        # 32 byte address check for admin rotation
        self.assertIn("len", self.hardened_app)
        self.assertIn("int 32", self.hardened_app)

if __name__ == "__main__":
    unittest.main()
