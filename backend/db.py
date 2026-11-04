"""Database models, connections, and relational schemas for Qmoosa Equality."""
import datetime
import json
from pathlib import Path
from typing import Generator
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from starlette import status
from fastapi import HTTPException

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "qmoosa.db"
DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"

import os

if "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]

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


# Explicit finite-state transition table enforcing terminal states
VALID_TRANSITIONS = {
    GrantStatus.SUBMITTED: {GrantStatus.UNDER_REVIEW, GrantStatus.CANCELLED},
    GrantStatus.UNDER_REVIEW: {GrantStatus.APPROVED, GrantStatus.REJECTED, GrantStatus.CANCELLED},
    GrantStatus.APPROVED: {GrantStatus.DISBURSED, GrantStatus.CANCELLED},
    GrantStatus.DISBURSED: set(),  # Terminal state: cannot be moved back to APPROVED
    GrantStatus.REJECTED: set(),   # Terminal state
    GrantStatus.CANCELLED: set(),  # Terminal state
}


def validate_grant_transition(current_status: str, target_status: str) -> None:
    """Validate grant status transition against explicit state table."""
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Illegal grant state transition: '{current_status}' cannot transition to '{target_status}'. "
                f"Allowed transitions: {sorted(list(allowed)) if allowed else 'None (Terminal state)'}."
            ),
        )


class GrantProposal(Base):
    __tablename__ = "grant_proposals"

    id = Column(String(64), primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    requested_amount_qeq = Column(Integer, nullable=False)
    beneficiary_address = Column(String(58), nullable=False, index=True)
    description = Column(Text, nullable=False)
    network = Column(String(20), nullable=False, default="testnet")
    asset_id = Column(Integer, nullable=False, default=774088414)
    status = Column(String(30), nullable=False, default=GrantStatus.SUBMITTED, index=True)
    reviewer_notes = Column(Text, nullable=True)
    onchain_tx_id = Column(String(64), nullable=True, unique=True, index=True)
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
            "network": self.network,
            "asset_id": self.asset_id,
            "status": self.status,
            "reviewer_notes": self.reviewer_notes,
            "onchain_tx_id": self.onchain_tx_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GrantSettlement(Base):
    """Durable settlement record enforcing single-disbursement and anti-replay constraints."""
    __tablename__ = "grant_settlements"
    __table_args__ = (
        UniqueConstraint(
            "network_identity",
            "root_transaction_id",
            "inner_transaction_path",
            name="uq_settlement_payment",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    grant_id = Column(String(64), ForeignKey("grant_proposals.id"), nullable=False, unique=True, index=True)
    network_identity = Column(String(100), nullable=False, index=True)
    root_transaction_id = Column(String(64), nullable=False, index=True)
    inner_transaction_path = Column(String(30), nullable=False, default="root")
    asset_id = Column(Integer, nullable=False)
    sender = Column(String(58), nullable=False)
    receiver = Column(String(58), nullable=False)
    amount_base_units = Column(Integer, nullable=False)
    confirmed_round = Column(Integer, nullable=False)
    verified_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "grant_id": self.grant_id,
            "network_identity": self.network_identity,
            "root_transaction_id": self.root_transaction_id,
            "inner_transaction_path": self.inner_transaction_path,
            "asset_id": self.asset_id,
            "sender": self.sender,
            "receiver": self.receiver,
            "amount_base_units": self.amount_base_units,
            "confirmed_round": self.confirmed_round,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


class AuditLog(Base):
    """Audit log tracking state changes and administrative reviews."""
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
    """Create all tables and execute required schema migrations on existing databases."""
    Base.metadata.create_all(bind=engine)
    # Ensure unique constraint index exists even on legacy databases
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_grant_proposals_onchain_tx_id "
            "ON grant_proposals(onchain_tx_id) WHERE onchain_tx_id IS NOT NULL;"
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_payment "
            "ON grant_settlements(network_identity, root_transaction_id, inner_transaction_path);"
        )


def get_db() -> Generator[Session, None, None]:
    """Dependency for API database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def record_audit(
    db: Session,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: str,
    details: dict = None,
    commit: bool = False,
) -> AuditLog:
    """Record an audit log entry within the caller's transaction.
    By default, commit is False so that entity mutation and audit logging
    are committed atomically in a single transaction.
    """
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        details=json.dumps(details or {}),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry


def log_audit(
    db: Session,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: str,
    details: dict = None,
    commit: bool = False,
) -> AuditLog:
    """Backwards-compatible alias for record_audit."""
    return record_audit(db, entity_type, entity_id, action, actor, details, commit=commit)
