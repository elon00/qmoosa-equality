#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v gh >/dev/null || { echo 'Install GitHub CLI and run gh auth login'; exit 2; }
test "$(gh api user --jq .login)" = elon00 || { echo 'Expected elon00 account'; exit 2; }
python3 scripts/check.py
git init -b main
git add .
git commit -m 'Initial experimental equality network with explicit release blockers'
gh repo create elon00/qmoosa-equality --public --source=. --remote=origin --push
