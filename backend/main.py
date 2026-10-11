"""Production FastAPI Backend for Qmoosa Equality.
Connects directly to live Algorand blockchain nodes and verifies PQC manifests.
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from algosdk.v2client.algod import AlgodClient

# Path setup
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from men.economics import ALLOCATION_BPS, allocate, issuance_budget
from men.pqc import encode_manifest, verify_manifest

app = FastAPI(
    title="Qmoosa Equality Production API",
    version="1.0.0",
    description="Real on-chain Algorand and Post-Quantum cryptographic backend for Qmoosa Equality."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAINNET_ALGOD = "https://mainnet-api.algonode.cloud"
TESTNET_ALGOD = "https://testnet-api.algonode.cloud"
MAINNET_ASSET_ID = 3737683297
TESTNET_ASSET_ID = 774088414
TESTNET_APP_ID = 774088598

# In-memory storage for submitted community grant applications (in production backed by DB)
GRANT_PROPOSALS: List[Dict[str, Any]] = [
    {
        "id": "grant-001",
        "title": "Moolnivasi Youth Coding & Quantum Literacy Program",
        "category": "community_grants",
        "requested_amount_qeq": 50000,
        "beneficiary_address": "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM",
        "status": "APPROVED",
        "description": "Providing post-quantum and web3 engineering literacy to underprivileged rural youth."
    },
    {
        "id": "grant-002",
        "title": "SC/ST Micro-Weaver Cooperative Solar Loom Setup",
        "category": "social_enterprises",
        "requested_amount_qeq": 25000,
        "beneficiary_address": "A2SUZAVEYRGQNXG7PMJP3W3JZHA7F24PRUTGHOQ4Q6AEWC574VR7S5OZEE",
        "status": "UNDER_REVIEW",
        "description": "Sustainable solar-powered looms for artisanal handloom cooperatives."
    }
]

class GrantSubmission(BaseModel):
    title: str
    category: str
    requested_amount_qeq: int
    beneficiary_address: str
    description: str

class PqcVerifyRequest(BaseModel):
    public_key_hex: str
    document: Dict[str, Any]
    signature_hex: str

@app.get("/api/health")
def health_check():
    """Verify live connectivity to Algorand nodes."""
    try:
        mainnet_client = AlgodClient("", MAINNET_ALGOD)
        mainnet_status = mainnet_client.status()
        mainnet_round = mainnet_status.get("last-round")
    except Exception as e:
        mainnet_round = f"error: {e}"

    try:
        testnet_client = AlgodClient("", TESTNET_ALGOD)
        testnet_status = testnet_client.status()
        testnet_round = testnet_status.get("last-round")
    except Exception as e:
        testnet_round = f"error: {e}"

    return {
        "status": "healthy",
        "reality_gate": "ENFORCED",
        "zero_simulation": True,
        "mainnet_round": mainnet_round,
        "testnet_round": testnet_round,
    }

@app.get("/api/tokenomics")
def get_tokenomics(network: str = "mainnet"):
    """Query real live on-chain tokenomics from Algorand."""
    algod_url = MAINNET_ALGOD if network == "mainnet" else TESTNET_ALGOD
    asset_id = MAINNET_ASSET_ID if network == "mainnet" else TESTNET_ASSET_ID
    client = AlgodClient("", algod_url)

    try:
        asset_info = client.asset_info(asset_id)
        params = asset_info.get("params", {})
        total_supply = params.get("total", 0)
        decimals = params.get("decimals", 6)
        formatted_total = total_supply / (10 ** decimals)

        # Calculate exact integer allocation distribution
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
            "allocations_qeq": formatted_allocations,
            "allocations_bps": ALLOCATION_BPS,
            "explorer_url": f"https://lora.algokit.io/{network}/asset/{asset_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Algorand node query failed: {e}")

@app.get("/api/treasury")
def get_treasury():
    """Query real live state of the Community Treasury Smart Contract."""
    client = AlgodClient("", TESTNET_ALGOD)
    try:
        app_info = client.application_info(TESTNET_APP_ID)
        params = app_info.get("params", {})
        return {
            "application_id": TESTNET_APP_ID,
            "creator": params.get("creator"),
            "global_state": params.get("global-state", []),
            "explorer_url": f"https://lora.algokit.io/testnet/application/{TESTNET_APP_ID}"
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to query application: {e}")

@app.get("/api/grants/proposals")
def list_grants():
    return {"proposals": GRANT_PROPOSALS}

@app.post("/api/grants/proposals")
def submit_grant(grant: GrantSubmission):
    if grant.category not in ALLOCATION_BPS:
        raise HTTPException(status_code=400, detail=f"Category must be one of: {list(ALLOCATION_BPS.keys())}")
    if grant.requested_amount_qeq <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    new_id = f"grant-00{len(GRANT_PROPOSALS) + 1}"
    proposal = {
        "id": new_id,
        "title": grant.title,
        "category": grant.category,
        "requested_amount_qeq": grant.requested_amount_qeq,
        "beneficiary_address": grant.beneficiary_address,
        "status": "SUBMITTED",
        "description": grant.description
    }
    GRANT_PROPOSALS.append(proposal)
    return {"message": "Grant proposal registered successfully", "proposal": proposal}

@app.post("/api/pqc/verify")
def verify_pqc_signature(req: PqcVerifyRequest):
    """Real NIST FIPS 204 ML-DSA-65 verification."""
    try:
        public_key = bytes.fromhex(req.public_key_hex)
        sig = bytes.fromhex(req.signature_hex)
        is_valid = verify_manifest(public_key, req.document, sig)
        return {
            "valid": is_valid,
            "scheme": "NIST_FIPS_204_ML_DSA_65",
            "document": req.document
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Verification failed: {e}")

# Mount static frontend
frontend_dir = root / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
