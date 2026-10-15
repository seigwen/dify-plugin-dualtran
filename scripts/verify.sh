#!/usr/bin/env bash
# One-command verification (plan 64 C3):
#   pytest suites → .difypkg package → artifact assertions.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt pytest
fi

echo "[verify] pytest …"
.venv/bin/python -m pytest tests/ -q

if [ ! -x tools/dify ]; then
  echo "[verify] the dify CLI is missing (download see docs/SUBMISSION.md)"
  exit 1
fi

echo "[verify] packaging …"
OUT="$(mktemp -d)/dualtran.difypkg"
./tools/dify plugin package . -o "$OUT" >/dev/null
LISTING="$(unzip -l "$OUT")"

echo "$LISTING" | grep -q "tools/dualtran.py" || { echo "[verify] FAIL: tool missing from the package"; exit 1; }
echo "$LISTING" | grep -q "provider/dualtran.yaml" || { echo "[verify] FAIL: provider missing"; exit 1; }
if echo "$LISTING" | grep -q "tools/dify"; then
  echo "[verify] FAIL: the dev CLI leaked into the package"; exit 1
fi
if echo "$LISTING" | grep -q "tests/"; then
  echo "[verify] FAIL: tests leaked into the package"; exit 1
fi

echo "[verify] PASS — $(echo "$LISTING" | tail -2 | head -1 | awk '{print $2}') files, package ok"
