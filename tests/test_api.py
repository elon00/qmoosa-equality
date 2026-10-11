"""Comprehensive API, authentication, middleware, and settlement integration tests for Qmoosa Equality."""
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

from backend.auth import get_authenticated_admin
from backend.db import Base, get_db, GrantProposal, GrantSettlement, GrantStatus
import backend.auth as auth_module
import backend.settlement as settlement_module
from backend.settlement import (
    COMPROMISED_ADMIN_ADDR,
    build_canonical_grant_note,
    verify_settlement_evidence,
    NormalizedPayment,
)
from backend.main import app
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
TESTNET_TREASURY_ADDR = "A2SUZAVEYRGQNXG7PMJP3W3JZHA7F24PRUTGHOQ4Q6AEWC574VR7S5OZEE"


class ApiAndSettlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)
        os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY
        os.environ["ADMIN_OPERATOR_IDENTITY"] = "verified_council_lead"
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except Exception:
                pass

    def setUp(self):
        os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY
        os.environ["ADMIN_OPERATOR_IDENTITY"] = "verified_council_lead"
        db = TestSessionLocal()
        db.query(GrantSettlement).delete()
        db.query(GrantProposal).delete()
        db.commit()
        db.close()

    # --- Section 3: Administrative Authentication ---
    def test_unconfigured_or_whitespace_admin_key_fails_closed(self):
        """When ADMIN_API_KEY is missing, empty, or whitespace, administrative actions fail with HTTP 503."""
        for blank_val in [None, "", "   ", "\t\n"]:
            if blank_val is None:
                os.environ.pop("ADMIN_API_KEY", None)
            else:
                os.environ["ADMIN_API_KEY"] = blank_val

            res = self.client.patch("/api/grants/proposals/test-id/review", json={"status": "APPROVED", "reviewer_notes": "ok"})
            self.assertEqual(res.status_code, 503)
            self.assertIn("Administrative operations disabled", res.json()["detail"])

    def test_admin_auth_wrong_credentials_returns_401(self):
        """Missing or wrong administrative credentials return HTTP 401."""
        os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY

        # No auth header
        res1 = self.client.patch("/api/grants/proposals/test-id/review", json={"status": "APPROVED", "reviewer_notes": "ok"})
        self.assertEqual(res1.status_code, 401)

        # Wrong token
        res2 = self.client.patch(
            "/api/grants/proposals/test-id/review",
            json={"status": "APPROVED", "reviewer_notes": "ok"},
            headers={"Authorization": "Bearer wrong-token-123"},
        )
        self.assertEqual(res2.status_code, 401)

    def test_reviewer_identity_strictly_server_derived(self):
        """Caller-supplied identity headers (X-Admin-Identity) are ignored; server identity is used."""
        os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY
        os.environ["ADMIN_OPERATOR_IDENTITY"] = "council_lead_operator_99"

        # Submit grant
        sub_res = self.client.post(
            "/api/grants/proposals",
            json={
                "title": "Vocational Weaving Center",
                "category": "community_grants",
                "requested_amount_qeq": 5000,
                "beneficiary_address": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                "description": "Livelihood support for traditional handloom artisans in rural area.",
            },
        )
        self.assertEqual(sub_res.status_code, 201)
        grant_id = sub_res.json()["proposal"]["id"]

        # Review with spoofed caller header
        review_res = self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json={"status": GrantStatus.UNDER_REVIEW, "reviewer_notes": "Valid application"},
            headers={
                "Authorization": f"Bearer {TEST_ADMIN_KEY}",
                "X-Admin-Identity": "malicious_spoofed_identity",
            },
        )
        self.assertEqual(review_res.status_code, 200)

        # Verify audit log actor
        audit_res = self.client.get(f"/api/grants/audit-logs/{grant_id}")
        self.assertEqual(audit_res.status_code, 200)
        logs = audit_res.json()["audit_logs"]
        review_log = [l for l in logs if l["action"] == "STATUS_CHANGED"][0]
        self.assertEqual(review_log["actor"], "council_lead_operator_99")
        self.assertNotEqual(review_log["actor"], "malicious_spoofed_identity")

    # --- Section 9: Streaming Request Limits ---
    def test_request_size_limits_and_malformed_framing(self):
        """Enforces 1 MB streaming limit and rejects malformed framing metadata."""
        # 1. Malformed Content-Length -> HTTP 400
        res_malformed = self.client.post("/api/grants/proposals", headers={"Content-Length": "not-a-number"}, content=b"{}")
        self.assertEqual(res_malformed.status_code, 400)

        # 2. Negative Content-Length -> HTTP 400
        res_neg = self.client.post("/api/grants/proposals", headers={"Content-Length": "-10"}, content=b"{}")
        self.assertEqual(res_neg.status_code, 400)

        # 3. Oversized Content-Length upfront -> HTTP 413
        res_large_cl = self.client.post(
            "/api/grants/proposals",
            headers={"Content-Length": str(2 * 1024 * 1024)},
            content=b"{}",
        )
        self.assertEqual(res_large_cl.status_code, 413)

        # 4. Chunked oversized body -> HTTP 413
        def chunked_gen():
            for _ in range(25):
                yield b"X" * (50 * 1024)  # Total 1.25 MB > 1 MB

        res_chunked = self.client.post("/api/grants/proposals", content=chunked_gen())
        self.assertEqual(res_chunked.status_code, 413)

    # --- Section 7: State Machine Transitions ---
    def test_grant_status_transition_table_enforcement(self):
        """Enforces finite state transitions and prevents terminal states from rolling back."""
        # Submit
        sub_res = self.client.post(
            "/api/grants/proposals",
            json={
                "title": "Solar Water Micro-Utility",
                "category": "public_goods",
                "requested_amount_qeq": 10000,
                "beneficiary_address": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                "description": "Clean drinking water access for community gathering point.",
            },
        )
        grant_id = sub_res.json()["proposal"]["id"]

        # SUBMITTED cannot transition directly to DISBURSED
        res_invalid = self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json={"status": GrantStatus.DISBURSED, "reviewer_notes": "illegal skip"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(res_invalid.status_code, 400)
        self.assertIn("Illegal grant state transition", res_invalid.json()["detail"])

        # SUBMITTED -> UNDER_REVIEW -> APPROVED (valid)
        self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json={"status": GrantStatus.UNDER_REVIEW, "reviewer_notes": "under evaluation"},
            headers=AUTH_HEADERS,
        )
        appr_res = self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json={"status": GrantStatus.APPROVED, "reviewer_notes": "approved by council"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(appr_res.status_code, 200)

        # Mock disbursement
        mock_p = NormalizedPayment(
            network_identity="testnet-gh",
            root_transaction_id="TX_DISB_MOCK_" + "7" * 39,
            inner_transaction_path="root",
            confirmed_round=68175000,
            application_id=None,
            sender=TESTNET_TREASURY_ADDR,
            asset_id=774088414,
            receiver="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            amount_base_units=10_000_000_000,
            canonical_grant_binding=build_canonical_grant_note("testnet", 774088414, grant_id),
            rekey_to=None,
            close_to=None,
            clawback=None,
        )
        with patch("backend.grants.verify_settlement_evidence", return_value=mock_p):
            disb_res = self.client.patch(
                f"/api/grants/proposals/{grant_id}/disburse",
                json={"onchain_tx_id": "TX_DISB_MOCK_" + "7" * 39},
                headers=AUTH_HEADERS,
            )
            self.assertEqual(disb_res.status_code, 200)
            self.assertEqual(disb_res.json()["proposal"]["status"], GrantStatus.DISBURSED)

        # Terminal state protection: DISBURSED cannot return to APPROVED
        terminal_res = self.client.patch(
            f"/api/grants/proposals/{grant_id}/review",
            json={"status": GrantStatus.APPROVED, "reviewer_notes": "attempt to un-disburse"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(terminal_res.status_code, 400)
        self.assertIn("Illegal grant state transition", terminal_res.json()["detail"])

    # --- Section 5 & 6: Mandatory Note Binding & Settlement Verification ---
    def test_canonical_grant_note_binding_verification(self):
        """Verifies exact canonical UTF-8 note protocol: qeq:grant:v1:<network>:<asset_id>:<grant_id>."""
        grant_id = "qeq-grant-test-123"
        correct_note = build_canonical_grant_note("testnet", 774088414, grant_id)
        self.assertEqual(correct_note, "qeq:grant:v1:testnet:774088414:qeq-grant-test-123")

        # 1. Missing note -> rejected
        mock_tx_no_note = {
            "confirmed-round": 68175000,
            "sender": TESTNET_TREASURY_ADDR,
            "asset-transfer-transaction": {
                "asset-id": 774088414,
                "receiver": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                "amount": 1000_000_000,
            },
        }
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"transaction": mock_tx_no_note}

            with self.assertRaises(HTTPException) as ctx:
                verify_settlement_evidence(
                    tx_id="TX_NO_NOTE_" + "1" * 40,
                    grant_id=grant_id,
                    beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                    expected_amount_qeq=1000,
                    configured_network="testnet",
                    configured_asset_id=774088414,
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Grant binding mismatch", ctx.exception.detail)

        # 2. Substring match attempt -> rejected
        substring_note = base64.b64encode(b"prefix:qeq:grant:v1:testnet:774088414:qeq-grant-test-123:suffix").decode()
        mock_tx_sub = dict(mock_tx_no_note)
        mock_tx_sub["note"] = substring_note
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"transaction": mock_tx_sub}

            with self.assertRaises(HTTPException) as ctx:
                verify_settlement_evidence(
                    tx_id="TX_SUBSTRING_" + "2" * 38,
                    grant_id=grant_id,
                    beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                    expected_amount_qeq=1000,
                    configured_network="testnet",
                    configured_asset_id=774088414,
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Grant binding mismatch", ctx.exception.detail)

        # 3. Exact canonical note -> PASS
        exact_note_b64 = base64.b64encode(correct_note.encode("utf-8")).decode()
        mock_tx_ok = dict(mock_tx_no_note)
        mock_tx_ok["note"] = exact_note_b64
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"transaction": mock_tx_ok}

            payment = verify_settlement_evidence(
                tx_id="TX_OK_" + "3" * 44,
                grant_id=grant_id,
                beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                expected_amount_qeq=1000,
                configured_network="testnet",
                configured_asset_id=774088414,
            )
            self.assertEqual(payment.canonical_grant_binding, correct_note)
            self.assertEqual(payment.amount_base_units, 1000_000_000)

    # --- Section 4: Treasury Sender Fail-Closed & Compromised Check ---
    def test_treasury_sender_security_and_fail_closed(self):
        """Disallow empty allowlist, ban compromised address, and reject unauthorized senders."""
        grant_id = "qeq-grant-sender-check"
        correct_note = base64.b64encode(build_canonical_grant_note("testnet", 774088414, grant_id).encode()).decode()

        # 1. Compromised address as sender -> rejected
        mock_tx_compromised = {
            "confirmed-round": 68175000,
            "sender": COMPROMISED_ADMIN_ADDR,
            "note": correct_note,
            "asset-transfer-transaction": {
                "asset-id": 774088414,
                "receiver": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                "amount": 1000_000_000,
            },
        }
        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"transaction": mock_tx_compromised}

            with self.assertRaises(HTTPException) as ctx:
                verify_settlement_evidence(
                    tx_id="TX_COMPROMISED_SENDER_" + "4" * 30,
                    grant_id=grant_id,
                    beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
                    expected_amount_qeq=1000,
                    configured_network="testnet",
                    configured_asset_id=774088414,
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Sender mismatch", ctx.exception.detail)

    # --- Section 7: Durable Replay & Uniqueness ---
    def test_durable_replay_protection_on_settlement_record(self):
        """A single on-chain transaction cannot be reused across proposals."""
        db = TestSessionLocal()
        p1 = GrantProposal(
            id="grant-p1",
            title="P1",
            category="community_grants",
            requested_amount_qeq=1000,
            beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            description="First grant",
            status=GrantStatus.APPROVED,
            network="testnet",
            asset_id=774088414,
        )
        p2 = GrantProposal(
            id="grant-p2",
            title="P2",
            category="community_grants",
            requested_amount_qeq=1000,
            beneficiary_address="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            description="Second grant",
            status=GrantStatus.APPROVED,
            network="testnet",
            asset_id=774088414,
        )
        db.add_all([p1, p2])
        db.commit()
        db.close()

        shared_tx_id = "TX_SHARED_REPLAY_" + "8" * 35

        mock_p1 = NormalizedPayment(
            network_identity="testnet-gh",
            root_transaction_id=shared_tx_id,
            inner_transaction_path="root",
            confirmed_round=68175000,
            application_id=None,
            sender=TESTNET_TREASURY_ADDR,
            asset_id=774088414,
            receiver="TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
            amount_base_units=1000_000_000,
            canonical_grant_binding=build_canonical_grant_note("testnet", 774088414, "grant-p1"),
            rekey_to=None,
            close_to=None,
            clawback=None,
        )

        with patch("backend.grants.verify_settlement_evidence", return_value=mock_p1):
            res1 = self.client.patch(
                f"/api/grants/proposals/grant-p1/disburse",
                json={"onchain_tx_id": shared_tx_id},
                headers=AUTH_HEADERS,
            )
            self.assertEqual(res1.status_code, 200)

        # Attempt to disburse grant-p2 using the SAME transaction ID -> HTTP 409 Conflict
        res2 = self.client.patch(
            f"/api/grants/proposals/grant-p2/disburse",
            json={"onchain_tx_id": shared_tx_id},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(res2.status_code, 409)
        self.assertIn("Transaction replay rejected", res2.json()["detail"])
