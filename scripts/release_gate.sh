#!/usr/bin/env bash
set -euo pipefail

ALLOW_PENDING_ORACLE=0
if [[ "${1:-}" == "--allow-pending-oracle" ]]; then
  ALLOW_PENDING_ORACLE=1
  shift
fi
if [[ $# -ne 0 ]]; then
  echo "usage: bash scripts/release_gate.sh [--allow-pending-oracle]" >&2
  exit 64
fi

PYTHON="${PYTHON:-.venv/bin/python}"
OUT_DIR="${PINE2AST_RELEASE_GATE_OUT_DIR:-.release_gate_reports/final}"
mkdir -p "$OUT_DIR"

run_log() {
  local log="$1"
  shift
  "$@" >"$OUT_DIR/$log" 2>&1
}

run_log RUFF_FINAL.log "$PYTHON" -m ruff check .
run_log BLACK_FINAL.log "$PYTHON" -m black --check .
run_log MYPY_FINAL.log "$PYTHON" -m mypy pine2ast
run_log SMOKE_IMPORT_PARSE_FINAL.log bash scripts/smoke_import_parse.sh
# Keep release verification hermetic: stale/corrupt coverage DBs from earlier
# interrupted runs must not poison the gate, and coverage XML must not rewrite
# tracked repository files during verification.
rm -f .coverage
run_log TEST_RUN_FINAL.log "$PYTHON" -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml:"$OUT_DIR/coverage.xml"
run_log QUALITY_GATE_FINAL.log "$PYTHON" -m pine2ast quality-gate tests/fixtures/real_world --json "$OUT_DIR/QUALITY_GATE_FINAL.json"
run_log BUILTIN_COVERAGE_FINAL.log "$PYTHON" -m pine2ast builtin-coverage --json "$OUT_DIR/BUILTIN_COVERAGE_FINAL.json"
run_log OFFICIAL_REFERENCE_V5_GATE_FINAL.log "$PYTHON" -m pine2ast official-reference gate --official-json pine2ast/reference_catalog/official_pine_v5_reference_index.json --baseline pine2ast/reference_catalog/official_pine_v5_gap_baseline.json --json "$OUT_DIR/OFFICIAL_REFERENCE_V5_GATE_FINAL.json"
run_log OFFICIAL_REFERENCE_V6_GATE_FINAL.log "$PYTHON" -m pine2ast official-reference gate --official-json pine2ast/reference_catalog/official_pine_v6_reference_index.json --baseline pine2ast/reference_catalog/official_pine_v6_gap_baseline.json --json "$OUT_DIR/OFFICIAL_REFERENCE_V6_GATE_FINAL.json"

if [[ "$ALLOW_PENDING_ORACLE" -eq 1 ]]; then
  run_log COMPILE_ORACLE_FINAL.log "$PYTHON" tools/compile_oracle_report.py --path tests/fixtures/compile_oracle --json "$OUT_DIR/COMPILE_ORACLE_FINAL.json" --allow-pending --pending-release-suffix oracle_expansion_pending
else
  run_log COMPILE_ORACLE_FINAL.log "$PYTHON" tools/compile_oracle_report.py --path tests/fixtures/compile_oracle --json "$OUT_DIR/COMPILE_ORACLE_FINAL.json"
fi

cat >"$OUT_DIR/QUALITY_GATE_FINAL.json.tmp" <<'JSON'
{
  "release_gate": "passed",
  "logs_dir": "reports/final",
  "oracle_mode": "pending_allowed_for_rc"
}
JSON
# Preserve the CLI quality-gate payload; the tmp file is only a smoke marker for shell debugging.
rm -f "$OUT_DIR/QUALITY_GATE_FINAL.json.tmp"
