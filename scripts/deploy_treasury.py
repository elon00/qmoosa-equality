"""Deploy Community Treasury & Escrow Smart Contract to Algorand Testnet."""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from algosdk import account, mnemonic, transaction
from algosdk.transaction import ApplicationCreateTxn, OnComplete, StateSchema
from algosdk.v2client.algod import AlgodClient
from contracts.treasury_app import compile_to_teal

DEFAULT_ALGOD_URL = "https://testnet-api.algonode.cloud"

def deploy_treasury(sender_mnemonic=None, asset_id=774088414, algod_url=DEFAULT_ALGOD_URL):
    if not sender_mnemonic:
        sender_mnemonic = os.getenv("ALGORAND_MNEMONIC", "").strip()

    if not sender_mnemonic:
        print("REALITY GATE ERROR: No Algorand mnemonic provided.", file=sys.stderr)
        sys.exit(1)

    private_key = mnemonic.to_private_key(sender_mnemonic)
    sender_addr = account.address_from_private_key(private_key)

    print("=" * 60)
    print("REALITY GATE: Community Treasury Contract Deployment")
    print(f"   Sender Address: {sender_addr}")
    print(f"   Target Asset ID: {asset_id}")
    print("=" * 60)

    client = AlgodClient("", algod_url)

    # Compile TEAL programs
    approval_teal, clear_teal = compile_to_teal()
    compiled_approval = client.compile(approval_teal)
    compiled_clear = client.compile(clear_teal)

    approval_bytes = base64.b64decode(compiled_approval["result"])
    clear_bytes = base64.b64decode(compiled_clear["result"])

    params = client.suggested_params()

    # Schema:
    # Global: admin (bytes), asset_id (uint), total_disbursed (uint), dispute_period (uint), paused (uint)
    # Total Global: 4 uints, 1 byte slice
    # Local: pending_grant (uint), grant_unlock_round (uint)
    # Total Local: 2 uints, 0 byte slices
    global_schema = StateSchema(num_uints=4, num_byte_slices=1)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)

    app_args = [asset_id.to_bytes(8, "big")]

    txn = ApplicationCreateTxn(
        sender=sender_addr,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_bytes,
        clear_program=clear_bytes,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
    )

    signed_txn = txn.sign(private_key)
    print("\nBroadcasting Application Creation transaction...")
    tx_id = client.send_transaction(signed_txn)
    print(f"   Transaction ID: {tx_id}")

    print("Waiting for on-chain block confirmation...")
    confirmed_txn = transaction.wait_for_confirmation(client, tx_id, 4)
    app_id = confirmed_txn["application-index"]
    from algosdk import logic
    app_addr = logic.get_application_address(app_id)

    print("\n" + "=" * 60)
    print("REALITY GATE VERIFIED: TREASURY CONTRACT DEPLOYED")
    print("=" * 60)
    print(f"   Application ID:      {app_id}")
    print(f"   Application Address: {app_addr}")
    print(f"   Confirmed Round:     {confirmed_txn.get('confirmed-round')}")
    print(f"   Transaction ID:      {tx_id}")
    print(f"   App Explorer URL:    https://lora.algokit.io/testnet/application/{app_id}")
    print("=" * 60)

    # Update STATUS.json
    status_file = root / "STATUS.json"
    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text())
            status_data["application_id"] = app_id
            status_data["application_address"] = app_addr
            # Remove blocker for grant treasury
            status_data["blockers"] = [
                b for b in status_data.get("blockers", [])
                if "No on-chain grant treasury" not in b
            ]
            status_file.write_text(json.dumps(status_data, indent=2))
            print("   Updated STATUS.json with real on-chain application_id.")
        except Exception as e:
            print(f"   Warning updating STATUS.json: {e}")

    return app_id, app_addr

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mnemonic", help="25-word mnemonic")
    parser.add_argument("--asset-id", type=int, default=774088414)
    args = parser.parse_args()
    deploy_treasury(sender_mnemonic=args.mnemonic, asset_id=args.asset_id)
