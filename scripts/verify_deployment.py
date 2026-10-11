"""Reproducible smart contract bytecode and deployment verification script for Qmoosa Equality.

Audits live on-chain Algorand applications against reproducibly compiled source bytecode.
Strictly requires an exact byte-for-byte match of both the approval-program and clear-state-program.
A schema match alone is explicitly rejected.
"""
import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Dict, Any, Tuple

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from algosdk.v2client.algod import AlgodClient
from contracts.hardened_treasury_app import compile_hardened_teal
from backend.settlement import COMPROMISED_ADMIN_ADDR, GENESIS_HASHES, AlgorandNetwork


def verify_application_deployment(
    app_id: int,
    network_str: str = "testnet",
    expected_admin: str = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Compare deployed on-chain bytecode against compiled source bytecode."""
    net = AlgorandNetwork(network_str.lower().strip())
    algod_url = "https://mainnet-api.algonode.cloud" if net == AlgorandNetwork.MAINNET else "https://testnet-api.algonode.cloud"
    client = AlgodClient("", algod_url)

    # 1. Reproducibly compile source
    app_teal, clear_teal = compile_hardened_teal()
    compiled_app = client.compile(app_teal)
    compiled_clear = client.compile(clear_teal)

    expected_app_bytes = base64.b64decode(compiled_app["result"])
    expected_clear_bytes = base64.b64decode(compiled_clear["result"])
    expected_app_hash = compiled_app["hash"]
    expected_clear_hash = compiled_clear["hash"]

    # 2. Query live on-chain application
    try:
        app_info = client.application_info(app_id)
    except Exception as e:
        return False, {
            "status": "NOT_FOUND",
            "error": f"Failed to retrieve Application #{app_id} from {net.value} Algorand node: {e}",
            "expected_approval_hash": expected_app_hash,
            "expected_clear_hash": expected_clear_hash,
        }

    params = app_info.get("params", {})
    deployed_app_b64 = params.get("approval-program", "")
    deployed_clear_b64 = params.get("clear-state-program", "")
    deployed_app_bytes = base64.b64decode(deployed_app_b64) if deployed_app_b64 else b""
    deployed_clear_bytes = base64.b64decode(deployed_clear_b64) if deployed_clear_b64 else b""

    # Calculate deployed hashes via logic.address
    from algosdk import logic
    deployed_app_hash = logic.address(deployed_app_bytes) if deployed_app_bytes else "NONE"
    deployed_clear_hash = logic.address(deployed_clear_bytes) if deployed_clear_bytes else "NONE"

    creator = params.get("creator", "")
    schema = params.get("global-state-schema", {})
    global_state = params.get("global-state", [])

    # Extract admin from global state
    current_admin = None
    for item in global_state:
        key_b64 = item.get("key", "")
        try:
            key_name = base64.b64decode(key_b64).decode("utf-8")
        except Exception:
            key_name = ""
        if key_name == "admin":
            from algosdk.encoding import encode_address
            val_bytes = base64.b64decode(item.get("value", {}).get("bytes", ""))
            if len(val_bytes) == 32:
                current_admin = encode_address(val_bytes)
            break

    # 3. Exact Bytecode Evaluation
    approval_matches = (deployed_app_bytes == expected_app_bytes)
    clear_matches = (deployed_clear_bytes == expected_clear_bytes)
    is_exact_bytecode_match = approval_matches and clear_matches

    # 4. Authority and Safety Checks
    admin_compromised = (current_admin == COMPROMISED_ADMIN_ADDR or creator == COMPROMISED_ADMIN_ADDR)
    admin_matches_expected = True
    if expected_admin:
        admin_matches_expected = (current_admin == expected_admin)

    is_verified = (
        is_exact_bytecode_match
        and not admin_compromised
        and admin_matches_expected
    )

    report = {
        "network": net.value,
        "application_id": app_id,
        "is_exact_bytecode_match": is_exact_bytecode_match,
        "approval_matches": approval_matches,
        "clear_matches": clear_matches,
        "expected_approval_hash": expected_app_hash,
        "deployed_approval_hash": deployed_app_hash,
        "expected_approval_bytes_len": len(expected_app_bytes),
        "deployed_approval_bytes_len": len(deployed_app_bytes),
        "creator": creator,
        "current_admin": current_admin,
        "admin_compromised": admin_compromised,
        "schema": schema,
        "verified_v2_deployment": is_verified,
    }

    return is_verified, report


def main():
    parser = argparse.ArgumentParser(description="Verify Algorand Application deployment bytecode")
    parser.add_argument("--app-id", type=int, required=True, help="Algorand Application ID")
    parser.add_argument("--network", type=str, default="testnet", help="Algorand network (mainnet/testnet)")
    parser.add_argument("--expected-admin", type=str, default=None, help="Expected safe administrative address")
    args = parser.parse_args()

    verified, report = verify_application_deployment(args.app_id, args.network, args.expected_admin)
    print(json.dumps(report, indent=2))
    if not verified:
        print("\n[VERIFICATION FAILED] Application does NOT match reviewed Hardened Treasury v2 bytecode or has compromised authority.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n[VERIFICATION PASSED] On-chain application bytecode exactly matches compiled Hardened Treasury v2.", file=sys.stdout)
        sys.exit(0)


if __name__ == "__main__":
    main()
