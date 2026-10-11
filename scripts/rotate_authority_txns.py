"""Prepare unsigned administrative rotation and rekey transactions for Qmoosa Equality.
Strictly zero-private-key: generates unsigned msgpack payloads for owner-controlled wallet signing.
"""
import argparse
import sys
from pathlib import Path
from algosdk import encoding, transaction
from algosdk.v2client.algod import AlgodClient

COMPROMISED_ADDR = "TPLMGGFNG64LKOCKVB7ZMQH5AMSNMV4GLI7GCH4FY2XQEKSIGB77O6LCFM"
MAINNET_ASSET_ID = 3737683297
TESTNET_ASSET_ID = 774088414

def main():
    parser = argparse.ArgumentParser(description="Generate unsigned ASA Manager rotation or Account Rekey transactions.")
    parser.add_argument("--network", choices=["mainnet", "testnet"], required=True, help="Target network")
    parser.add_argument("--new-manager", help="Target secure uncompromised address for ASA manager and reserve")
    parser.add_argument("--rekey-to", help="Target secure address to rekey the account to (delegates all L1 authority)")
    parser.add_argument("--out", help="Output file path for unsigned transaction")
    args = parser.parse_args()

    if not args.new_manager and not args.rekey_to:
        parser.error("Must specify either --new-manager or --rekey-to")

    algod_url = "https://mainnet-api.algonode.cloud" if args.network == "mainnet" else "https://testnet-api.algonode.cloud"
    asset_id = MAINNET_ASSET_ID if args.network == "mainnet" else TESTNET_ASSET_ID
    client = AlgodClient("", algod_url)

    params = client.suggested_params()

    if args.rekey_to:
        if not encoding.is_valid_address(args.rekey_to):
            parser.error("Invalid --rekey-to Algorand address")
        out_file = args.out or f"rekey-{args.network}.unsigned"
        # 0-value payment transaction with rekey_to set
        txn = transaction.PaymentTxn(
            sender=COMPROMISED_ADDR,
            sp=params,
            receiver=COMPROMISED_ADDR,
            amt=0,
            rekey_to=args.rekey_to
        )
        transaction.write_to_file([txn], out_file)
        print("=" * 65)
        print("GENERATED UNSIGNED REKEY TRANSACTION")
        print("=" * 65)
        print(f"Network:      {args.network}")
        print(f"Account:      {COMPROMISED_ADDR}")
        print(f"Rekey Target: {args.rekey_to}")
        print(f"Output File:  {out_file}")
        print("\nSigning instructions:")
        print("1. Transfer this .unsigned file to your offline/hardware wallet.")
        print(f"2. Sign with {COMPROMISED_ADDR}.")
        print("3. Broadcast via Algorand CLI or web wallet.")

    elif args.new_manager:
        if not encoding.is_valid_address(args.new_manager):
            parser.error("Invalid --new-manager Algorand address")
        out_file = args.out or f"rotate-manager-{args.network}.unsigned"
        # AssetConfigTxn to reconfigure manager and reserve
        txn = transaction.AssetConfigTxn(
            sender=COMPROMISED_ADDR,
            sp=params,
            index=asset_id,
            manager=args.new_manager,
            reserve=args.new_manager,
            freeze=None,
            clawback=None,
            strict_empty_address_check=False
        )
        transaction.write_to_file([txn], out_file)
        print("=" * 65)
        print("GENERATED UNSIGNED ASA MANAGER ROTATION TRANSACTION")
        print("=" * 65)
        print(f"Network:      {args.network}")
        print(f"Asset ID:     {asset_id}")
        print(f"Current Admin:{COMPROMISED_ADDR}")
        print(f"New Manager:  {args.new_manager}")
        print(f"New Reserve:  {args.new_manager}")
        print(f"Output File:  {out_file}")
        print("\nSigning instructions:")
        print("1. Review parameters and sign with current manager key in your secure wallet.")
        print("2. Broadcast via live Algod node to finalize on-chain rotation.")

if __name__ == "__main__":
    main()
