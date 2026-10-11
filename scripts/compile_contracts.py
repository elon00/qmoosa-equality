import base64
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from algosdk.v2client.algod import AlgodClient
from contracts.treasury_app import compile_to_teal

def main():
    print("Compiling PyTeal contracts to TEAL 8...")
    approval_teal, clear_teal = compile_to_teal()

    contracts_dir = Path(__file__).resolve().parents[1] / "contracts"
    approval_file = contracts_dir / "treasury_approval.teal"
    clear_file = contracts_dir / "treasury_clear.teal"

    approval_file.write_text(approval_teal)
    clear_file.write_text(clear_teal)
    print(f"Written: {approval_file}")
    print(f"Written: {clear_file}")

    # Verify against live Algod node
    client = AlgodClient("", "https://testnet-api.algonode.cloud")
    print("Verifying compilation on Algorand testnet Algod...")
    app_res = client.compile(approval_teal)
    clear_res = client.compile(clear_teal)

    print("Approval Hash:", app_res["hash"])
    print("Clear Hash:   ", clear_res["hash"])
    print("PyTeal Contracts compiled and verified successfully on-chain.")

if __name__ == "__main__":
    main()
