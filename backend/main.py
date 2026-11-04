"""FastAPI application entry point for Qmoosa Equality.
Integrates pure ASGI middleware, modular authentication, persistent grant registry,
and live Algorand node connectivity.
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from algosdk.v2client.algod import AlgodClient

# Path setup
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend.auth import (
    get_authenticated_admin,
    get_admin_api_key,
    get_admin_operator_identity,
)
from backend.db import get_db, init_db
from backend.grants import router as grants_router
from backend.middleware import RequestSizeLimitMiddleware, MAX_REQUEST_BYTES
from backend.settlement import (
    COMPROMISED_ADMIN_ADDR,
    get_network_config,
    verify_settlement_evidence,
)
from men.economics import ALLOCATION_BPS, allocate
from men.pqc import verify_manifest

# Initialize Database Schema
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

# Pure ASGI Streaming Request Size & Security Headers Middleware
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)

# Include Modular Grant Lifecycle Router
app.include_router(grants_router)

# Live Node URLs
MAINNET_ALGOD = os.getenv("MAINNET_ALGOD_URL", "https://mainnet-api.algonode.cloud")
TESTNET_ALGOD = os.getenv("TESTNET_ALGOD_URL", "https://testnet-api.algonode.cloud")
MAINNET_ASSET_ID = int(os.getenv("MAINNET_ASSET_ID", "3737683297"))
TESTNET_ASSET_ID = int(os.getenv("TESTNET_ASSET_ID", "774088414"))
TESTNET_APP_ID = int(os.getenv("TESTNET_APP_ID", "774088598"))


class PqcVerifyRequest(BaseModel):
    public_key_hex: str
    document: Dict[str, Any]
    signature_hex: str


# --- Health & Readiness Probes ---
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
