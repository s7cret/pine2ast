#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" - <<'PY'
import json
import pine2ast
from pine2ast import ast_to_json, parse_code

src = '''//@version=6
indicator("smoke", overlay=true)
plot(close)
'''
result = parse_code(src)
if not result.ok or result.ast is None:
    raise SystemExit(f"parse failed: {result.diagnostics!r}")
payload = json.loads(ast_to_json(result.ast))
if payload.get("kind") != "Program":
    raise SystemExit(f"unexpected AST root: {payload.get('kind')!r}")
print(f"smoke ok pine2ast={pine2ast.__version__}")
PY
