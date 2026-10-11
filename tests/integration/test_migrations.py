"""Integration tests for versioned database migrations."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from migrations.run_migrations import apply_migrations, inspect_pre_migration_data


class MigrationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = Path(self.temp_file.name)

    def tearDown(self):
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except Exception:
                pass

    def test_migration_from_legacy_schema_preserves_records(self):
        """Simulate legacy database without network/asset_id columns and verify migration."""
        conn = sqlite3.connect(self.db_path)
        # Create legacy table schema
        conn.execute(
            """
            CREATE TABLE grant_proposals (
                id VARCHAR(64) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                category VARCHAR(50) NOT NULL,
                requested_amount_qeq INTEGER NOT NULL,
                beneficiary_address VARCHAR(58) NOT NULL,
                description TEXT NOT NULL,
                status VARCHAR(30) NOT NULL,
                reviewer_notes TEXT,
                onchain_tx_id VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type VARCHAR(50) NOT NULL,
                entity_id VARCHAR(64) NOT NULL,
                action VARCHAR(50) NOT NULL,
                actor VARCHAR(100) NOT NULL,
                details TEXT,
                created_at DATETIME NOT NULL
            );
            """
        )
        # Insert pre-existing proposal and audit entry
        conn.execute(
            """
            INSERT INTO grant_proposals (
                id, title, category, requested_amount_qeq, beneficiary_address,
                description, status, onchain_tx_id, created_at, updated_at
            ) VALUES (
                'qeq-grant-legacy-01', 'Traditional Handloom Support', 'community_grants',
                2500, 'TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM',
                'Legacy grant before schema migration', 'SUBMITTED', NULL,
                datetime('now'), datetime('now')
            );
            """
        )
        conn.execute(
            """
            INSERT INTO audit_logs (entity_type, entity_id, action, actor, details, created_at)
            VALUES ('GRANT_PROPOSAL', 'qeq-grant-legacy-01', 'SUBMITTED', 'artisan_01', '{}', datetime('now'));
            """
        )
        conn.commit()
        conn.close()

        # Run migration runner
        success = apply_migrations(self.db_path)
        self.assertTrue(success)

        # Verify upgraded schema and preserved data
        verify_conn = sqlite3.connect(self.db_path)
        cursor = verify_conn.cursor()

        # Check preserved record
        cursor.execute("SELECT id, network, asset_id, status FROM grant_proposals WHERE id='qeq-grant-legacy-01';")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "qeq-grant-legacy-01")
        self.assertEqual(row[1], "testnet")  # Default backfilled
        self.assertEqual(row[2], 774088414)   # Default backfilled
        self.assertEqual(row[3], "SUBMITTED")

        # Check index existence
        cursor.execute("PRAGMA index_list('grant_proposals');")
        indexes = {r[1] for r in cursor.fetchall()}
        self.assertIn("uq_grant_proposals_onchain_tx_id", indexes)

        # Check settlements table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='grant_settlements';")
        self.assertIsNotNone(cursor.fetchone())

        verify_conn.close()

    def test_migration_aborts_on_conflicting_duplicate_tx_ids(self):
        """Pre-migration conflict audit must abort if duplicate tx IDs already exist in database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE grant_proposals (
                id VARCHAR(64) PRIMARY KEY,
                title VARCHAR(255),
                category VARCHAR(50),
                requested_amount_qeq INTEGER,
                beneficiary_address VARCHAR(58),
                description TEXT,
                status VARCHAR(30),
                onchain_tx_id VARCHAR(64)
            );
            """
        )
        # Insert two records with the SAME onchain_tx_id
        shared_tx = "TX_CORRUPTED_DUPLICATE_99999"
        conn.execute(
            "INSERT INTO grant_proposals VALUES ('g1', 'G1', 'cat', 100, 'addr', 'desc', 'DISBURSED', ?)",
            (shared_tx,),
        )
        conn.execute(
            "INSERT INTO grant_proposals VALUES ('g2', 'G2', 'cat', 100, 'addr', 'desc', 'DISBURSED', ?)",
            (shared_tx,),
        )
        conn.commit()

        is_safe, issues = inspect_pre_migration_data(conn)
        self.assertFalse(is_safe)
        self.assertTrue(any("Duplicate onchain_tx_id found" in issue for issue in issues))

        conn.close()

        # Runner must refuse to alter database
        success = apply_migrations(self.db_path)
        self.assertFalse(success)
