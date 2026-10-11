"""Automated test suite for Algorand TEAL smart contracts.
Evaluates off-chain specification models, live Algod node AVM compilation,
reservation accounting, overcommit protections, and on-chain schema reality.

NOTE ON REALITY GATE & AVM EXECUTION:
The state-machine tests in this file evaluate specification logic off-chain.
They do NOT execute inside the Algorand Virtual Machine (AVM) runtime on-chain.
True on-chain execution testing requires deployment to an Algorand network.
As verified by the on-chain checks herein, Hardened Treasury v2 is NOT yet deployed.
"""
import unittest
from algosdk import encoding
from algosdk.v2client.algod import AlgodClient
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


class HardenedTreasuryOffChainSpecificationModel:
    """Off-chain state machine model specifying PyTeal contract transitions.
    Used for rapid specification testing; does not execute within the Algorand AVM.
    """

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
        self.local_state = {}
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
        pending = self.local_state.get(sender, {}).get("pending_grant", 0)
        if pending != 0:
            raise AssertionError("CloseOut rejected: Active pending grant exists")
        self.app_opted_in.remove(sender)
        del self.local_state[sender]

    def clearstate_app(self, sender: str):
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

        liquid_balance = self.asset_holdings["treasury"]
        if self.global_state["total_reserved"] + amount > liquid_balance:
            raise RuntimeError(f"Overcommit error: requested {amount} exceeds liquid treasury capacity")

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

        self.asset_holdings["treasury"] -= amount
        self.asset_holdings[sender] += amount
        self.global_state["total_disbursed"] += amount
        self.global_state["total_reserved"] -= amount
        self.local_state[sender]["pending_grant"] = 0
        self.local_state[sender]["unlock_round"] = 0


class ContractSpecificationAndAttackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hardened_app, cls.hardened_clear = compile_hardened_teal()
        cls.v1_app, cls.v1_clear = compile_to_teal()

    def setUp(self):
        self.sim = HardenedTreasuryOffChainSpecificationModel(creator=ADMIN_ADDR, asset_id=ASSET_ID)
        self.sim.deposit_treasury_asset(100_000_000_000)
        self.sim.optin_asset_beneficiary(BENEFICIARY_ADDR)
        self.sim.optin_app(BENEFICIARY_ADDR)

    def test_complete_grant_lifecycle_pass(self):
        grant_amount = 5_000_000_000
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, grant_amount)
        self.assertEqual(self.sim.global_state["total_reserved"], grant_amount)
        self.assertEqual(self.sim.local_state[BENEFICIARY_ADDR]["pending_grant"], grant_amount)

        self.sim.current_round = 1050
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertIn("timelock", str(ctx.exception).lower())

        self.sim.current_round = 1101
        self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertEqual(self.sim.asset_holdings[BENEFICIARY_ADDR], grant_amount)
        self.assertEqual(self.sim.global_state["total_disbursed"], grant_amount)
        self.assertEqual(self.sim.global_state["total_reserved"], 0)

    def test_overcommit_rejection(self):
        self.sim.asset_holdings["treasury"] = 10_000_000
        excessive_amount = 12_000_000
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, excessive_amount)
        self.assertIn("overcommit", str(ctx.exception).lower())
        self.assertEqual(self.sim.global_state["total_reserved"], 0)

    def test_unauthorized_propose_rejection(self):
        with self.assertRaises(PermissionError):
            self.sim.propose_grant(ATTACKER_ADDR, BENEFICIARY_ADDR, 1_000_000)

    def test_double_grant_overwrite_rejection(self):
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 5_000_000)
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 10_000_000)
        self.assertIn("already has an active pending grant", str(ctx.exception))

    def test_cancel_during_dispute_and_after_expiration(self):
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 5_000_000)
        with self.assertRaises(PermissionError):
            self.sim.cancel_grant(ATTACKER_ADDR, BENEFICIARY_ADDR)

        self.sim.current_round = 1105
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.cancel_grant(ADMIN_ADDR, BENEFICIARY_ADDR)
        self.assertIn("cannot be canceled", str(ctx.exception))

        self.sim.current_round = 1050
        self.sim.cancel_grant(ADMIN_ADDR, BENEFICIARY_ADDR)
        self.assertEqual(self.sim.global_state["total_reserved"], 0)

    def test_emergency_pause_blocks_propose_and_claim(self):
        self.sim.toggle_pause(ADMIN_ADDR)
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)
        self.assertIn("paused", str(ctx.exception).lower())

        self.sim.toggle_pause(ADMIN_ADDR)
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)

        self.sim.toggle_pause(ADMIN_ADDR)
        self.sim.current_round = 1200
        with self.assertRaises(RuntimeError) as ctx:
            self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertIn("paused", str(ctx.exception).lower())

    def test_closeout_with_active_grant_rejected(self):
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 2_000_000)
        with self.assertRaises(AssertionError) as ctx:
            self.sim.closeout_app(BENEFICIARY_ADDR)
        self.assertIn("CloseOut rejected", str(ctx.exception))

    def test_clearstate_recovers_reserved_tokens(self):
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 3_000_000)
        self.sim.clearstate_app(BENEFICIARY_ADDR)
        self.assertEqual(self.sim.global_state["total_reserved"], 0)
        self.assertNotIn(BENEFICIARY_ADDR, self.sim.local_state)

    def test_double_claim_replay_rejection(self):
        self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 2_000_000)
        self.sim.current_round = 1200
        self.sim.claim_grant(BENEFICIARY_ADDR)
        with self.assertRaises(ValueError) as ctx:
            self.sim.claim_grant(BENEFICIARY_ADDR)
        self.assertIn("No pending grant", str(ctx.exception))

    def test_admin_rotation(self):
        with self.assertRaises(PermissionError):
            self.sim.rotate_admin(ATTACKER_ADDR, NEW_ADMIN_ADDR)
        self.sim.rotate_admin(ADMIN_ADDR, NEW_ADMIN_ADDR)
        self.assertEqual(self.sim.global_state["admin"], NEW_ADMIN_ADDR)
        with self.assertRaises(PermissionError):
            self.sim.propose_grant(ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)
        self.sim.propose_grant(NEW_ADMIN_ADDR, BENEFICIARY_ADDR, 1_000_000)
        self.assertEqual(self.sim.global_state["total_reserved"], 1_000_000)


class LiveAvmCompilationAndRealityGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hardened_app, cls.hardened_clear = compile_hardened_teal()
        cls.tc = AlgodClient("", "https://testnet-api.algonode.cloud")

    def test_real_algod_avm_node_compiles_teal8_bytecode(self):
        """Send compiled TEAL 8 source directly to a live Algorand node /v2/teal/compile endpoint.
        Validates real AVM opcode validity, version conformance, and bytecode generation.
        """
        app_comp = self.tc.compile(self.hardened_app)
        clear_comp = self.tc.compile(self.hardened_clear)

        self.assertIn("hash", app_comp, "Algod node must return bytecode hash for approval program")
        self.assertIn("result", app_comp, "Algod node must return base64 bytecode result")
        self.assertIn("hash", clear_comp, "Algod node must return bytecode hash for clear state program")

        # Approval bytecode is non-empty and has valid length
        self.assertGreater(len(app_comp["result"]), 200)
        self.assertGreater(len(clear_comp["result"]), 20)

    def test_onchain_reality_gap_undeployed_treasury_v2(self):
        """Query live Testnet Application 774088598 and prove it is Treasury v1, NOT Hardened Treasury v2.
        Confirms that Treasury v2 remains undeployed on-chain, keeping release gates BLOCKED.
        """
        app_info = self.tc.application_info(774088598)
        global_schema = app_info.get("params", {}).get("global-state-schema", {})
        onchain_uints = global_schema.get("num-uint", 0)

        # Treasury v1 prototype has 4 uints
        # Hardened Treasury v2 has 6 uints (added total_reserved and max_grant)
        self.assertEqual(onchain_uints, 4, "Deployed Testnet App 774088598 is Treasury v1 (4 uints)")
        self.assertNotEqual(onchain_uints, 6, "Hardened Treasury v2 (6 uints) is NOT yet deployed on Testnet")


if __name__ == "__main__":
    unittest.main()
