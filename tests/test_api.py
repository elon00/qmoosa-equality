import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEMP_DB.close()
TEST_DB_PATH = Path(TEMP_DB.name)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from backend.db import Base, get_db, GrantProposal, GrantStatus
import backend.main as backend_module
from backend.main import (
    app,
    verify_onchain_disbursement_tx,
    AUTHORIZED_TREASURY_ADDRESSES,
    TESTNET_TREASURY_APP_ADDRESS,
)
from fastapi.testclient import TestClient

test_engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

TEST_ADMIN_KEY = "test-secret-vault-key-abc123xyz"
AUTH_HEADERS = {
    "Authorization": f"Bearer {TEST_ADMIN_KEY}",
    "X-Admin-Identity": "spoofed_attacker_should_be_ignored",
}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)
        backend_module.ADMIN_API_KEY = TEST_ADMIN_KEY
        backend_module.ADMIN_OPERATOR_IDENTITY = "verified_council_lead"

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except Exception:
                pass

    def setUp(self):
        self.client = TestClient(app)

    def test_liveness_and_readiness(self):
        r_live = self.client.get("/api/health/live")
        self.assertEqual(r_live.status_code, 200)
        self.assertEqual(r_live.json()["status"], "ALIVE")

        r_ready = self.client.get("/api/health/ready")
        self.assertEqual(r_ready.status_code, 200)
        data = r_ready.json()
        self.assertEqual(data["status"], "READY")
        self.assertTrue(data["database_ok"])

    def test_unconfigured_admin_key_fails_closed(self):
        """When ADMIN_API_KEY is missing/unconfigured, administrative operations fail closed with HTTP 503."""
        saved_key = backend_module.ADMIN_API_KEY
        try:
            backend_module.ADMIN_API_KEY = None
            res = self.client.patch("/api/grants/proposals/test-id/review", json={"status": "APPROVED", "reviewer_notes": "test"})
            self.assertEqual(res.status_code, 503)
            self.assertIn("ADMIN_API_KEY is not configured", res.json()["detail"])
        finally:
            backend_module.ADMIN_API_KEY = saved_key

    def test_grant_submission_validation(self):
        # Invalid address test
        bad_payload = {
            "title": "Community Clean Energy",
            "category": "social_enterprises",
            "requested_amount_qeq": 1000,
            "beneficiary_address": "INVALID_ADDRESS_123",
            "description": "Funding solar panels for rural community center."
        }
        res = self.client.post("/api/grants/proposals", json=bad_payload)
        self.assertEqual(res.status_code, 422)

        # Invalid category test
        bad_cat_payload = {
            "title": "Community Clean Energy",
            "category": "unsupported_category",
            "requested_amount_qeq": 1000,
            "beneficiary_address": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            "description": "Funding solar panels for rural community center."
        }
        res_cat = self.client.post("/api/grants/proposals", json=bad_cat_payload)
        self.assertEqual(res_cat.status_code, 422)

        # Valid payload submission
        valid_payload = {
            "title": "Moolnivasi Artisanal Handloom Grant",
            "category": "community_grants",
            "requested_amount_qeq": 5000,
            "beneficiary_address": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            "description": "Grant for purchasing traditional handloom weaving materials."
        }
        res_valid = self.client.post("/api/grants/proposals", json=valid_payload)
        self.assertEqual(res_valid.status_code, 201)
        created = res_valid.json()["proposal"]
        grant_id = created["id"]
        self.assertEqual(created["status"], GrantStatus.SUBMITTED)

        # Review Attack 1: Unauthenticated review attempt -> 401
        review_payload = {
            "status": GrantStatus.APPROVED,
            "reviewer_notes": "Attempting unauthenticated approval.",
        }
        res_unauth = self.client.patch(f"/api/grants/proposals/{grant_id}/review", json=review_payload)
        self.assertEqual(res_unauth.status_code, 401)

        # Review Attack 2: Invalid bearer token -> 401
        res_bad_auth = self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json=review_payload,
            headers={"Authorization": "Bearer wrong-key"},
        )
        self.assertEqual(res_bad_auth.status_code, 401)

        # Valid Authenticated Review
        valid_review = {
            "status": GrantStatus.APPROVED,
            "reviewer_notes": "Meets all criteria for community grant program.",
        }
        res_review = self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json=valid_review,
            headers=AUTH_HEADERS,
        )
        self.assertEqual(res_review.status_code, 200)
        self.assertEqual(res_review.json()["proposal"]["status"], GrantStatus.APPROVED)

        # Verify Reviewer Identity: Must NOT be the caller's spoofed header
        res_audit = self.client.get(f"/api/grants/audit-logs/{grant_id}")
        logs = res_audit.json()["audit_logs"]
        review_log = next(l for l in logs if l["action"] == "STATUS_CHANGED")
        self.assertEqual(review_log["actor"], "verified_council_lead")
        self.assertNotEqual(review_log["actor"], "spoofed_attacker_should_be_ignored")

        # Disburse Attack 1: Unauthenticated disburse attempt -> 401
        tx_id_1 = "TXID1" + "A" * 47
        disburse_payload = {"onchain_tx_id": tx_id_1}
        res_disburse_unauth = self.client.patch(
            f"/api/grants/proposals/{grant_id}/disburse",
            json=disburse_payload,
        )
        self.assertEqual(res_disburse_unauth.status_code, 401)

        # Disburse Attack 2: Authenticated but nonexistent on-chain transaction ID -> 400
        res_fake_tx = self.client.patch(
            f"/api/grants/proposals/{grant_id}/disburse",
            json=disburse_payload,
            headers=AUTH_HEADERS,
        )
        self.assertEqual(res_fake_tx.status_code, 400)
        self.assertIn("could not be located", res_fake_tx.json()["detail"].lower())

        # Disburse Success: Verified on-chain transaction
        mock_verification = {
            "tx_id": tx_id_1,
            "confirmed_round": 68175000,
            "sender": TESTNET_TREASURY_APP_ADDRESS,
            "network": "testnet",
            "verified": True,
        }
        with patch("backend.main.verify_onchain_disbursement_tx", return_value=mock_verification):
            res_disburse = self.client.patch(
                f"/api/grants/proposals/{grant_id}/disburse",
                json=disburse_payload,
                headers=AUTH_HEADERS,
            )
            self.assertEqual(res_disburse.status_code, 200)
            self.assertEqual(res_disburse.json()["proposal"]["status"], GrantStatus.DISBURSED)

    def test_payment_replay_prevention_across_proposals(self):
        """A single on-chain transaction cannot be reused to disburse multiple grant proposals."""
        db = TestSessionLocal()
        # Create Proposal A (Disbursed)
        p_a = GrantProposal(
            id="qeq-grant-replay-a",
            title="Proposal A",
            category="community_grants",
            requested_amount_qeq=1000,
            beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            description="Testing replay prevention mechanism",
            status=GrantStatus.DISBURSED,
            onchain_tx_id="SHARED_TX_ID_" + "9" * 39,
        )
        # Create Proposal B (Approved)
        p_b = GrantProposal(
            id="qeq-grant-replay-b",
            title="Proposal B",
            category="community_grants",
            requested_amount_qeq=1000,
            beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            description="Testing replay prevention mechanism",
            status=GrantStatus.APPROVED,
        )
        db.add_all([p_a, p_b])
        db.commit()

        # Replay attempt: Try disbursing Proposal B with the tx_id already used for Proposal A
        with self.assertRaises(HTTPException) as ctx:
            verify_onchain_disbursement_tx(
                tx_id="SHARED_TX_ID_" + "9" * 39,
                proposal_id="qeq-grant-replay-b",
                beneficiary_address=p_b.beneficiary_address,
                expected_amount_qeq=p_b.requested_amount_qeq,
                db=db,
                network="testnet",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Transaction replay rejected", ctx.exception.detail)
        db.close()

    def test_unauthorized_disbursement_sender_rejection(self):
        """Disbursement transaction from an unauthorized sender is rejected."""
        db = TestSessionLocal()
        mock_tx = {
            "confirmed-round": 68175000,
            "sender": "UNAUTHORIZED_SENDER_ADDR_12345",
            "asset-transfer-transaction": {
                "asset-id": 774088414,
                "receiver": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                "amount": 1000_000_000,
            }
        }
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"transaction": mock_tx}

            with self.assertRaises(HTTPException) as ctx:
                verify_onchain_disbursement_tx(
                    tx_id="TX_UNAUTH_" + "1" * 42,
                    proposal_id="test-prop",
                    beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                    expected_amount_qeq=1000,
                    db=db,
                    network="testnet",
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Unauthorized disbursement sender", ctx.exception.detail)
        db.close()

    def test_grant_binding_note_mismatch_rejection(self):
        """Transaction note specifying a different proposal ID is rejected."""
        db = TestSessionLocal()
        mismatched_note = base64.b64encode(b"qeq:grant:qeq-grant-different-id").decode("utf-8")
        mock_tx = {
            "confirmed-round": 68175000,
            "sender": TESTNET_TREASURY_APP_ADDRESS,
            "note": mismatched_note,
            "asset-transfer-transaction": {
                "asset-id": 774088414,
                "receiver": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                "amount": 1000_000_000,
            }
        }
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"transaction": mock_tx}

            with self.assertRaises(HTTPException) as ctx:
                verify_onchain_disbursement_tx(
                    tx_id="TX_NOTE_MISMATCH_" + "2" * 36,
                    proposal_id="qeq-grant-my-id",
                    beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                    expected_amount_qeq=1000,
                    db=db,
                    network="testnet",
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Grant binding mismatch", ctx.exception.detail)
        db.close()


if __name__ == "__main__":
    unittest.main()
