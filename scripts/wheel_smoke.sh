#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python}"
WORK_DIR="${PINE2AST_WHEEL_SMOKE_DIR:-$(mktemp -d)}"
DIST_DIR="$WORK_DIR/dist"
VENV_DIR="$WORK_DIR/venv"
mkdir -p "$DIST_DIR"

"$PYTHON" -m pip wheel . --no-deps -w "$DIST_DIR" >/tmp/pine2ast_wheel_build.log 2>&1
"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --no-index --find-links "$DIST_DIR" pine2ast >/tmp/pine2ast_wheel_install.log 2>&1
"$VENV_DIR/bin/python" - <<'PY'
import json
import subprocess
import sys

import pine2ast
from pine2ast import ast_to_json, parse_code

src = '''//@version=6
indicator("wheel smoke", overlay=true)
plot(close)
'''
result = parse_code(src)
if not result.ok or result.ast is None:
    raise SystemExit(f"parse failed: {result.diagnostics!r}")
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
print(f"wheel smoke ok pine2ast={pine2ast.__version__}")
PY
