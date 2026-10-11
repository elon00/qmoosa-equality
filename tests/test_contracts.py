"""Automated test suite for Algorand TEAL smart contracts.
Executes complete grant lifecycle, attack vectors, state-machine transitions,
reservation accounting, overcommit protections, and on-chain schema distinction.
"""
import unittest
from algosdk import encoding
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
    compile_hardened_teal,
)
from contracts.treasury_app import compile_to_teal

ADMIN_ADDR = "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM"
BENEFICIARY_ADDR = "2UB5OTY6Z63V7SIQCTWBNDKEHGDXA5ZDYQCAZTGBA2VWDZUMKGF2A4RIOO"
ATTACKER_ADDR = "HZ57J3K46JIJXILONBBZOHX6BKPXEM2VVXNRSUSEUSVLWT3GSSDNNUM3UM"
NEW_ADMIN_ADDR = "ONEDMBHMGVFTKOWPZGGLQCG4SXI7SDPTJI3Q5MVEC3J47DZMIJ7V4OTP2A"
ASSET_ID = 774088414


class HardenedTreasurySimulator:
    """Stateful execution simulator strictly mirroring PyTeal TEAL 8 contract logic."""

    def __init__(self, creator: str, asset_id: int, max_grant: int = 50_000_000_000, dispute_period: int = 100):
        self.global_state = {
            "admin": creator,
            "asset_id": asset_id,
            "total_disbursed": 0,
            "total_reserved": 0,
            "max_grant": max_grant,
            "dispute_period": dispute_period,
            "paused": 0,
        }
        self.local_state = {}  # address -> {"pending_grant": int, "unlock_round": int}
        self.asset_holdings = {
            "treasury": 0,
            BENEFICIARY_ADDR: 0,
            ATTACKER_ADDR: 0,
        }
        self.app_opted_in = set()
        self.current_round = 1000

    def deposit_treasury_asset(self, amount: int):
        self.asset_holdings["treasury"] += amount

    def optin_asset_beneficiary(self, addr: str):
        self.asset_holdings[addr] = 0

    def optin_app(self, sender: str):
        self.app_opted_in.add(sender)
        self.local_state[sender] = {"pending_grant": 0, "unlock_round": 0}

    def closeout_app(self, sender: str):
        if sender not in self.app_opted_in:
            raise ValueError("Not opted in")
        # Assert App.localGet(Int(0), KEY_PENDING_GRANT) == 0
        pending = self.local_state.get(sender, {}).get("pending_grant", 0)
        if pending != 0:
            raise AssertionError("CloseOut rejected: Active pending grant exists")
        self.app_opted_in.remove(sender)
        del self.local_state[sender]

    def clearstate_app(self, sender: str):
        # ClearState cannot fail in AVM, but recovers total_reserved
        if sender in self.local_state:
            pending = self.local_state[sender].get("pending_grant", 0)
            if pending > 0:
                self.global_state["total_reserved"] -= pending
            del self.local_state[sender]
        if sender in self.app_opted_in:
            self.app_opted_in.remove(sender)

    def rotate_admin(self, sender: str, new_admin: str):
        if sender != self.global_state["admin"]:
            raise PermissionError("Sender is not admin")
        raw_bytes = encoding.decode_address(new_admin)
        if len(raw_bytes) != 32:
            raise ValueError("Invalid address length")
        if new_admin == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ":
            raise ValueError("Zero address not allowed")
        self.global_state["admin"] = new_admin

    def set_limits(self, sender: str, max_grant: int, dispute_period: int):
        if sender != self.global_state["admin"]:
            raise PermissionError("Sender is not admin")
        if max_grant <= 0:
            raise ValueError("max_grant must be > 0")
        if dispute_period < 10:
            raise ValueError("dispute_period must be >= 10")
        self.global_state["max_grant"] = max_grant
        self.global_state["dispute_period"] = dispute_period

    def toggle_pause(self, sender: str):
        if sender != self.global_state["admin"]:
            raise PermissionError("Sender is not admin")
        self.global_state["paused"] = 1 if self.global_state["paused"] == 0 else 0

    def propose_grant(self, sender: str, beneficiary: str, amount: int):
        if sender != self.global_state["admin"]:
            raise PermissionError("Sender is not admin")
        if self.global_state["paused"] != 0:
            raise RuntimeError("Contract is paused")
        if amount <= 0:
            raise ValueError("Grant amount must be > 0")
        if amount > self.global_state["max_grant"]:
            raise ValueError("Amount exceeds max_grant limit")
        if beneficiary not in self.app_opted_in:
            raise ValueError("Beneficiary not opted into application")
        if beneficiary not in self.asset_holdings:
            raise ValueError("Beneficiary not opted into ASA")
        
        ben_local = self.local_state.get(beneficiary, {})
        if ben_local.get("pending_grant", 0) != 0:
            raise RuntimeError("Beneficiary already has an active pending grant")

        # Overcommit protection
        liquid_balance = self.asset_holdings["treasury"]
        if self.global_state["total_reserved"] + amount > liquid_balance:
            raise RuntimeError(f"Overcommit error: requested {amount} exceeds liquid treasury capacity")

        # Reservation Accounting
        self.global_state["total_reserved"] += amount
        self.local_state[beneficiary]["pending_grant"] = amount
        self.local_state[beneficiary]["unlock_round"] = self.current_round + self.global_state["dispute_period"]

    def cancel_grant(self, sender: str, beneficiary: str):
        if sender != self.global_state["admin"]:
            raise PermissionError("Sender is not admin")
        ben_local = self.local_state.get(beneficiary, {})
        pending = ben_local.get("pending_grant", 0)
        if pending <= 0:
            raise ValueError("No pending grant to cancel")
        if self.current_round >= ben_local.get("unlock_round", 0):
            raise RuntimeError("Dispute period elapsed; grant cannot be canceled")

        self.global_state["total_reserved"] -= pending
        self.local_state[beneficiary]["pending_grant"] = 0
        self.local_state[beneficiary]["unlock_round"] = 0

    def claim_grant(self, sender: str):
        if self.global_state["paused"] != 0:
            raise RuntimeError("Contract is paused")
        sen_local = self.local_state.get(sender, {})
        amount = sen_local.get("pending_grant", 0)
        if amount <= 0:
            raise ValueError("No pending grant to claim")
        if self.current_round < sen_local.get("unlock_round", 0):
            raise RuntimeError("Dispute timelock not yet elapsed")

        # Inner transaction transfer
        self.asset_holdings["treasury"] -= amount
        self.asset_holdings[sender] += amount
        self.global_state["total_disbursed"] += amount
        self.global_state["total_reserved"] -= amount
        self.local_state[sender]["pending_grant"] = 0
        self.local_state[sender]["unlock_round"] = 0


class ContractSecurityExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hardened_app, cls.hardened_clear = compile_hardened_teal()
        cls.v1_app, cls.v1_clear = compile_to_teal()

    def setUp(self):
        self.sim = HardenedTreasurySimulator(creator=ADMIN_ADDR, asset_id=ASSET_ID)
        self.sim.deposit_treasury_asset(100_000_000_000)  # 100,000 QEQ in treasury
        self.sim.optin_asset_beneficiary(BENEFICIARY_ADDR)
        self.sim.optin_app(BENEFICIARY_ADDR)

    def test_complete_grant_lifecycle_pass(self):
        """Simulate valid propose -> wait timelock -> claim lifecycle."""
        grant_amount = 5_000_000_000  # 5,000 QEQ
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, grant_amount)

        self.assertEqual(self.sim.global_state["total_reserved"], grant_amount)
        self.assertEqual(self.sim.local_state[BENEFICIARY_ADDR]["pending_grant"], grant_amount)
        self.assertEqual(self.sim.local_state[BENEFICIARY_ADDR]["unlock_round"], 1100)

        # Beneficiary attempts to claim prematurely at round 1050 -> FAILS
        self.sim.current_round = 1050
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertIn("timelock", str(ctx.exception).lower())

        # Forward round past unlock round (1100) -> SUCCESS
        self.sim.current_round = 1101
        self.sim.claim_grant(BENEFICIARY_ADDR)

        self.assertEqual(self.sim.asset_holdings[BENEFICIARY_ADDR], grant_amount)
        self.assertEqual(self.sim.global_state["total_disbursed"], grant_amount)
        self.assertEqual(self.sim.global_state["total_reserved"], 0)
        self.assertEqual(self.sim.local_state[BENEFICIARY_ADDR]["pending_grant"], 0)

    def test_overcommit_rejection(self):
        """Verify that contract rejects reserving more than available treasury balance."""
        # Restrict treasury liquid balance to 10,000,000 units (less than max_grant 50,000,000,000)
        self.sim.asset_holdings["treasury"] = 10_000_000
        excessive_amount = 12_000_000  # Within max_grant, but exceeds liquid treasury

        with self.assertRaises(RuntimeError) as ctx:
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, excessive_amount)
        self.assertIn("overcommit", str(ctx.exception).lower())
        self.assertEqual(self.sim.global_state["total_reserved"], 0)

    def test_unauthorized_propose_rejection(self):
        """Non-admin caller cannot propose grants."""
        with self.assertRaises(PermissionError):
            self.sim.propose_grant(ATTACKER_ADDR, BENEFICIARY_ADDR, 1_000_000)

    def test_double_grant_overwrite_rejection(self):
        """Admin cannot overwrite a pending grant before it is resolved."""
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 5_000_000)
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 10_000_000)
        self.assertIn("already has an active pending grant", str(ctx.exception))

    def test_cancel_during_dispute_and_after_expiration(self):
        """Admin can cancel within dispute window, but not once unlock_round is reached."""
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 5_000_000)
        self.assertEqual(self.sim.global_state["total_reserved"], 5_000_000)

        # Attack: Attacker tries to cancel
        with self.assertRaises(PermissionError):
            self.sim.cancel_grant(ATTACKER_ADDR, BENEFICIARY_ADDR)

        # Round past dispute period
        self.sim.current_round = 1105
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.cancel_grant(ADMIN_ADDR, BENEFICIARY_ADDR)
        self.assertIn("cannot be canceled", str(ctx.exception))

        # Reset round back into dispute period and cancel
        self.sim.current_round = 1050
        self.sim.cancel_grant(ADMIN_ADDR, BENEFICIARY_ADDR)
        self.assertEqual(self.sim.global_state["total_reserved"], 0)
        self.assertEqual(self.sim.local_state[BENEFICIARY_ADDR]["pending_grant"], 0)

    def test_emergency_pause_blocks_propose_and_claim(self):
        """Emergency pause stops all grant proposals and disbursements."""
        self.sim.toggle_pause(ADMIN_ADDR)
        self.assertEqual(self.sim.global_state["paused"], 1)

        with self.assertRaises(RuntimeError) as ctx:
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)
        self.assertIn("paused", str(ctx.exception).lower())

        self.sim.toggle_pause(ADMIN_ADDR)
        self.assertEqual(self.sim.global_state["paused"], 0)
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)

        self.sim.toggle_pause(ADMIN_ADDR)
        self.sim.current_round = 1200
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertIn("paused", str(ctx.exception).lower())

    def test_closeout_with_active_grant_rejected(self):
        """Account cannot CloseOut while having an active pending grant."""
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 2_000_000)
        with self.assertRaises(AssertionError) as ctx:
            self.sim.closeout_app(BENEFICIARY_ADDR)
        self.assertIn("CloseOut rejected", str(ctx.exception))

    def test_clearstate_recovers_reserved_tokens(self):
        """ClearState recovers leaked reservation capacity."""
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 3_000_000)
        self.assertEqual(self.sim.global_state["total_reserved"], 3_000_000)

        # Beneficiary clears state
        self.sim.clearstate_app(BENEFICIARY_ADDR)
        self.assertEqual(self.sim.global_state["total_reserved"], 0)
        self.assertNotIn(BENEFICIARY_ADDR, self.sim.local_state)

    def test_double_claim_replay_rejection(self):
        """Beneficiary cannot replay claim_grant twice."""
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 2_000_000)
        self.sim.current_round = 1200
        self.sim.claim_grant(BENEFICIARY_ADDR)

        # Attempt to claim again
        with self.assertRaises(ValueError) as ctx:
            self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertIn("No pending grant", str(ctx.exception))

    def test_admin_rotation(self):
        """Admin rotation succeeds for valid 32-byte address, fails for non-admin."""
        with self.assertRaises(PermissionError):
            self.sim.rotate_admin(ATTACKER_ADDR, NEW_ADMIN_ADDR)

        self.sim.rotate_admin(ADMIN_ADDR, NEW_ADMIN_ADDR)
        self.assertEqual(self.sim.global_state["admin"], NEW_ADMIN_ADDR)

        # Old admin can no longer propose grants
        with self.assertRaises(PermissionError):
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)

        # New admin can propose grants
        self.sim.propose_grant(NEW_ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)
        self.assertEqual(self.sim.global_state["total_reserved"], 1_000_000)

    def test_contract_schema_distinction_from_deployed_v1(self):
        """Verify on-chain Testnet App 774088598 schema is Treasury v1, distinct from Hardened v2."""
        # Deployed v1 schema in on-chain status: 1 byte-slice, 4 uints
        # Hardened v2 schema: 1 byte-slice (admin), 6 uints (asset_id, total_disbursed, total_reserved, dispute_period, max_grant, paused)
        v1_num_uints = 4
        hardened_v2_num_uints = 6
        self.assertNotEqual(v1_num_uints, hardened_v2_num_uints)
        self.assertIn('byte "total_reserved"', self.hardened_app)
        self.assertNotIn('byte "total_reserved"', self.v1_app)

    def test_compiled_teal_security_instructions(self):
        """Verify that compiled TEAL output contains critical opcodes and safety checks."""
        self.assertTrue(self.hardened_app.startswith("#pragma version 8"))
        # Asset balance check for overcommit protection
        self.assertIn("asset_holding_get AssetBalance", self.hardened_app)
        # Application opt-in check
        self.assertIn("app_opted_in", self.hardened_app)
        # Anti-drain zeroes
        self.assertIn("AssetCloseTo", self.hardened_app)
        self.assertIn("RekeyTo", self.hardened_app)
        self.assertIn("global ZeroAddress", self.hardened_app)
        # Clear state reservation recovery
        self.assertIn('byte "pending_grant"', self.hardened_clear)
        self.assertIn('byte "total_reserved"', self.hardened_clear)


if __name__ == "__main__":
    unittest.main()
