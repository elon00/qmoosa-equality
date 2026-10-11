"""Explicit, versioned database migration runner for Qmoosa Equality.

Ensures:
1. Pre-migration backup is generated and verified before any DDL changes.
2. Existing data is inspected for conflicts (duplicate tx IDs, invalid statuses).
3. If conflicts exist, aborts with a remediation report rather than altering data silently.
4. Executes incremental DDL schema migrations.
5. Post-migration inspection verifies indexes and constraints exist on the live engine.
"""
import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend.db import DEFAULT_DB_PATH, engine, GrantStatus
from scripts.db_backup_restore import backup_db


def inspect_pre_migration_data(conn: sqlite3.Connection) -> Tuple[bool, List[str]]:
    """Inspect existing data for data-loss risks, duplicate tx IDs, or corrupted statuses."""
    issues: List[str] = []

    # Check if grant_proposals table exists
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='grant_proposals';")
    if not cursor.fetchone():
        return True, []  # Fresh database, no conflicts possible

    # Check for duplicate onchain_tx_id values (ignoring NULL)
    cursor.execute(
        """
        SELECT onchain_tx_id, COUNT(*) 
        FROM grant_proposals 
        WHERE onchain_tx_id IS NOT NULL 
        GROUP BY onchain_tx_id 
        HAVING COUNT(*) > 1;
        """
    )
    duplicates = cursor.fetchall()
    if duplicates:
        for tx_id, count in duplicates:
            issues.append(f"Duplicate onchain_tx_id found: '{tx_id}' appears {count} times.")

    # Check for invalid statuses
    cursor.execute("SELECT id, status FROM grant_proposals;")
    for row_id, stat in cursor.fetchall():
        if stat not in GrantStatus.ALL:
            issues.append(f"Invalid status '{stat}' on proposal '{row_id}'.")

    is_safe = len(issues) == 0
    return is_safe, issues


def apply_migrations(db_path: Path) -> bool:
    """Execute versioned migration steps on the SQLite database."""
    print("=" * 65)
    print("STARTING QMOOSA EQUALITY DATABASE MIGRATION")
    print(f"Target Database: {db_path}")
    print("=" * 65)

    if not db_path.exists():
        print(f"Target database file not found at {db_path}. Initializing empty schema.")
        from backend.db import init_db
        init_db()
        print("[SUCCESS] Fresh database initialized with latest schema.")
        return True

    conn = sqlite3.connect(db_path)

    # Step 1: Pre-migration data audit
    print("\n--- [PHASE 1] Pre-Migration Data & Conflict Audit ---")
    is_safe, issues = inspect_pre_migration_data(conn)
    if not is_safe:
        print("[ABORT] Migration cannot proceed due to data integrity conflicts:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        conn.close()
        return False
    print("[PASS] Pre-migration data audit passed with 0 conflicts.")

    # Step 2: Automated point-in-time backup
    print("\n--- [PHASE 2] Automated Pre-Migration Backup ---")
    try:
        backup_file = backup_db()
        print(f"[PASS] Pre-migration backup verified at: {backup_file}")
    except Exception as e:
        print(f"[ABORT] Pre-migration backup failed: {e}", file=sys.stderr)
        conn.close()
        return False

    # Step 3: DDL Schema Migrations
    print("\n--- [PHASE 3] Applying DDL Migrations ---")
    cursor = conn.cursor()

    # Migration 001: Ensure columns network & asset_id exist on grant_proposals
    cursor.execute("PRAGMA table_info('grant_proposals');")
    existing_cols = {row[1] for row in cursor.fetchall()}

    if "network" not in existing_cols:
        cursor.execute("ALTER TABLE grant_proposals ADD COLUMN network VARCHAR(20) DEFAULT 'testnet' NOT NULL;")
        print("  - [MIGRATION 001a] Added 'network' column to grant_proposals.")

    if "asset_id" not in existing_cols:
        cursor.execute("ALTER TABLE grant_proposals ADD COLUMN asset_id INTEGER DEFAULT 774088414 NOT NULL;")
        print("  - [MIGRATION 001b] Added 'asset_id' column to grant_proposals.")

    # Migration 002: Unique index on grant_proposals(onchain_tx_id)
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_grant_proposals_onchain_tx_id 
        ON grant_proposals(onchain_tx_id) 
        WHERE onchain_tx_id IS NOT NULL;
        """
    )
    print("  - [MIGRATION 002] Applied unique partial index uq_grant_proposals_onchain_tx_id.")

    # Migration 003: Table grant_settlements
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS grant_settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grant_id VARCHAR(64) NOT NULL UNIQUE,
            network_identity VARCHAR(100) NOT NULL,
            root_transaction_id VARCHAR(64) NOT NULL,
            inner_transaction_path VARCHAR(30) DEFAULT 'root' NOT NULL,
            asset_id INTEGER NOT NULL,
            sender VARCHAR(58) NOT NULL,
            receiver VARCHAR(58) NOT NULL,
            amount_base_units INTEGER NOT NULL,
            confirmed_round INTEGER NOT NULL,
            verified_at DATETIME NOT NULL,
            FOREIGN KEY (grant_id) REFERENCES grant_proposals (id)
        );
        """
    )
    print("  - [MIGRATION 003a] Created grant_settlements table.")

    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_payment 
        ON grant_settlements (network_identity, root_transaction_id, inner_transaction_path);
        """
    )
    print("  - [MIGRATION 003b] Created uq_settlement_payment unique index.")

    conn.commit()

    # Step 4: Post-migration Verification
    print("\n--- [PHASE 4] Post-Migration Index & Schema Verification ---")
    cursor.execute("PRAGMA index_list('grant_proposals');")
    gp_indexes = {row[1] for row in cursor.fetchall()}
    assert "uq_grant_proposals_onchain_tx_id" in gp_indexes, "uq_grant_proposals_onchain_tx_id index missing"
    print("  [VERIFIED] uq_grant_proposals_onchain_tx_id index exists.")

    cursor.execute("PRAGMA index_list('grant_settlements');")
    gs_indexes = {row[1] for row in cursor.fetchall()}
    assert "uq_settlement_payment" in gs_indexes, "uq_settlement_payment index missing"
    print("  [VERIFIED] uq_settlement_payment index exists.")

    conn.close()
    print("\n[SUCCESS] All database migrations applied and verified successfully.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Qmoosa Equality database migrations")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to database")
    args = parser.parse_args()

    success = apply_migrations(args.db_path)
    if not success:
        sys.exit(1)
