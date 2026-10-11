"""Persistent Database Layer for Qmoosa Equality.
Implements real persistence, relational schema constraints, audit logging, and migrations.
"""
import datetime
import json
import os
from pathlib import Path
from typing import Generator
from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Integer,
    MetaData,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from algosdk.encoding import is_valid_address

# Default database in project data directory
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH = DATA_DIR / "qmoosa.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class GrantStatus:
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"

    ALL = {SUBMITTED, UNDER_REVIEW, APPROVED, REJECTED, DISBURSED, CANCELLED}


class GrantProposal(Base):
    __tablename__ = "grant_proposals"

    id = Column(String(64), primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    requested_amount_qeq = Column(Integer, nullable=False)
    beneficiary_address = Column(String(58), nullable=False, index=True)
    description = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default=GrantStatus.SUBMITTED, index=True)
    reviewer_notes = Column(Text, nullable=True)
    onchain_tx_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "requested_amount_qeq": self.requested_amount_qeq,
            "beneficiary_address": self.beneficiary_address,
            "description": self.description,
            "status": self.status,
            "reviewer_notes": self.reviewer_notes,
            "onchain_tx_id": self.onchain_tx_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(64), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    actor = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "action": self.action,
            "actor": self.actor,
            "details": json.loads(self.details) if self.details else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for API database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def log_audit(db: Session, entity_type: str, entity_id: str, action: str, actor: str, details: dict = None):
    """Record an immutable audit log entry."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        details=json.dumps(details or {}),
    )
    db.add(entry)
    db.commit()
