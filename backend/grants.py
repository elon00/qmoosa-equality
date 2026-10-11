"""Grant lifecycle and proposal management module for Qmoosa Equality."""
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from algosdk.encoding import is_valid_address

from backend.auth import get_authenticated_admin
from backend.db import (
    AuditLog,
    GrantProposal,
    GrantSettlement,
    GrantStatus,
    get_db,
    record_audit,
    validate_grant_transition,
)
from backend.settlement import (
    AlgorandNetwork,
    get_network_config,
    verify_settlement_evidence,
)
from men.economics import ALLOCATION_BPS

router = APIRouter(prefix="/api/grants", tags=["grants"])


class GrantSubmissionRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=255)
    category: str = Field(..., max_length=50)
    requested_amount_qeq: int = Field(..., gt=0, le=500_000)
    beneficiary_address: str = Field(..., min_length=58, max_length=58)
    description: str = Field(..., min_length=20, max_length=5000)
    network: str = Field(default="testnet")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in ALLOCATION_BPS:
            raise ValueError(f"Category must be one of: {list(ALLOCATION_BPS.keys())}")
        return v

    @field_validator("beneficiary_address")
    @classmethod
    def validate_algorand_address(cls, v: str) -> str:
        if not is_valid_address(v):
            raise ValueError("Invalid Algorand public address")
        return v

    @field_validator("network")
    @classmethod
    def validate_network(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in {"mainnet", "testnet"}:
            raise ValueError("Network must be 'mainnet' or 'testnet'")
        return clean


class GrantReviewRequest(BaseModel):
    status: str
    reviewer_notes: str = Field(..., min_length=3, max_length=1000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in GrantStatus.ALL:
            raise ValueError(f"Status must be one of {GrantStatus.ALL}")
        return v


class GrantDisburseRequest(BaseModel):
    onchain_tx_id: str = Field(..., min_length=52, max_length=64)


@router.get("/proposals")
def list_grants(
    status_filter: Optional[str] = Query(None, alias="status"),
    category_filter: Optional[str] = Query(None, alias="category"),
    db: Session = Depends(get_db),
):
    """List persistent grant proposals with optional filtering."""
    query = db.query(GrantProposal)
    if status_filter:
        query = query.filter(GrantProposal.status == status_filter)
    if category_filter:
        query = query.filter(GrantProposal.category == category_filter)

    proposals = query.order_by(GrantProposal.created_at.desc()).all()
    return {"proposals": [p.to_dict() for p in proposals], "count": len(proposals)}


@router.post("/proposals", status_code=status.HTTP_201_CREATED)
def submit_grant(req: GrantSubmissionRequest, db: Session = Depends(get_db)):
    """Submit a grant proposal. Atomic creation with persistent audit log."""
    grant_id = f"qeq-grant-{uuid.uuid4().hex[:12]}"
    cfg = get_network_config(req.network)

    proposal = GrantProposal(
        id=grant_id,
        title=req.title,
        category=req.category,
        requested_amount_qeq=req.requested_amount_qeq,
        beneficiary_address=req.beneficiary_address,
        description=req.description,
        network=cfg.network.value,
        asset_id=cfg.asset_id,
        status=GrantStatus.SUBMITTED,
    )
    db.add(proposal)

    record_audit(
        db,
        entity_type="GRANT_PROPOSAL",
        entity_id=grant_id,
        action="SUBMITTED",
        actor=req.beneficiary_address,
        details={
            "title": req.title,
            "amount": req.requested_amount_qeq,
            "network": cfg.network.value,
            "asset_id": cfg.asset_id,
        },
        commit=False,
    )

    try:
        db.commit()
        db.refresh(proposal)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist grant proposal: {e}",
        )

    return {"message": "Grant proposal registered successfully", "proposal": proposal.to_dict()}


@router.patch("/proposals/{grant_id}/review")
def review_grant(
    grant_id: str,
    req: GrantReviewRequest,
    reviewer: str = Depends(get_authenticated_admin),
    db: Session = Depends(get_db),
):
    """Review and transition grant status.
    Enforces:
    1. Valid finite-state machine transitions.
    2. Terminal state protection (DISBURSED grants cannot be returned to APPROVED).
    3. Server-derived reviewer identity (actor).
    4. Atomic status update and audit log recording.
    """
    proposal = db.query(GrantProposal).filter(GrantProposal.id == grant_id).first()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant proposal not found")

    old_status = proposal.status
    validate_grant_transition(old_status, req.status)

    proposal.status = req.status
    proposal.reviewer_notes = req.reviewer_notes

    record_audit(
        db,
        entity_type="GRANT_PROPOSAL",
        entity_id=grant_id,
        action="STATUS_CHANGED",
        actor=reviewer,
        details={"old_status": old_status, "new_status": req.status, "notes": req.reviewer_notes},
        commit=False,
    )

    try:
        db.commit()
        db.refresh(proposal)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to commit review status update: {e}",
        )

    return {"message": f"Proposal transitioned to {req.status}", "proposal": proposal.to_dict()}


@router.patch("/proposals/{grant_id}/disburse")
def disburse_grant(
    grant_id: str,
    req: GrantDisburseRequest,
    admin: str = Depends(get_authenticated_admin),
    db: Session = Depends(get_db),
):
    """Verify on-chain settlement evidence and atomically record disbursement.

    Enforces:
    1. Grant must be in APPROVED status.
    2. Uses persisted grant network and asset ID; disbursement request cannot switch networks.
    3. Live on-chain verification of sender, receiver, exact canonical note binding, amount,
       and unconsumed evidence.
    4. Durable replay protection via unique constraint on GrantSettlement.
    5. Atomic transaction: inserts GrantSettlement, transitions status to DISBURSED, records audit event.
    6. Replays return HTTP 409 Conflict.
    """
    proposal = db.query(GrantProposal).filter(GrantProposal.id == grant_id).first()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant proposal not found")

    if proposal.status != GrantStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot disburse proposal with status '{proposal.status}'. Only APPROVED proposals can be disbursed.",
        )

    # Replay check in existing settlements table before network query
    existing_settlement = (
        db.query(GrantSettlement)
        .filter(
            GrantSettlement.root_transaction_id == req.onchain_tx_id,
        )
        .first()
    )
    if existing_settlement:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Transaction replay rejected: Transaction '{req.onchain_tx_id}' was already consumed "
                f"as disbursement evidence for grant '{existing_settlement.grant_id}'."
            ),
        )

    # Live on-chain settlement evidence verification
    payment = verify_settlement_evidence(
        tx_id=req.onchain_tx_id,
        grant_id=proposal.id,
        beneficiary_address=proposal.beneficiary_address,
        expected_amount_qeq=proposal.requested_amount_qeq,
        configured_network=proposal.network,
        configured_asset_id=proposal.asset_id,
    )

    # Atomically insert settlement record, transition proposal, and record audit log
    settlement = GrantSettlement(
        grant_id=proposal.id,
        network_identity=payment.network_identity,
        root_transaction_id=payment.root_transaction_id,
        inner_transaction_path=payment.inner_transaction_path,
        asset_id=payment.asset_id,
        sender=payment.sender,
        receiver=payment.receiver,
        amount_base_units=payment.amount_base_units,
        confirmed_round=payment.confirmed_round,
    )
    db.add(settlement)

    proposal.status = GrantStatus.DISBURSED
    proposal.onchain_tx_id = payment.root_transaction_id

    record_audit(
        db,
        entity_type="GRANT_PROPOSAL",
        entity_id=grant_id,
        action="DISBURSED",
        actor=admin,
        details={
            "root_transaction_id": payment.root_transaction_id,
            "inner_transaction_path": payment.inner_transaction_path,
            "confirmed_round": payment.confirmed_round,
            "network": proposal.network,
            "asset_id": payment.asset_id,
            "amount_base_units": payment.amount_base_units,
        },
        commit=False,
    )

    try:
        db.commit()
        db.refresh(proposal)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Concurrent settlement conflict: Transaction or grant was already disbursed ({e}).",
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record settlement: {e}",
        )

    return {
        "message": "Disbursement verified on-chain and recorded successfully",
        "settlement": settlement.to_dict(),
        "proposal": proposal.to_dict(),
    }


@router.get("/audit-logs/{grant_id}")
def get_grant_audit_logs(grant_id: str, db: Session = Depends(get_db)):
    """Retrieve audit log history for a specific grant proposal."""
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == grant_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    return {"grant_id": grant_id, "audit_logs": [l.to_dict() for l in logs]}
