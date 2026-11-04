"""Database backup and restoration utility for Qmoosa Equality."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend.db import DEFAULT_DB_PATH, engine, SessionLocal, GrantProposal, AuditLog, init_db

BACKUP_DIR = root / "data" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def compute_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def backup_db() -> Path:
    db_url = str(engine.url)
    if not db_url.startswith("sqlite"):
        raise ValueError("Online snapshot backup is only supported for SQLite databases.")

    db_path = Path(engine.url.database) if engine.url.database else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"Database file not found at {db_path}. Initializing empty DB first.")
        init_db()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    backup_file = BACKUP_DIR / f"qmoosa_db_{timestamp}.sqlite"

    # Use SQLite online backup API to ensure journal/WAL consistency
    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(backup_file)
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    checksum = compute_file_sha256(backup_file)
    meta_file = BACKUP_DIR / f"qmoosa_db_{timestamp}.meta.json"

    meta_conn = sqlite3.connect(backup_file)
    m_cursor = meta_conn.cursor()
    try:
        m_cursor.execute("SELECT count(*) FROM grant_proposals;")
        proposals_count = m_cursor.fetchone()[0]
    except Exception:
        proposals_count = 0
    try:
        m_cursor.execute("SELECT count(*) FROM audit_logs;")
        audit_count = m_cursor.fetchone()[0]
    except Exception:
        audit_count = 0
    meta_conn.close()

    metadata = {
        "timestamp": timestamp,
        "source_path": str(db_path),
        "backup_path": str(backup_file),
        "sha256": checksum,
        "size_bytes": backup_file.stat().st_size,
        "counts": {
            "grant_proposals": proposals_count,
            "audit_logs": audit_count
        }
    }
    meta_file.write_text(json.dumps(metadata, indent=2))
    print(f"Backup created successfully: {backup_file}")
    print(f"Checksum: {checksum}")
    print(f"Metadata: {meta_file}")
    return backup_file

def restore_db(backup_file: Path) -> bool:
    if not backup_file.exists():
        print(f"Backup file not found: {backup_file}", file=sys.stderr)
        return False

    meta_file = backup_file.with_suffix(".meta.json")
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        expected_checksum = meta.get("sha256")
        actual_checksum = compute_file_sha256(backup_file)
        if expected_checksum and expected_checksum != actual_checksum:
            print(f"Checksum mismatch: expected {expected_checksum}, got {actual_checksum}", file=sys.stderr)
            return False

    db_path = Path(engine.url.database) if engine.url.database else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_target = db_path.with_suffix(".tmp_restore")
    shutil.copy2(backup_file, temp_target)
    temp_target.replace(db_path)
    print(f"Restored database to {db_path} from {backup_file}")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backup and restore Qmoosa Equality database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a backup snapshot")

    restore_parser = subparsers.add_parser("restore", help="Restore database from a backup file")
    restore_parser.add_argument("backup_file", type=Path, help="Path to the backup sqlite file")

    args = parser.parse_args()
    if args.command == "backup":
        backup_db()
    elif args.command == "restore":
        success = restore_db(args.backup_file)
        if not success:
            sys.exit(1)
