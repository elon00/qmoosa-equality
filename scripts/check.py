"""Comprehensive Verification Engine for Qmoosa Equality.
Enforces the Reality Gate: executes component tests, contract tests, API tests,
live on-chain ledger queries, and security incident gates.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from algosdk.v2client.algod import AlgodClient

root = Path(__file__).resolve().parents[1]

COMPROMISED_ADMIN_ADDR = "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM"

def run_test_module(module_path: str, name: str) -> bool:
    print(f"\n--- [RUNNING] {name} ({module_path}) ---")
    res = subprocess.run([sys.executable, "-m", "unittest", module_path, "-v"], cwd=root)
    if res.returncode == 0:
        print(f"[PASS] {name} passed.")
        return True
    else:
        print(f"[FAIL] {name} failed with exit code {res.returncode}.", file=sys.stderr)
        return False

def verify_onchain_state(status_data: dict) -> bool:
    print("\n--- [VERIFYING] Live Algorand Node State ---")
    identifiers = status_data.get("identifiers", {})
    mainnet_id = status_data.get("mainnet_asset_id") or identifiers.get("mainnet_asset_id")
    testnet_id = status_data.get("asset_id") or identifiers.get("testnet_asset_id")
    app_id = status_data.get("application_id") or identifiers.get("testnet_application_id")

    if not mainnet_id or not testnet_id or not app_id:
        print("[FAIL] Missing on-chain identifiers in STATUS.json", file=sys.stderr)
        return False

    try:
        mc = AlgodClient("", "https://mainnet-api.algonode.cloud")
        m_info = mc.asset_info(mainnet_id)
        m_params = m_info["params"]
        assert m_params["unit-name"] == "QEQ", "Mainnet ticker mismatch"
        assert m_params["total"] == 1_000_000_000_000, "Mainnet total mismatch"
        print(f"[PASS] Mainnet Asset #{mainnet_id} (QEQ) verified on-chain.")

        tc = AlgodClient("", "https://testnet-api.algonode.cloud")
        t_info = tc.asset_info(testnet_id)
        assert t_info["params"]["unit-name"] == "QEQ", "Testnet ticker mismatch"
        print(f"[PASS] Testnet Asset #{testnet_id} (QEQ) verified on-chain.")

        app_info = tc.application_info(app_id)
        assert app_info["id"] == app_id, "Application ID mismatch"
        print(f"[PASS] Testnet Treasury App #{app_id} verified on-chain.")
        return True
    except Exception as e:
        print(f"[FAIL] On-chain query failed: {e}", file=sys.stderr)
        return False

def check_security_incident_gate() -> bool:
    print("\n--- [VERIFYING] Security Incident Authority Gate ---")
    # Verify whether Mainnet Asset Manager has been rotated away from the compromised address
    try:
        mc = AlgodClient("", "https://mainnet-api.algonode.cloud")
        m_info = mc.asset_info(3737683297)
        manager = m_info["params"].get("manager")
        if manager == COMPROMISED_ADMIN_ADDR:
            print("[BLOCKER] Mainnet Asset Manager is still the compromised address TPLMGGFN...", file=sys.stderr)
            print("          Production release is strictly BLOCKED until on-chain rotation is completed.", file=sys.stderr)
            print("          See docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md for rotation runbook.", file=sys.stderr)
            return False
        else:
            print(f"[PASS] Mainnet Asset Manager successfully rotated to: {manager}")
            return True
    except Exception as e:
        print(f"[FAIL] Failed to verify manager status: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Reality Gate Comprehensive Verification Engine")
    parser.add_argument("--components", action="store_true", help="Run core unit & crypto tests")
    parser.add_argument("--contracts", action="store_true", help="Run smart contract compilation & security tests")
    parser.add_argument("--api", action="store_true", help="Run database & API integration tests")
    parser.add_argument("--onchain", action="store_true", help="Verify live on-chain ledger state")
    parser.add_argument("--full-audit", action="store_true", help="Run complete audit suite")
    parser.add_argument("--release", action="store_true", help="Run production release certification gate")
    args = parser.parse_args()

    # Default to running all test suites if no specific flags
    run_all = args.full_audit or (not args.components and not args.contracts and not args.api and not args.onchain and not args.release)

    failures = 0

    if args.components or run_all:
        if not run_test_module("tests/test_core.py", "Core & Economic Tests"):
            failures += 1
        if not run_test_module("tests/test_crypto.py", "ML-DSA-65 Cryptographic Tests"):
            failures += 1

    if args.contracts or run_all:
        if not run_test_module("tests/test_contracts.py", "Smart Contract Security Tests"):
            failures += 1

    if args.api or run_all:
        if not run_test_module("tests/test_api.py", "Hardened Backend & DB Tests"):
            failures += 1

    status_file = root / "STATUS.json"
    status_data = json.loads(status_file.read_text()) if status_file.exists() else {}

    if args.onchain or run_all:
        if not verify_onchain_state(status_data):
            failures += 1

    if failures > 0:
        print(f"\n[SUMMARY] Verification finished with {failures} failure(s).", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 65)
    print("[PASS] ALL TECHNICAL TEST SUITES & LEDGER CHECKS SUCCESSFUL")
    print("=" * 65)

    if args.release:
        print("\n" + "*" * 65)
        print("CHECKING PRODUCTION RELEASE READINESS")
        print("*" * 65)
        is_secured = check_security_incident_gate()
        if not is_secured:
            print("\n[CRITICAL RELEASE GATE HALT]")
            print("Release certification FAILS CLOSED (exit code 2).")
            print("Reason: Key Exposure Incident IR-2026-001 requires administrative authority rotation.")
            sys.exit(2)
        else:
            print("[PASS] Administrative authority rotation verified on-chain.")
            print("[CERTIFIED] Release readiness confirmed.")
            sys.exit(0)

if __name__ == "__main__":
    main()
