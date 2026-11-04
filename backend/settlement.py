"""Algorand on-chain settlement normalization and verification engine for Qmoosa Equality."""
import base64
from dataclasses import dataclass
from enum import Enum
import os
from typing import Any, Dict, List, Optional
from algosdk.encoding import encode_address, is_valid_address
from algosdk.v2client.algod import AlgodClient
from fastapi import HTTPException, status
import httpx

COMPROMISED_ADMIN_ADDR = "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM"


class AlgorandNetwork(str, Enum):
    MAINNET = "mainnet"
    TESTNET = "testnet"


@dataclass(frozen=True)
class NetworkConfig:
    network: AlgorandNetwork
    asset_id: int
    application_id: Optional[int]
    treasury_address: str
    genesis_hash: str
    algod_url: str
    indexer_url: str


GENESIS_HASHES = {
    AlgorandNetwork.MAINNET: "wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=",
    AlgorandNetwork.TESTNET: "SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
}


def get_network_config(network_str: str) -> NetworkConfig:
    """Retrieve and validate network-specific configuration.
    Strictly fails closed: refuses unknown networks, missing configs, or compromised authority.
    """
    try:
        net = AlgorandNetwork(network_str.lower().strip())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported network '{network_str}'. Strictly supported: 'mainnet', 'testnet'.",
        )

    if net == AlgorandNetwork.MAINNET:
        asset_id = int(os.getenv("MAINNET_ASSET_ID", "3737683297"))
        app_id_str = os.getenv("MAINNET_APP_ID")
        app_id = int(app_id_str) if app_id_str else None
        treasury_addr = os.getenv("MAINNET_TREASURY_ADDRESS", "").strip()
        algod_url = os.getenv("MAINNET_ALGOD_URL", "https://mainnet-api.algonode.cloud").strip()
        indexer_url = os.getenv("MAINNET_INDEXER_URL", "https://mainnet-idx.algonode.cloud").strip()
    else:
        asset_id = int(os.getenv("TESTNET_ASSET_ID", "774088414"))
        app_id = int(os.getenv("TESTNET_APP_ID", "774088598"))
        treasury_addr = os.getenv(
            "TESTNET_TREASURY_ADDRESS",
            "A2SUZAVEYRGQNXG7PMJP3W3JZHA7F24PRUTGHOQ4Q6AEWC574VR7S5OZEE",
        ).strip()
        algod_url = os.getenv("TESTNET_ALGOD_URL", "https://testnet-api.algonode.cloud").strip()
        indexer_url = os.getenv("TESTNET_INDEXER_URL", "https://testnet-idx.algonode.cloud").strip()

    # Fail-closed validations
    if not treasury_addr:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Settlement verification disabled: No authorized treasury address configured for {net.value}.",
        )

    if not is_valid_address(treasury_addr):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Configuration error: Invalid Algorand treasury address configured for {net.value}.",
        )

    if treasury_addr == COMPROMISED_ADMIN_ADDR:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Configuration rejected: Treasury address for {net.value} matches compromised account (IR-2026-001).",
        )

    return NetworkConfig(
        network=net,
        asset_id=asset_id,
        application_id=app_id,
        treasury_address=treasury_addr,
        genesis_hash=GENESIS_HASHES[net],
        algod_url=algod_url,
        indexer_url=indexer_url,
    )


def build_canonical_grant_note(network: str, asset_id: int, grant_id: str) -> str:
    """Canonical UTF-8 note binding protocol: qeq:grant:v1:<network>:<asset_id>:<grant_id>."""
    return f"qeq:grant:v1:{network.lower().strip()}:{asset_id}:{grant_id.strip()}"


@dataclass(frozen=True)
class NormalizedPayment:
    network_identity: str
    root_transaction_id: str
    inner_transaction_path: str
    confirmed_round: int
    application_id: Optional[int]
    sender: str
    asset_id: int
    receiver: str
    amount_base_units: int
    canonical_grant_binding: str
    rekey_to: Optional[str]
    close_to: Optional[str]
    clawback: Optional[str]


def parse_address(val: Any) -> Optional[str]:
    """Normalize address representation from string or raw bytes."""
    if not val:
        return None
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (bytes, bytearray)):
        if len(val) == 32:
            return encode_address(bytes(val))
    return None


def decode_note_bytes(raw_note_val: Any) -> str:
    """Strictly decode note bytes. Fails on invalid base64 or invalid UTF-8."""
    if not raw_note_val:
        raise ValueError("Missing note")
    if isinstance(raw_note_val, str):
        try:
            raw_bytes = base64.b64decode(raw_note_val, validate=True)
        except Exception as e:
            raise ValueError(f"Invalid Base64 in note: {e}")
    elif isinstance(raw_note_val, (bytes, bytearray)):
        raw_bytes = bytes(raw_note_val)
    else:
        raise ValueError(f"Unsupported note type {type(raw_note_val)}")

    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Invalid UTF-8 in note: {e}")


def parse_indexer_transaction(tx_dict: Dict[str, Any], root_tx_id: str) -> List[NormalizedPayment]:
    """Parse Indexer REST API transaction schema into NormalizedPayments."""
    payments: List[NormalizedPayment] = []
    genesis_hash = tx_dict.get("genesis-hash", "")
    confirmed_round = tx_dict.get("confirmed-round", 0)

    # 1. Root asset transfer
    if "asset-transfer-transaction" in tx_dict:
        axfer = tx_dict["asset-transfer-transaction"]
        note_str = ""
        try:
            note_str = decode_note_bytes(tx_dict.get("note"))
        except Exception:
            pass

        payments.append(
            NormalizedPayment(
                network_identity=genesis_hash,
                root_transaction_id=root_tx_id,
                inner_transaction_path="root",
                confirmed_round=confirmed_round,
                application_id=None,
                sender=tx_dict.get("sender", ""),
                asset_id=axfer.get("asset-id", 0),
                receiver=axfer.get("receiver", ""),
                amount_base_units=axfer.get("amount", 0),
                canonical_grant_binding=note_str,
                rekey_to=tx_dict.get("rekey-to"),
                close_to=axfer.get("close-to"),
                clawback=axfer.get("sender") if axfer.get("sender") != tx_dict.get("sender") else None,
            )
        )

    # 2. Inner transactions
    inner_list = tx_dict.get("inner-txns", [])
    app_id = tx_dict.get("application-transaction", {}).get("application-id") or tx_dict.get("created-application-index")

    for idx, inner in enumerate(inner_list):
        if "asset-transfer-transaction" in inner:
            axfer = inner["asset-transfer-transaction"]
            note_str = ""
            try:
                raw_note = inner.get("note") or tx_dict.get("note")
                note_str = decode_note_bytes(raw_note)
            except Exception:
                pass

            inner_sender = inner.get("sender")
            if not inner_sender:
                # Do NOT substitute outer sender for missing inner sender
                continue

            payments.append(
                NormalizedPayment(
                    network_identity=genesis_hash,
                    root_transaction_id=root_tx_id,
                    inner_transaction_path=f"inner:{idx}",
                    confirmed_round=confirmed_round,
                    application_id=app_id,
                    sender=inner_sender,
                    asset_id=axfer.get("asset-id", 0),
                    receiver=axfer.get("receiver", ""),
                    amount_base_units=axfer.get("amount", 0),
                    canonical_grant_binding=note_str,
                    rekey_to=inner.get("rekey-to"),
                    close_to=axfer.get("close-to"),
                    clawback=axfer.get("sender") if axfer.get("sender") != inner_sender else None,
                )
            )

    return payments


def parse_algod_transaction(tx_dict: Dict[str, Any], root_tx_id: str) -> List[NormalizedPayment]:
    """Parse Algod pending/confirmed transaction info schema into NormalizedPayments."""
    payments: List[NormalizedPayment] = []
    confirmed_round = tx_dict.get("confirmed-round", 0)
    genesis_hash = tx_dict.get("txn", {}).get("txn", {}).get("gh")
    if isinstance(genesis_hash, bytes):
        genesis_hash = base64.b64encode(genesis_hash).decode("utf-8")

    raw_txn = tx_dict.get("txn", {}).get("txn", {})
    if raw_txn.get("type") == "axfer":
        note_str = ""
        try:
            note_str = decode_note_bytes(raw_txn.get("note"))
        except Exception:
            pass

        snd = parse_address(raw_txn.get("snd"))
        arcv = parse_address(raw_txn.get("arcv"))
        rekey = parse_address(raw_txn.get("rekey"))
        aclose = parse_address(raw_txn.get("aclose"))

        payments.append(
            NormalizedPayment(
                network_identity=genesis_hash or "",
                root_transaction_id=root_tx_id,
                inner_transaction_path="root",
                confirmed_round=confirmed_round,
                application_id=None,
                sender=snd or "",
                asset_id=raw_txn.get("xaid", 0),
                receiver=arcv or "",
                amount_base_units=raw_txn.get("aamt", 0),
                canonical_grant_binding=note_str,
                rekey_to=rekey,
                close_to=aclose,
                clawback=None,
            )
        )

    inner_list = tx_dict.get("inner-txns", [])
    app_id = raw_txn.get("apid")

    for idx, inner in enumerate(inner_list):
        i_txn = inner.get("txn", {}).get("txn", {})
        if i_txn.get("type") == "axfer":
            note_str = ""
            try:
                raw_note = i_txn.get("note") or raw_txn.get("note")
                note_str = decode_note_bytes(raw_note)
            except Exception:
                pass

            snd = parse_address(i_txn.get("snd"))
            if not snd:
                continue

            arcv = parse_address(i_txn.get("arcv"))
            rekey = parse_address(i_txn.get("rekey"))
            aclose = parse_address(i_txn.get("aclose"))

            payments.append(
                NormalizedPayment(
                    network_identity=genesis_hash or "",
                    root_transaction_id=root_tx_id,
                    inner_transaction_path=f"inner:{idx}",
                    confirmed_round=confirmed_round,
                    application_id=app_id,
                    sender=snd,
                    asset_id=i_txn.get("xaid", 0),
                    receiver=arcv or "",
                    amount_base_units=i_txn.get("aamt", 0),
                    canonical_grant_binding=note_str,
                    rekey_to=rekey,
                    close_to=aclose,
                    clawback=None,
                )
            )

    return payments


def verify_settlement_evidence(
    tx_id: str,
    grant_id: str,
    beneficiary_address: str,
    expected_amount_qeq: int,
    configured_network: str,
    configured_asset_id: int,
) -> NormalizedPayment:
    """Fetch on-chain transaction evidence, normalize, and verify all 10 invariants strictly."""
    cfg = get_network_config(configured_network)

    if configured_asset_id != cfg.asset_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Asset mismatch: Grant configured for asset {configured_asset_id}, but network {cfg.network.value} uses asset {cfg.asset_id}.",
        )

    expected_base_units = expected_amount_qeq * (10 ** 6)
    expected_canonical_note = build_canonical_grant_note(cfg.network.value, cfg.asset_id, grant_id)

    # 1. Fetch from Indexer
    raw_tx = None
    source = None
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{cfg.indexer_url}/v2/transactions/{tx_id}")
            if resp.status_code == 200:
                raw_tx = resp.json().get("transaction")
                source = "indexer"
    except Exception:
        pass

    # 2. Fall back to Algod
    if not raw_tx:
        try:
            algod_client = AlgodClient("", cfg.algod_url)
            pending_info = algod_client.pending_transaction_info(tx_id)
            if pending_info and pending_info.get("confirmed-round", 0) > 0:
                raw_tx = pending_info
                source = "algod"
        except Exception:
            pass

    if not raw_tx:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disbursement transaction {tx_id} could not be located on {cfg.network.value} Algorand ledger.",
        )

    # Parse payments
    if source == "indexer":
        payments = parse_indexer_transaction(raw_tx, tx_id)
    else:
        payments = parse_algod_transaction(raw_tx, tx_id)

    if not payments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No asset transfer found in transaction {tx_id}.",
        )

    # Filter and validate matching payments
    eligible_payments: List[NormalizedPayment] = []
    rejection_reasons: List[str] = []

    for p in payments:
        # Check 1: Confirmed round
        if p.confirmed_round <= 0:
            rejection_reasons.append(f"{p.inner_transaction_path}: Unconfirmed transaction (round {p.confirmed_round})")
            continue

        # Check 2: Transferred asset matches configured asset
        if p.asset_id != cfg.asset_id:
            rejection_reasons.append(f"{p.inner_transaction_path}: Asset ID mismatch (got {p.asset_id}, expected {cfg.asset_id})")
            continue

        # Check 3: Sender is configured authorized treasury
        if p.sender != cfg.treasury_address:
            rejection_reasons.append(f"{p.inner_transaction_path}: Sender mismatch (got {p.sender}, expected authorized {cfg.treasury_address})")
            continue

        # Check 4: Receiver equals registered beneficiary
        if p.receiver != beneficiary_address:
            rejection_reasons.append(f"{p.inner_transaction_path}: Receiver mismatch (got {p.receiver}, expected {beneficiary_address})")
            continue

        # Check 5: Amount matches integer base units
        if p.amount_base_units != expected_base_units:
            rejection_reasons.append(f"{p.inner_transaction_path}: Amount mismatch (got {p.amount_base_units}, expected {expected_base_units})")
            continue

        # Check 6: Exact canonical grant binding
        if p.canonical_grant_binding != expected_canonical_note:
            rejection_reasons.append(
                f"{p.inner_transaction_path}: Grant binding mismatch (got '{p.canonical_grant_binding}', expected '{expected_canonical_note}')"
            )
            continue

        # Check 7: For contract payouts, verify expected application
        if cfg.application_id and p.inner_transaction_path != "root":
            if p.application_id and p.application_id != cfg.application_id:
                rejection_reasons.append(
                    f"{p.inner_transaction_path}: Originating app ID mismatch (got {p.application_id}, expected {cfg.application_id})"
                )
                continue

        # Check 8: No unexpected clawback, rekey, or close-to behavior
        if p.rekey_to is not None:
            rejection_reasons.append(f"{p.inner_transaction_path}: Unexpected rekey field present ({p.rekey_to})")
            continue
        if p.close_to is not None:
            rejection_reasons.append(f"{p.inner_transaction_path}: Unexpected close-to field present ({p.close_to})")
            continue
        if p.clawback is not None:
            rejection_reasons.append(f"{p.inner_transaction_path}: Unexpected clawback sender present ({p.clawback})")
            continue

        eligible_payments.append(p)

    # Check 10: Exactly one eligible payment identified
    if len(eligible_payments) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disbursement transaction {tx_id} failed verification: {'; '.join(rejection_reasons)}",
        )

    if len(eligible_payments) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ambiguous disbursement: Multiple eligible asset transfers ({len(eligible_payments)}) found in transaction {tx_id}.",
        )

    return eligible_payments[0]
