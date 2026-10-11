"""One-command checks; deployment readiness deliberately fails closed."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--release', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=root)
if result.returncode:
    sys.exit(result.returncode)
status = json.loads((root / 'STATUS.json').read_text())
print(json.dumps(status, indent=2))
if args.release:
    print('BLOCKED: release requires independent integration, contract and chain evidence.')
    sys.exit(2)
