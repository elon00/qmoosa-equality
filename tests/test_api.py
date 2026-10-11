import os
import tempfile
import unittest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base, get_db, GrantStatus
from backend.main import app
from fastapi.testclient import TestClient

TEMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEMP_DB.close()
TEST_DB_PATH = Path(TEMP_DB.name)

test_engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)
        if TEST_DB_PATH.exists():
            try:
                TEST_DB_PATH.unlink()
            except:
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

        # Valid payload
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

        # Check in list
        res_list = self.client.get("/api/grants/proposals")
        self.assertEqual(res_list.status_code, 200)
        self.assertTrue(any(p["id"] == grant_id for p in res_list.json()["proposals"]))

        # Review proposal -> APPROVE
        review_payload = {
            "status": GrantStatus.APPROVED,
            "reviewer_notes": "Meets all criteria for community grant program.",
            "reviewer_identity": "council_reviewer_1"
        }
        res_review = self.client.patch(f"/api/grants/proposals/{grant_id}/review", json=review_payload)
        self.assertEqual(res_review.status_code, 200)
        self.assertEqual(res_review.json()["proposal"]["status"], GrantStatus.APPROVED)

        # Disburse proposal
        disburse_payload = {
            "onchain_tx_id": "X" * 52,
            "actor_identity": "treasury_admin"
        }
        res_disburse = self.client.patch(f"/api/grants/proposals/{grant_id}/disburse", json=disburse_payload)
        self.assertEqual(res_disburse.status_code, 200)
        self.assertEqual(res_disburse.json()["proposal"]["status"], GrantStatus.DISBURSED)

        # Verify Audit Logs
        res_audit = self.client.get(f"/api/grants/audit-logs/{grant_id}")
        self.assertEqual(res_audit.status_code, 200)
        actions = [log["action"] for log in res_audit.json()["audit_logs"]]
        self.assertIn("SUBMITTED", actions)
        self.assertIn("STATUS_CHANGED", actions)
        self.assertIn("DISBURSED", actions)

if __name__ == "__main__":
    unittest.main()
