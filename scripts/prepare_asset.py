"""Prepare an unsigned TESTNET ASA creation; never submits or holds keys."""
import argparse
from pathlib import Path
from algosdk import encoding, transaction
from algosdk.v2client.algod import AlgodClient

p = argparse.ArgumentParser()
p.add_argument('--sender', required=True)
p.add_argument('--total', type=int, required=True)
p.add_argument('--out', default='asset-testnet.unsigned')
a = p.parse_args()
if not encoding.is_valid_address(a.sender):
    p.error('valid Algorand sender required')
if not 0 < a.total <= 2**64 - 1:
    p.error('ASA total must be between 1 and uint64 maximum')
client = AlgodClient('', 'https://testnet-api.algonode.cloud')
params = client.suggested_params()
if params.gen != 'testnet-v1.0':
    raise RuntimeError('Wrong network')
txn = transaction.AssetCreateTxn(
    sender=a.sender, sp=params, total=a.total, decimals=6,
    default_frozen=False, unit_name='QEQ', asset_name='Qmoosa Equality',
    manager=a.sender, reserve=a.sender, freeze=None, clawback=None)
with Path(a.out).open('x') as f:
    f.write(encoding.msgpack_encode(txn))
print('Unsigned testnet transaction prepared. NOT deployed. Total is immutable.')
