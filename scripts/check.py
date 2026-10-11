"""One-command Reality Gate check with live on-chain cryptographic and ledger verification."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from algosdk.v2client.algod import AlgodClient

parser = argparse.ArgumentParser()
parser.add_argument('--release', action='store_true')
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]

# 1. Run all unit tests (ML-DSA-65, integer tokenomics, HTTPS)
print("=" * 60)
print("1. RUNNING COMPONENT TEST SUITE")
print("=" * 60)
result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=root)
if result.returncode:
    print("FAILED: Component tests failed.", file=sys.stderr)
    sys.exit(result.returncode)

# 2. Display STATUS.json
status_file = root / 'STATUS.json'
status = json.loads(status_file.read_text())
print("\n" + "=" * 60)
print("2. STATUS AND EVIDENCE MANIFEST")
print("=" * 60)
print(json.dumps(status, indent=2))

# 3. Live On-Chain Reality Gate Verification for Release
if args.release:
    print("\n" + "=" * 60)
    print("3. VERIFYING LIVE ON-CHAIN MAINNET & TESTNET LEDGER PROOFS")
    print("=" * 60)

    mainnet_id = status.get("mainnet_asset_id")
    testnet_id = status.get("asset_id")
    app_id = status.get("application_id")

    if not mainnet_id or not testnet_id or not app_id:
        print("BLOCKED: Incomplete on-chain proofs in STATUS.json", file=sys.stderr)
        sys.exit(2)

    try:
        # Check Mainnet
        mainnet_client = AlgodClient("", "https://mainnet-api.algonode.cloud")
        m_info = mainnet_client.asset_info(mainnet_id)
        m_params = m_info["params"]
        assert m_params["unit-name"] == "QEQ", "Mainnet unit-name mismatch"
        assert m_params["total"] == 1_000_000_000_000, "Mainnet total mismatch"
        print(f"[PASS] Mainnet Proof Verified: ASA #{mainnet_id} (QEQ) is live and confirmed.")

        # Check Testnet
        testnet_client = AlgodClient("", "https://testnet-api.algonode.cloud")
        t_info = testnet_client.asset_info(testnet_id)
        assert t_info["params"]["unit-name"] == "QEQ", "Testnet unit-name mismatch"
        print(f"[PASS] Testnet Proof Verified: ASA #{testnet_id} (QEQ) is live and confirmed.")

        # Check Treasury Application
        app_info = testnet_client.application_info(app_id)
        assert app_info["id"] == app_id, "Application ID mismatch"
        print(f"[PASS] Treasury Contract Verified: App #{app_id} is live and confirmed on-chain.")

        print("\n" + "*" * 60)
        print("REALITY GATE PRODUCTION RELEASE: ALL ON-CHAIN CRITERIA SATISFIED")
        print("*" * 60)
    except Exception as e:
        print(f"BLOCKED: Live on-chain verification failed: {e}", file=sys.stderr)
        sys.exit(2)
