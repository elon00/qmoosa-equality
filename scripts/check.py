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
    print("\n--- [VERIFYING] Security Incident Authority Gate (IR-2026-001) ---")
    mc = AlgodClient("", "https://mainnet-api.algonode.cloud")
    tc = AlgodClient("", "https://testnet-api.algonode.cloud")

    blockers = []

    # 1. Mainnet ASA 3737683297 Manager and Reserve
    try:
        m_info = mc.asset_info(3737683297)
        params = m_info.get("params", {})
        m_manager = params.get("manager")
        m_reserve = params.get("reserve")

        if m_manager == COMPROMISED_ADMIN_ADDR:
            blockers.append("Mainnet ASA 3737683297 manager is still compromised key TPLMGGFN...")
            print("  [BLOCKED] Mainnet ASA Manager: Still compromised address TPLMGGFN...", file=sys.stderr)
        else:
            print(f"  [PASS] Mainnet ASA Manager rotated to: {m_manager}")

        if m_reserve == COMPROMISED_ADMIN_ADDR:
            blockers.append("Mainnet ASA 3737683297 reserve is still compromised key TPLMGGFN...")
            print("  [BLOCKED] Mainnet ASA Reserve: Still compromised address TPLMGGFN...", file=sys.stderr)
        else:
            print(f"  [PASS] Mainnet ASA Reserve rotated to: {m_reserve}")
    except Exception as e:
        blockers.append(f"Failed to query Mainnet ASA: {e}")
        print(f"  [ERROR] Mainnet ASA query failed: {e}", file=sys.stderr)

    # 2. Testnet ASA 774088414 Manager and Reserve
    try:
        t_info = tc.asset_info(774088414)
        t_params = t_info.get("params", {})
        t_manager = t_params.get("manager")
        t_reserve = t_params.get("reserve")

        if t_manager == COMPROMISED_ADMIN_ADDR:
            blockers.append("Testnet ASA 774088414 manager is still compromised key TPLMGGFN...")
            print("  [BLOCKED] Testnet ASA Manager: Still compromised address TPLMGGFN...", file=sys.stderr)
        else:
            print(f"  [PASS] Testnet ASA Manager rotated to: {t_manager}")

        if t_reserve == COMPROMISED_ADMIN_ADDR:
            blockers.append("Testnet ASA 774088414 reserve is still compromised key TPLMGGFN...")
            print("  [BLOCKED] Testnet ASA Reserve: Still compromised address TPLMGGFN...", file=sys.stderr)
        else:
            print(f"  [PASS] Testnet ASA Reserve rotated to: {t_reserve}")
    except Exception as e:
        blockers.append(f"Failed to query Testnet ASA: {e}")
        print(f"  [ERROR] Testnet ASA query failed: {e}", file=sys.stderr)

    # 3. Mainnet Compromised Account Rekeying & Balance Evacuation
    try:
        acc_info = mc.account_info(COMPROMISED_ADMIN_ADDR)
        auth_addr = acc_info.get("auth-addr")
        algo_balance = acc_info.get("amount", 0) / 1e6

        if not auth_addr:
            blockers.append("Compromised Mainnet account is NOT rekeyed (auth-addr absent). Anyone with the exposed seed can sign transactions!")
            print("  [BLOCKED] Mainnet Account Rekey: Account NOT rekeyed (auth-addr is absent).", file=sys.stderr)
        else:
            print(f"  [PASS] Mainnet Account Rekeyed to: {auth_addr}")

        if algo_balance > 1.0:
            blockers.append(f"Compromised Mainnet account still holds {algo_balance:.2f} ALGO. Funds must be evacuated!")
            print(f"  [BLOCKED] Mainnet Account Balance: Holds {algo_balance:.4f} ALGO (not evacuated).", file=sys.stderr)
        else:
            print(f"  [PASS] Mainnet Account Balance: Evacuated ({algo_balance:.4f} ALGO remaining).")
    except Exception as e:
        blockers.append(f"Failed to query compromised account info: {e}")
        print(f"  [ERROR] Compromised account query failed: {e}", file=sys.stderr)

    # 4. Testnet Treasury Application Status
    try:
        app_info = tc.application_info(774088598)
        creator = app_info.get("params", {}).get("creator")
        if creator == COMPROMISED_ADMIN_ADDR:
            print("  [NOTE] Testnet Treasury App 774088598 is Treasury v1 prototype created by TPLMGGFN... Hardened Treasury v2 is compiled but not yet deployed.")
    except Exception as e:
        print(f"  [WARN] Failed to query testnet app: {e}", file=sys.stderr)

    if blockers:
        print("\n[SECURITY AUDIT SUMMARY] The following critical security blockers remain unresolved:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        print("\nProduction release remains strictly BLOCKED until on-chain rotation and rekeying are confirmed.", file=sys.stderr)
        print("See docs/INCIDENT_RESPONSE_KEY_EXPOSURE.md for owner-signed migration instructions.", file=sys.stderr)
        return False
    else:
        print("\n[ALL INCIDENT AUTHORITIES SECURED]")
        return True


def main():
    parser = argparse.ArgumentParser(description="Reality Gate Comprehensive Verification Engine")
    parser.add_argument("--components", action="store_true", help="Run core unit & crypto tests")
    parser.add_argument("--contracts", action="store_true", help="Run smart contract compilation & security tests")
    parser.add_argument("--api", action="store_true", help="Run database & API integration tests")
    parser.add_argument("--onchain", action="store_true", help="Verify live on-chain ledger state")
    parser.add_argument("--full-audit", action="store_true", help="Run complete audit suite")
    parser.add_argument("--release", action="store_true", help="Run production release certification gate")
    args = parser.parse_args()

    # Default to running all technical test suites if no specific subset or if running full-audit or release
    run_all = args.full_audit or args.release or (
        not args.components and not args.contracts and not args.api and not args.onchain
    )

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
