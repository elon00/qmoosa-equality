"""Real Algorand Testnet ASA Deployment Script under Reality Gate.
Strictly zero-simulation, zero-mock. Fails closed if account lacks real Testnet ALGO.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from algosdk import account, encoding, mnemonic, transaction
from algosdk.v2client.algod import AlgodClient

DEFAULT_ALGOD_URL = "https://testnet-api.algonode.cloud"

def deploy(sender_mnemonic=None, algod_url=DEFAULT_ALGOD_URL, total=1_000_000_000_000, decimals=6, unit="QEQ", name="Qmoosa Equality"):
    if not sender_mnemonic:
        sender_mnemonic = os.getenv("ALGORAND_MNEMONIC", "").strip()

    if not sender_mnemonic:
        print("REALITY GATE ERROR: No Algorand mnemonic provided.", file=sys.stderr)
        print("   Set the ALGORAND_MNEMONIC environment variable or pass --mnemonic.", file=sys.stderr)
        sys.exit(1)

    try:
        private_key = mnemonic.to_private_key(sender_mnemonic)
        sender_addr = account.address_from_private_key(private_key)
    except Exception as e:
        print(f"REALITY GATE ERROR: Invalid mnemonic: {e}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("REALITY GATE: Algorand Testnet Deployment Check")
    print(f"   Sender Address: {sender_addr}")
    print(f"   Algod Node URL: {algod_url}")
    print(f"   Asset Name:     {name} ({unit})")
    print(f"   Total Supply:   {total} (Decimals: {decimals})")
    print("=" * 60)

    client = AlgodClient("", algod_url)

    # 1. Real on-chain balance verification
    try:
        acc_info = client.account_info(sender_addr)
        balance_micro = acc_info.get("amount", 0)
        balance_algo = balance_micro / 1_000_000
        print(f"   Real On-Chain Balance: {balance_algo:.6f} ALGO")
    except Exception as e:
        print(f"REALITY GATE ERROR: Failed to query account info: {e}", file=sys.stderr)
        sys.exit(1)

    MIN_REQUIRED_MICRO = 200_000  # 0.2 ALGO for ASA MBR + fee
    if balance_micro < MIN_REQUIRED_MICRO:
        print("\n" + "!" * 60)
        print("REALITY GATE FAIL-CLOSED REJECTION:")
        print(f"   Account balance is {balance_algo:.6f} ALGO (minimum {MIN_REQUIRED_MICRO/1e6:.1f} ALGO required).")
        print("   ZERO SIMULATION POLICY: Fake or simulated deployments are strictly prohibited.")
        print("\n   To fund this real testnet address for free:")
        print("   1. Open the official Algorand Testnet Dispenser: https://lora.algokit.io/testnet/fund")
        print(f"   2. Paste your address: {sender_addr}")
        print("   3. Click 'Dispense' to receive 10 Testnet ALGO.")
        print("   4. Re-run this deployment script.")
        print("!" * 60 + "\n")
        sys.exit(2)

    # 2. Fetch live suggested network params
    params = client.suggested_params()
    if params.gen != "testnet-v1.0":
        raise RuntimeError(f"Reality Gate check failed: Expected testnet-v1.0, got {params.gen}")

    print(f"   Network Genesis ID: {params.gen}")
    print(f"   Current Round:      {params.first}")
    print(f"   Suggested Fee:      {params.fee / 1e6:.6f} ALGO")

    # 3. Create real AssetConfigTxn
    txn = transaction.AssetCreateTxn(
        sender=sender_addr,
        sp=params,
        total=total,
        decimals=decimals,
        default_frozen=False,
        unit_name=unit,
        asset_name=name,
        manager=sender_addr,
        reserve=sender_addr,
        freeze=None,
        clawback=None,
        url="https://github.com/elon00/qmoosa-equality"
    )

    # 4. Sign transaction cryptographically
    signed_txn = txn.sign(private_key)

    # 5. Broadcast to real Algorand Testnet
    print("\nBroadcasting signed transaction to Algorand Testnet...")
    tx_id = client.send_transaction(signed_txn)
    print(f"   Transaction ID: {tx_id}")

    # 6. Wait for real on-chain confirmation
    print("Waiting for on-chain block confirmation...")
    confirmed_txn = transaction.wait_for_confirmation(client, tx_id, 4)
    asset_id = confirmed_txn["asset-index"]
    confirmed_round = confirmed_txn.get("confirmed-round")

    print("\n" + "=" * 60)
    print("REALITY GATE VERIFIED: ASA DEPLOYED ON TESTNET")
    print("=" * 60)
    print(f"   Asset ID:        {asset_id}")
    print(f"   Asset Name:      {name} ({unit})")
    print(f"   Confirmed Round: {confirmed_round}")
    print(f"   Transaction ID:  {tx_id}")
    print(f"   Explorer URL:    https://lora.algokit.io/testnet/asset/{asset_id}")
    print(f"   Tx Explorer URL: https://lora.algokit.io/testnet/transaction/{tx_id}")
    print("=" * 60)

    # Update STATUS.json if present
    root = Path(__file__).resolve().parents[1]
    status_file = root / "STATUS.json"
    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text())
            status_data["stage"] = "testnet-deployed"
            status_data["deployed"] = True
            status_data["asset_id"] = asset_id
            status_file.write_text(json.dumps(status_data, indent=2))
            print("   Updated STATUS.json with real on-chain asset_id.")
        except Exception as e:
            print(f"   Warning updating STATUS.json: {e}")

    return asset_id, tx_id

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy QEQ ASA to Algorand Testnet under Reality Gate")
    parser.add_argument("--mnemonic", help="25-word sender mnemonic (or via ALGORAND_MNEMONIC env)")
    parser.add_argument("--total", type=int, default=1_000_000_000_000, help="Total supply (default: 1,000,000,000,000 base units = 1M QEQ)")
    parser.add_argument("--decimals", type=int, default=6, help="Decimals (default: 6)")
    parser.add_argument("--algod", default=DEFAULT_ALGOD_URL, help="Algod node URL (default: AlgoNode testnet)")
    args = parser.parse_args()
    deploy(sender_mnemonic=args.mnemonic, algod_url=args.algod, total=args.total, decimals=args.decimals)
