#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python}"
CONTRACTS_WHEEL="${OPENPINE_CONTRACTS_WHEEL:-}"
PRODUCER_COMMIT="${OPENPINE_PRODUCER_COMMIT:-}"
if [[ -z "$CONTRACTS_WHEEL" || ! -f "$CONTRACTS_WHEEL" ]]; then
  echo "OPENPINE_CONTRACTS_WHEEL must name the exact local Contracts wheel" >&2
  exit 1
fi
if [[ ! "$PRODUCER_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "OPENPINE_PRODUCER_COMMIT must be an exact 40-character Git SHA" >&2
  exit 1
fi
WORK_DIR="${PINE2AST_WHEEL_SMOKE_DIR:-$(mktemp -d)}"
DIST_DIR="$WORK_DIR/dist"
VENV_DIR="$WORK_DIR/venv"
mkdir -p "$DIST_DIR"

"$PYTHON" -m pip wheel . --no-deps -w "$DIST_DIR" >/tmp/pine2ast_wheel_build.log 2>&1
shopt -s nullglob
wheels=("$DIST_DIR"/pine2ast-*.whl)
if (( ${#wheels[@]} != 1 )); then
  echo "expected exactly one Pine2AST wheel" >&2
  exit 1
fi
"$PYTHON" -m venv "$VENV_DIR"
env -u PYTHONPATH "$VENV_DIR/bin/python" -m pip install \
  "$CONTRACTS_WHEEL" "${wheels[0]}" --quiet
cd "$WORK_DIR"
env -u PYTHONPATH OPENPINE_PRODUCER_COMMIT="$PRODUCER_COMMIT" \
  "$VENV_DIR/bin/python" -I - <<'PY'
import json
import pathlib
import subprocess
import sys

import pine2ast
from pine2ast import ast_to_json, parse_code

path = pathlib.Path(pine2ast.__file__).resolve()
assert "site-packages" in path.parts, path
src = '''//@version=6
indicator("wheel smoke", overlay=true)
plot(close)
'''
result = parse_code(src)
if not result.ok or result.ast is None:
    raise SystemExit(f"parse failed: {result.diagnostics!r}")
if result.ast_artifact is None or result.frontend_artifact is None:
    raise SystemExit("immutable production artifacts missing")
payload = json.loads(ast_to_json(result.ast))
if payload.get("kind") != "Program":
    raise SystemExit(f"unexpected AST root: {payload.get('kind')!r}")
cli = subprocess.run(
    [sys.executable, "-m", "pine2ast", "contract-check", "--help"],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    check=False,
)
if cli.returncode != 0 or "contract-check" not in cli.stdout:
    raise SystemExit(cli.stdout)
print(f"wheel smoke ok pine2ast={pine2ast.__version__} path={path}")
PY
