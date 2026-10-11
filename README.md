# Qmoosa Equality

An experimental Algorand economic-inclusion project for Moolnivasi, SC, ST,
OBC, minorities and underserved communities worldwide. An independent project
for economic inclusion; token issuance alone does not eliminate poverty.

**Status: source prototype. Not deployed to testnet or mainnet.**
Proposed repository: `elon00/qmoosa-equality`. Proposed ticker: `QEQ`.

## Run

Python 3.12 recommended:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/check.py
```

Windows: activate `.venv\Scripts\activate` instead.
`python scripts/check.py --release` intentionally exits 2 while release is blocked.
Passing component tests does not mean a deployment or financial system is safe.

## What exists

- Integer allocation and funded issuance-budget calculations with tests.
- Real off-chain ML-DSA-65 signature adapter and signature/tampering tests.
- HTTPS adapters for OpenAI-compatible chat providers and x402 discovery.
- Unsigned Algorand testnet ASA transaction preparation using the official SDK.
- GitHub component and failing release-readiness jobs.
- Publication script for an authenticated GitHub CLI account `elon00`.

## What does not exist yet

Grant/treasury smart contracts, unlimited issuance contract, end-user frontend,
multi-chain wallet signing, Conway runtime integration, x402 settlement,
production chatbot routing, independent security audit and live deployments.
See `STATUS.json`. No fake RPC responses, asset IDs or success manifests are supplied.

## Publish source

After installing GitHub CLI and authenticating as `elon00`, run:

```bash
bash scripts/publish_github.sh
```

This creates a PUBLIC repository and pushes source; it does not launch a coin.
It requires an available repository name and configured git author identity.
Review source before publishing. No private keys are needed for publishing.

## Prepare testnet asset transaction

```bash
python scripts/prepare_asset.py --sender YOUR_ALGORAND_ADDRESS --total 1000000000000
```

The example is one million tokens at six decimals, not a chosen economic supply.
The tool fetches real testnet parameters and creates an unsigned transaction.
A wallet must review and sign it separately. It does not broadcast transactions.
Standard ASA supply is fixed at creation; the unlimited-supply request remains unresolved.

## Security boundaries

Never paste wallet seeds into chat or put them in git. Application signatures
do not replace Algorand transaction signatures or make the blockchain PQ-safe.
ML-DSA implementation is not a claim of FIPS product validation.
AI must never receive custody or autonomously approve beneficiaries or funds.
No mainnet spending, contracts or assets have been created by this package.

See `docs/DESIGN.md` for tokenomics and remaining implementation requirements.
