"""Hardened FastAPI Backend for Qmoosa Equality.
Connects directly to live Algorand blockchain nodes, enforces persistent relational storage,
audit logging, strict security headers, and ML-DSA-65 post-quantum verification.
"""
import base64
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session
from algosdk.encoding import is_valid_address
from algosdk.v2client.algod import AlgodClient

# Path setup
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend.db import AuditLog, GrantProposal, GrantStatus, get_db, init_db, log_audit
from men.economics import ALLOCATION_BPS, allocate
from men.pqc import verify_manifest

# Initialize Database
init_db()

app = FastAPI(
    title="Qmoosa Equality Hardened API",
    version="2.0.0",
    description="Live Algorand node integration, persistent grant registry, and PQC verification.",
)

# Configurable CORS
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Security Headers & Size Limit Middleware
MAX_REQUEST_BYTES = 1024 * 1024  # 1 MB


@app.middleware("http")
async def security_and_limit_middleware(request: Request, call_next):
    content_length_str = request.headers.get("content-length")
    if content_length_str is not None:
        try:
            content_length = int(content_length_str)
            if content_length > MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Payload exceeds 1 MB limit."},
                )
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Invalid Content-Length header."},
            )

    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Payload exceeds 1 MB limit."},
            )

    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:;"
    return response


MAINNET_ALGOD = os.getenv("MAINNET_ALGOD_URL", "https://mainnet-api.algonode.cloud")
TESTNET_ALGOD = os.getenv("TESTNET_ALGOD_URL", "https://testnet-api.algonode.cloud")
MAINNET_INDEXER = os.getenv("MAINNET_INDEXER_URL", "https://mainnet-idx.algonode.cloud")
TESTNET_INDEXER = os.getenv("TESTNET_INDEXER_URL", "https://testnet-idx.algonode.cloud")
MAINNET_ASSET_ID = int(os.getenv("MAINNET_ASSET_ID", "3737683297"))
TESTNET_ASSET_ID = int(os.getenv("TESTNET_ASSET_ID", "774088414"))
TESTNET_APP_ID = int(os.getenv("TESTNET_APP_ID", "774088598"))
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
ADMIN_OPERATOR_IDENTITY = os.getenv("ADMIN_OPERATOR_IDENTITY", "verified_council_lead")
TESTNET_TREASURY_APP_ADDRESS = os.getenv(
    "TESTNET_TREASURY_APP_ADDRESS", "A2SUZAVEYRGQNXG7PMJP3W3JZHA7F24PRUTGHOQ4Q6AEWC574VR7S5OZEE"
)
AUTHORIZED_TREASURY_ADDRESSES = {
    a.strip()
    for a in os.getenv(
        "AUTHORIZED_TREASURY_ADDRESSES",
        f"{TESTNET_TREASURY_APP_ADDRESS},TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
    ).split(",")
    if a.strip()
}

security = HTTPBearer(auto_error=False)


def get_authenticated_admin(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Enforce strict administrative authorization for governance actions.
    Fails closed if ADMIN_API_KEY is not configured in the host environment.
    Derives operator identity strictly from server-side verified configuration,
    never trusting caller-supplied headers.
    """
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrative operations disabled: ADMIN_API_KEY is not configured in environment.",
        )

    token = None
    if creds:
        token = creds.credentials
    elif "x-admin-key" in request.headers:
        token = request.headers["x-admin-key"]

    if not token or token != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid administrative Bearer token or X-Admin-Key header required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reviewer identity derived strictly from server configuration
    return ADMIN_OPERATOR_IDENTITY


def verify_onchain_disbursement_tx(
    tx_id: str,
    proposal_id: str,
    beneficiary_address: str,
    expected_amount_qeq: int,
    db: Session,
    network: str = "testnet",
) -> Dict[str, Any]:
    """Verify live on-chain Algorand settlement for grant disbursements.
    Guarantees:
    1. Replay prevention: tx_id has not already been used for another proposal in DB.
    2. Confirmation: tx has confirmed on the target Algorand network.
    3. Sender: must be the authorized treasury escrow/disburser address.
    4. Asset: matches expected QEQ ASA ID.
    5. Receiver: matches registered proposal beneficiary address.
    6. Amount: transfers at least the requested amount in base units.
    7. Grant binding: if note is present, validates note binds to proposal_id.
    """
    # 1. Durable Replay Check in Database
    existing = db.query(GrantProposal).filter(
        GrantProposal.onchain_tx_id == tx_id,
        GrantProposal.id != proposal_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transaction replay rejected: Transaction {tx_id} was already used to disburse proposal {existing.id}.",
        )

    expected_asset_id = MAINNET_ASSET_ID if network == "mainnet" else TESTNET_ASSET_ID
    expected_base_units = expected_amount_qeq * (10 ** 6)
    idx_url = MAINNET_INDEXER if network == "mainnet" else TESTNET_INDEXER
    algod_url = MAINNET_ALGOD if network == "mainnet" else TESTNET_ALGOD

    tx = None
    confirmed_round = 0

    # Query Indexer
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{idx_url}/v2/transactions/{tx_id}")
            if resp.status_code == 200:
                tx_json = resp.json().get("transaction", {})
                tx = tx_json
                confirmed_round = tx_json.get("confirmed-round", 0)
    except Exception:
        pass

    # Fall back to Algod pending transaction info
    if not tx:
        try:
            algod_client = AlgodClient("", algod_url)
            pending_info = algod_client.pending_transaction_info(tx_id)
            if pending_info:
                confirmed_round = pending_info.get("confirmed-round", 0)
                tx = pending_info
        except Exception:
            pass

    if not tx:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disbursement transaction {tx_id} could not be located on {network} Algorand ledger.",
        )

    if confirmed_round <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disbursement transaction {tx_id} is pending and not yet confirmed on {network} ledger.",
        )

    # 2. Extract transfer fields and note
    details_found = []
    tx_sender = None
    tx_receiver = None
    tx_asset_id = None
    tx_amount = 0
    raw_note = None

    if "asset-transfer-transaction" in tx:
        axfer = tx["asset-transfer-transaction"]
        tx_sender = tx.get("sender") or axfer.get("sender")
        tx_asset_id = axfer.get("asset-id")
        tx_receiver = axfer.get("receiver")
        tx_amount = axfer.get("amount", 0)
        raw_note = tx.get("note")
        details_found.append(f"axfer: sender={tx_sender}, asset={tx_asset_id}, receiver={tx_receiver}, amount={tx_amount}")

    elif "inner-txns" in tx:
        for inner in tx["inner-txns"]:
            if "asset-transfer-transaction" in inner:
                axfer = inner["asset-transfer-transaction"]
                tx_sender = inner.get("sender") or tx.get("sender")
                tx_asset_id = axfer.get("asset-id")
                tx_receiver = axfer.get("receiver")
                tx_amount = axfer.get("amount", 0)
                raw_note = inner.get("note") or tx.get("note")
                details_found.append(f"inner-axfer: sender={tx_sender}, asset={tx_asset_id}, receiver={tx_receiver}, amount={tx_amount}")
                break

    elif "txn" in tx and "txn" in tx["txn"]:
        raw_txn = tx["txn"]["txn"]
        if raw_txn.get("type") == "axfer":
            tx_sender = raw_txn.get("snd")
            tx_asset_id = raw_txn.get("xaid")
            tx_receiver = raw_txn.get("arcv")
            tx_amount = raw_txn.get("aamt", 0)
            raw_note = raw_txn.get("note")
            details_found.append(f"algod-axfer: sender={tx_sender}, asset={tx_asset_id}, receiver={tx_receiver}, amount={tx_amount}")

    # 3. Verify authorized treasury sender
    if AUTHORIZED_TREASURY_ADDRESSES and tx_sender not in AUTHORIZED_TREASURY_ADDRESSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unauthorized disbursement sender: Transaction sender {tx_sender} is not an authorized "
                f"treasury or disburser address ({', '.join(AUTHORIZED_TREASURY_ADDRESSES)})."
            ),
        )

    # 4. Verify asset, beneficiary, and amount
    if tx_asset_id != expected_asset_id or tx_receiver != beneficiary_address or tx_amount < expected_base_units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"On-chain disbursement validation failed for transaction {tx_id}. "
                f"Required: asset={expected_asset_id}, receiver={beneficiary_address}, min_amount={expected_base_units}. "
                f"Ledger observations: {', '.join(details_found) if details_found else 'No valid asset transfer found'}."
            ),
        )

    # 5. Verify grant note binding if present
    if raw_note:
        try:
            decoded_note = base64.b64decode(raw_note).decode("utf-8", errors="ignore")
            if "qeq:grant:" in decoded_note and proposal_id not in decoded_note:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Grant binding mismatch: Transaction note specifies a different grant ({decoded_note}) than {proposal_id}.",
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e

    return {
        "tx_id": tx_id,
        "confirmed_round": confirmed_round,
        "sender": tx_sender,
        "network": network,
        "verified": True,
    }


# --- Pydantic Schemas ---
class GrantSubmissionRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=255)
    category: str = Field(..., max_length=50)
    requested_amount_qeq: int = Field(..., gt=0, le=500_000)
    beneficiary_address: str = Field(..., min_length=58, max_length=58)
    description: str = Field(..., min_length=20, max_length=5000)

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


class GrantReviewRequest(BaseModel):
    status: str
    reviewer_notes: str = Field(..., min_length=3, max_length=1000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in {GrantStatus.UNDER_REVIEW, GrantStatus.APPROVED, GrantStatus.REJECTED, GrantStatus.CANCELLED}:
            raise ValueError(f"Status transition must be one of UNDER_REVIEW, APPROVED, REJECTED, CANCELLED")
        return v


class GrantDisburseRequest(BaseModel):
    onchain_tx_id: str = Field(..., min_length=52, max_length=64)


class PqcVerifyRequest(BaseModel):
    public_key_hex: str
    document: Dict[str, Any]
    signature_hex: str


# --- Health & Readiness Endpoints ---
@app.get("/api/health/live")
def liveness():
    """Liveness probe: verifies process is responsive."""
    return {"status": "ALIVE"}


@app.get("/api/health/ready")
def readiness(db: Session = Depends(get_db)):
    """Readiness probe: verifies live database and Algorand node connectivity."""
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_err = str(e)

    node_errors = []
    mainnet_round = None
    try:
        mc = AlgodClient("", MAINNET_ALGOD)
        mainnet_round = mc.status().get("last-round")
    except Exception as e:
        node_errors.append(f"Mainnet node unreachable: {e}")

    testnet_round = None
    try:
        tc = AlgodClient("", TESTNET_ALGOD)
        testnet_round = tc.status().get("last-round")
    except Exception as e:
        node_errors.append(f"Testnet node unreachable: {e}")

    if not db_ok or node_errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "UNREADY",
                "database_ok": db_ok,
                "node_errors": node_errors,
            },
        )

    return {
        "status": "READY",
        "database_ok": True,
        "mainnet_round": mainnet_round,
        "testnet_round": testnet_round,
        "reality_gate": "ENFORCED",
    }


# Backwards compatibility alias
@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    return readiness(db=db)


# --- On-Chain Tokenomics & State ---
@app.get("/api/tokenomics")
def get_tokenomics(network: str = "mainnet"):
    """Query live on-chain parameters from the Algorand blockchain."""
    if network not in ("mainnet", "testnet"):
        raise HTTPException(status_code=400, detail="Network must be 'mainnet' or 'testnet'")

    algod_url = MAINNET_ALGOD if network == "mainnet" else TESTNET_ALGOD
    asset_id = MAINNET_ASSET_ID if network == "mainnet" else TESTNET_ASSET_ID
    client = AlgodClient("", algod_url)

    try:
        asset_info = client.asset_info(asset_id)
        params = asset_info.get("params", {})
        total_supply = params.get("total", 0)
        decimals = params.get("decimals", 6)
        formatted_total = total_supply / (10 ** decimals)

        # Proposed governance allocations (Integer math)
        allocations = allocate(total_supply)
        formatted_allocations = {k: v / (10 ** decimals) for k, v in allocations.items()}

        return {
            "network": network,
            "asset_id": asset_id,
            "name": params.get("name"),
            "unit_name": params.get("unit-name"),
            "decimals": decimals,
            "total_supply": formatted_total,
            "creator": params.get("creator"),
            "manager": params.get("manager"),
            "reserve": params.get("reserve"),
            "freeze": params.get("freeze"),
            "clawback": params.get("clawback"),
            "proposed_allocations_policy": {
                "fractions": formatted_allocations,
                "bps": ALLOCATION_BPS,
                "status": "PROPOSED_GOVERNANCE_POLICY_NOT_ESCROW_LOCKED",
            },
            "explorer_url": f"https://lora.algokit.io/{network}/asset/{asset_id}",
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Algorand node query failed: {e}")


@app.get("/api/treasury")
def get_treasury():
    """Query live on-chain state of the Community Treasury Application."""
    client = AlgodClient("", TESTNET_ALGOD)
    try:
        app_info = client.application_info(TESTNET_APP_ID)
        params = app_info.get("params", {})
        return {
            "application_id": TESTNET_APP_ID,
            "creator": params.get("creator"),
            "global_state": params.get("global-state", []),
            "explorer_url": f"https://lora.algokit.io/testnet/application/{TESTNET_APP_ID}",
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Treasury query failed: {e}")


# --- Persistent Grant Registry ---
@app.get("/api/grants/proposals")
def list_grants(
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(GrantProposal)
    if status_filter:
        query = query.filter(GrantProposal.status == status_filter)
    if category_filter:
        query = query.filter(GrantProposal.category == category_filter)

    proposals = query.order_by(GrantProposal.created_at.desc()).all()
    return {"proposals": [p.to_dict() for p in proposals], "count": len(proposals)}


@app.post("/api/grants/proposals", status_code=status.HTTP_201_CREATED)
def submit_grant(req: GrantSubmissionRequest, db: Session = Depends(get_db)):
    grant_id = f"qeq-grant-{uuid.uuid4().hex[:12]}"
    proposal = GrantProposal(
        id=grant_id,
        title=req.title,
        category=req.category,
        requested_amount_qeq=req.requested_amount_qeq,
        beneficiary_address=req.beneficiary_address,
        description=req.description,
        status=GrantStatus.SUBMITTED,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    log_audit(
        db,
        entity_type="GRANT_PROPOSAL",
        entity_id=grant_id,
        action="SUBMITTED",
        actor=req.beneficiary_address,
        details={"title": req.title, "amount": req.requested_amount_qeq},
    )

    return {"message": "Grant proposal registered successfully", "proposal": proposal.to_dict()}


@app.patch("/api/grants/proposals/{grant_id}/review")
def review_grant(
    grant_id: str,
    req: GrantReviewRequest,
    reviewer: str = Depends(get_authenticated_admin),
    db: Session = Depends(get_db),
):
    proposal = db.query(GrantProposal).filter(GrantProposal.id == grant_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Grant proposal not found")

    old_status = proposal.status
    proposal.status = req.status
    proposal.reviewer_notes = req.reviewer_notes
    db.commit()
    db.refresh(proposal)

    log_audit(
        db,
        entity_type="GRANT_PROPOSAL",
        entity_id=grant_id,
        action="STATUS_CHANGED",
        actor=reviewer,
        details={"old_status": old_status, "new_status": req.status, "notes": req.reviewer_notes},
    )

    return {"message": f"Proposal transitioned to {req.status}", "proposal": proposal.to_dict()}


@app.patch("/api/grants/proposals/{grant_id}/disburse")
def record_disbursement(
    grant_id: str,
    req: GrantDisburseRequest,
    network: str = "testnet",
    admin: str = Depends(get_authenticated_admin),
    db: Session = Depends(get_db),
):
    proposal = db.query(GrantProposal).filter(GrantProposal.id == grant_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Grant proposal not found")

    if proposal.status != GrantStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Only APPROVED proposals can be disbursed")

    # Live On-Chain Settlement Verification Gate
    verification = verify_onchain_disbursement_tx(
        tx_id=req.onchain_tx_id,
        proposal_id=proposal.id,
        beneficiary_address=proposal.beneficiary_address,
        expected_amount_qeq=proposal.requested_amount_qeq,
        db=db,
        network=network,
    )

    proposal.status = GrantStatus.DISBURSED
    proposal.onchain_tx_id = req.onchain_tx_id
    db.commit()
    db.refresh(proposal)

    log_audit(
        db,
        entity_type="GRANT_PROPOSAL",
        entity_id=grant_id,
        action="DISBURSED",
        actor=admin,
        details={
            "onchain_tx_id": req.onchain_tx_id,
            "confirmed_round": verification.get("confirmed_round"),
            "network": network,
        },
    )

    return {
        "message": "Disbursement verified on-chain and recorded successfully",
        "verification": verification,
        "proposal": proposal.to_dict(),
    }


@app.get("/api/grants/audit-logs/{grant_id}")
def get_grant_audit_logs(grant_id: str, db: Session = Depends(get_db)):
    logs = db.query(AuditLog).filter(AuditLog.entity_id == grant_id).order_by(AuditLog.created_at.asc()).all()
    return {"audit_logs": [l.to_dict() for l in logs]}


# --- ML-DSA-65 Verification Endpoint ---
@app.post("/api/pqc/verify")
def verify_pqc_signature(req: PqcVerifyRequest):
    try:
        public_key = bytes.fromhex(req.public_key_hex)
        sig = bytes.fromhex(req.signature_hex)
        is_valid = verify_manifest(public_key, req.document, sig)
        return {
            "valid": is_valid,
            "scheme": "NIST_FIPS_204_ML_DSA_65",
            "document": req.document,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Verification failed: {e}")


# Mount Static Frontend
frontend_dir = root / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
