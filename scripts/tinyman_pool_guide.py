"""Tinyman AMM Liquidity & Market-Making Specification for QEQ."""
import sys

MAINNET_ASSET_ID = 3737683297
TESTNET_ASSET_ID = 774088414

def main():
    print("=" * 65)
    print("📈 QMOOSA EQUALITY (QEQ) — DEX MARKET-MAKING SPECIFICATION")
    print("=" * 65)
    print(f"Mainnet Asset ID: {MAINNET_ASSET_ID}")
    print(f"Testnet Asset ID: {TESTNET_ASSET_ID}")
    print("\nTo establish the open decentralized trading market for QEQ:")
    print("1. Tinyman DEX Pool Creation:")
    print("   - Platform: Tinyman AMM (https://app.tinyman.org/)")
    print(f"   - Add Pool: ALGO (Asset ID 0) + QEQ (Asset ID {MAINNET_ASSET_ID})")
    print("   - Pool Fee Tier: 0.30% (Standard)")
    print("\n2. Initial Liquidity Bootstrap:")
    print("   - Deposit Initial QEQ from Reserve Address")
    print("   - Deposit matching ALGO from Deployer Address")
    print("   - Receive Pool LP Tokens (Proof of Reserve)")
    print("\n3. DEX Aggregators & Charting:")
    print(f"   - Vestige.fi: https://vestige.fi/asset/{MAINNET_ASSET_ID}")
    print(f"   - Tinyman App: https://app.tinyman.org/#/swap?asset_in=0&asset_out={MAINNET_ASSET_ID}")
    print("=" * 65)

if __name__ == "__main__":
    main()
