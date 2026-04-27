# Pine2AST Interpipe — v0.2.0 big-block milestone report

## Scope completed in v0.1.9

This iteration focused on production-facing semantic correctness and type propagation:

- Added explicit type compatibility checks for:
  - typed variable initializers;
  - reassignments and compound assignments;
  - UDT field default values;
  - function and method parameter defaults.
- Added loop range type validation for `for i = start to end by step`.
- Added switch semantic validation:
  - expressionless `switch` cases must be bool-like;
  - `switch expr` cases must be comparable with the switch expression type.
- Improved type inference for:
  - `request.security(..., expression)` and tuple security requests;
  - `map.get` / `m.get`;
  - `matrix.get`;
  - array first/last/pop/shift/get style calls.
- Expanded `builtins_v6.json` from 187 to 231 function entries.
- Expanded the real-world seed corpus from 80 to 100 Pine fixtures.
- Added v0.1.9 regression tests covering the new semantic rules and inference paths.

## Verification

Expected verification commands:

```bash
/usr/bin/python3 -S -m compileall -q pine2ast tests tools benchmarks
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -S -u tools/run_tests_no_pytest.py
python -m pine2ast validate-corpus tests/fixtures/real_world --json corpus.json
```

Verified in the build workspace:

```text
95 stdlib regression checks pass.
100 real-world seed corpus files parse with 0 ERROR/FATAL diagnostics.
```

## Remaining v1.1/v2 backlog

- Replace generated seed corpus with a larger manually curated real Pine corpus.
- Add more precise Pine-specific overload resolution for builtins with multiple signatures.
- Add optional external library resolver for imported libraries.
- Add AST2Python compatibility fixtures and roundtrip optimizer contracts.

## v0.2.0 big-block milestone

This iteration moves the package from v0.1.x hardening into a wider integration milestone:

- Added UDT member access validation with `P2A1605 UNKNOWN_FIELD`.
- Added UDT field reassignment type checks, so `p.y := "bad"` is diagnosed against the declared field type instead of treating the whole object as the target.
- Added optimizer/AST2Python-oriented extractors:
  - `extract_alertconditions()`
  - `extract_drawing_calls()`
  - `extract_dependencies()`
- Added `pine2ast inspect` CLI, producing a compact JSON payload with diagnostics, inputs, strategy calls, request calls, plots, alerts, drawings and dependency metadata.
- Expanded seeded real-world corpus from 100 to 150 `.pine` files.
- Added v0.2.0 regression tests for UDT fields, dependency extraction and CLI inspect.
- Replaced hard `os._exit()` exits in the stdlib-only runner and direct CLI entry path with normal `SystemExit`/`sys.exit` for friendlier agent execution.

Validation snapshot:

```text
python3 -S -m compileall -q pine2ast tests tools benchmarks
python3 -S -u tools/run_tests_no_pytest.py
100 passed

python -m pine2ast validate-corpus tests/fixtures/real_world --json corpus.json
150 files, 150 ok, 0 errors
```

## v0.2.1 — schema/diagnostics/semantic hardening block

Added in this block:

- `pine2ast.ast.schema.validate_ast_schema()` structural AST contract validator.
- `pine2ast schema-check <file> --json report.json` CLI command.
- `pine2ast.diagnostics.reports.summarize_diagnostics()` and `diagnostics-report` CLI command.
- `P2A1804 QUALIFIER_MISMATCH` semantic rule for explicit `const`/`simple` qualifiers initialized from stronger values.
- Binary operator type validation for numeric/string/bool/comparable operators.
- `tools/run_tests_no_pytest.py` avoids `Path.resolve()` to reduce hangs in symlink-heavy/agent filesystems.
- Real-world seed corpus expanded from 150 to 200 Pine fixtures.

Validation commands used for this package:

```bash
/usr/bin/python3 -S -m compileall -q pine2ast tests tools benchmarks
PYTHONPATH=. /usr/bin/python3 -S - <<'PY'
# stdlib-only unit execution used in the build container
PY
PYTHONPATH=. /usr/bin/python3 -S - <<'PY'
from pine2ast.corpus import validate_corpus
r = validate_corpus('tests/fixtures/real_world')
assert r['file_count'] == 200
assert r['ok_count'] == 200
assert r['error_count'] == 0
PY
```

Known limitation remains: this is still Pine2AST parser/semantic front-end hardening, not TradingView runtime parity or full external-library resolution.

## v0.2.2 — quality gate / collection semantics big-block

Added in this block:

- Version bump to `0.2.2`.
- Stronger generic assignability for `array<T>`, `map<K,V>` and `matrix<T>` instead of accepting every collection as compatible.
- New diagnostic `P2A1805 COLLECTION_ELEMENT_TYPE`.
- Collection mutation validation for:
  - `array.push`, `array.set`, `array.unshift`;
  - method forms like `values.push(x)` / `values.set(i, x)`;
  - `map.put` key/value typing;
  - `matrix.set` value typing;
  - generic constructors such as `array.new<float>(size, initial)` and `matrix.new<float>(rows, cols, initial)`.
- `pine2ast.diagnostics.reports.diff_diagnostic_reports()` and CLI command `pine2ast diagnostics-diff current.json baseline.json` for stable CI baselines by diagnostic code.
- `pine2ast.quality.quality_gate()` and CLI command `pine2ast quality-gate PATH --json quality.json`.
- Quality gate checks parse result, ERROR/FATAL count, AST schema validity and diagnostic summary per file.
- Real-world seed corpus expanded from 200 to 240 Pine fixtures.
- Added v0.2.2 stdlib regression tests for collection typing, diagnostic diff and quality gate CLI.

Validation snapshot in the build workspace:

```text
python3 -S -m compileall -q pine2ast tests tools benchmarks
python -m pine2ast validate-corpus tests/fixtures/real_world --json corpus.json
240 files, 240 ok, 0 errors
python -m pine2ast quality-gate tests/fixtures/real_world --json quality.json
240 files, 240 ok, 0 errors, 0 schema errors
```

Known limitation remains: this is a Pine2AST parser/semantic front-end with production-oriented hardening, not full TradingView runtime parity and not a complete external-library resolver.

## v0.2.3 — CI/SARIF + semantic report big-block

- Version bump to `0.2.3`.
- Added `pine2ast.diagnostics.sarif`:
  - `diagnostics_to_sarif()`
  - `diagnostics_to_sarif_json()`
  - `write_sarif()`
- Added CLI:
  - `pine2ast sarif file.pine --json diagnostics.sarif`
  - `pine2ast semantic-report file.pine --json semantic.json`
- Added `pine2ast.semantic.reports.semantic_report()` for symbol/scope/type/qualifier reporting.
- Added semantic diagnostic `P2A1806 BRANCH_TYPE_MISMATCH` for incompatible ternary branch arms.
- Expanded real-world fixture seed from 240 to 300 Pine files.
- Added v0.2.3 regression tests for SARIF, semantic report, and ternary branch validation.
- Validation summary:
  - `compileall`: OK
  - stdlib tests: `120 passed`
  - corpus: `300 files / 300 ok / 0 errors`
  - quality gate: `300 files / 300 ok / 0 schema errors / 1 warning`


## v2.8.0 addendum

- Added parser recovery for malformed for-in destructuring.
- Added strategy namespace state/constant split and readonly trade accessor registry entries.
- Added soft unknown builtin namespace diagnostics.
- Added forward tuple return shape predeclaration.
- Verification: 143 stdlib tests passed; 300 real-world fixtures parse cleanly with zero errors.
