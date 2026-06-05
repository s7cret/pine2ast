#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    -h|--help) echo "Usage: ./scripts/install.sh [--dev]"; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$ROOT"
echo "== Pine2AST installer =="
python --version
python -m pip --version
python - <<'PY'
import tomllib
from pathlib import Path
p = tomllib.loads(Path("pyproject.toml").read_text())["project"]
print(f"name: {p['name']}")
print(f"version: {p['version']}")
print("dependencies:")
for dep in p.get("dependencies", []):
    print(f"  - {dep}")
print("dev dependencies:")
for dep in p.get("optional-dependencies", {}).get("dev", []):
    print(f"  - {dep}")
PY
python -m pip install --upgrade pip
if [[ "$DEV" == "1" ]]; then
  python -m pip install -e ".[dev]"
else
  python -m pip install -e .
fi
python -m pip list
