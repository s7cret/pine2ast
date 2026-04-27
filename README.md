# Pine2AST

`pine2ast` — Python-библиотека для разбора Pine Script™ v6 в нормализованный AST. Реализация построена по pipeline:

```text
SourceNormalizer -> Lexer -> LayoutProcessor -> Parser -> AST -> SemanticAnalyzer
```

Проект intentionally не исполняет Pine-код, не использует `eval/exec` и не ходит в интернет из CLI.

## Быстрый старт

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest
# fallback without pytest, only stdlib:
/usr/bin/python tools/run_tests_no_pytest.py
```

```python
from pine2ast import parse_code, ast_to_json

src = '''//@version=6
indicator("My Indicator", overlay = true)
plot(close)
'''
result = parse_code(src)
print(result.ok)
print(ast_to_json(result.ast))
```

## CLI

```bash
pine2ast parse strategy.pine --json out.ast.json
pine2ast tokens strategy.pine
pine2ast validate strategy.pine
pine2ast dump-symbols strategy.pine
pine2ast test-fixture tests/fixtures/valid/basic_indicator.pine
pine2ast bench tests/fixtures --repeat 20 --json benchmark.json
```
Additional production-oriented commands added in v0.2.x:

```bash
python -m pine2ast inspect strategy.pine --json inspect.json
python -m pine2ast schema-check strategy.pine --json schema.json
python -m pine2ast diagnostics-report strategy.pine --json diagnostics.json
python -m pine2ast diagnostics-diff diagnostics.json baseline.json
python -m pine2ast quality-gate tests/fixtures/real_world --json quality.json
```


Exit codes:

| Code | Meaning |
|---:|---|
| 0 | parse ok, no ERROR/FATAL |
| 1 | ERROR diagnostics |
| 2 | FATAL diagnostics |
| 3 | internal error |

## Что реализовано

- UTF-8/BOM/CRLF normalizer.
- Stateful lexer: literals, strings, comments/annotations, operators, identifiers.
- LayoutProcessor: `NEWLINE/INDENT/DEDENT`, базовый line wrapping.
- Recursive descent + Pratt parser.
- AST nodes + stable JSON serialization.
- SemanticAnalyzer: scopes/symbols, `=` vs `:=`, bool v6 checks, history reference checks, `strategy.*(when=...)`, forbidden local builtins.
- Versioned `builtins_v6.json`.
- CLI and pytest suite.
- Hardening: generic type annotations (`array<float>`), generic calls (`array.new<float>()`), comma-separated one-line function bodies, stricter second declaration detection, `input`-qualifier rejection, loop-local forbidden builtin checks, method receiver type diagnostics.
- v0.1.2: tuple-expression returns (`[a, b]`), stricter declaration-in-local diagnostics, data-driven builtin named-parameter validation, history reference warning for local-scope values, stronger optimizer extractors, golden AST regression, and `pine2ast bench`.

## Ограничения текущей версии

Это v1-prototype foundation, а не полный компилятор TradingView. Неполная registry-сигнатура встроенных функций, без online import resolver, без полного real-world корпуса 200–300 файлов. Архитектура оставляет эти пункты как v1.1/v2 hardening backlog.


## v0.1.3 corpus validation

```bash
pine2ast validate-corpus tests/fixtures --json corpus.json
```

This command parses every `.pine` file under a directory and writes a compact JSON report with ok/error counts and diagnostic codes.

## v0.1.5 big-block hardening highlights

This build adds a larger production-integration block: member reassignment support,
callee-root validation, builtin qualifier checks, `golden` CLI generation/compare,
`dump-symbols --json`, and a seed `tests/fixtures/real_world` corpus.

Useful commands:

```bash
pine2ast golden tests/fixtures/valid/basic_indicator.pine --ignore-spans
pine2ast golden tests/fixtures/valid/basic_indicator.pine --ignore-spans --compare
pine2ast dump-symbols tests/fixtures/valid/basic_indicator.pine --json
pine2ast validate-corpus tests/fixtures/real_world --json corpus.json
```

Additional v0.1.5 hardening:

- symbol-aware type/qualifier inference for identifiers and member constants;
- `na(x)` recognised as a builtin call while preserving `na` literal parsing;
- wider Pine v6 builtin/variable seed for `input.source`, `request.financial`, common `ta.*`, drawing/table helpers, `strategy.*` state and UI constants;
- real-world fixture seed extended to 15 files;
- input extractor now reads positional `title` and tuple/list-style `options`.

## v0.1.6 big-block hardening highlights

- Parser now accepts trailing commas in calls, generic invocations, parameter lists and tuple declarations/expressions.
- Member access after `.` accepts Pine keyword-shaped names such as `input.enum()`.
- Switch case bodies can use inline comma-separated statement sequences, matching Pine function-body style.
- Semantic inference recognizes UDT constructors (`Pivot.new(...)`) and UDT field access (`p.y`).
- Method calls are receiver-type checked when a method declaration is available.
- Type references are validated and emit `P2A1604 UNKNOWN_TYPE` for unresolved explicit types.
- `extract_inputs()` understands `options = array.from(...)` in addition to tuple-style options.
- Builtin registry expanded to 165 function entries and the real-world seed corpus was expanded to 30 clean files.


## v0.1.8 big-block hardening highlights

- Added `P2A1406 ARGUMENT_TYPE` and stricter call-contract validation for builtin, user function, method and UDT constructor calls.
- Tuple declarations now propagate tuple-return element types into target symbols, e.g. `ta.bb()` targets become `float`.
- UDT constructors now validate required fields, defaults, field names and field types.
- `extract_inputs()` now preserves symbolic enum/member constants such as `Mode.Fast` in defaults/options.
- Builtin registry signatures were corrected for `ta.linreg`, `color.from_gradient`, `str.format`, and `line.get_price`.
- Real-world seed corpus expanded to 50 clean fixtures and tests expanded to 72 stdlib-runner checks.

## v0.1.8 highlights

- Collection element inference for `array.from`, `array.get`, method-style `values.get()`, `first()`, `last()`.
- Generic type annotations are preserved in symbols, e.g. `map<string,float>`.
- `for ... in ...` target inference for arrays and maps.
- Duplicate positional+named argument validation for builtins and user functions.
- Seed real-world corpus: 80 Pine files.

## v0.1.9 big-block hardening highlights

- Explicit type compatibility checks for variable initializers, reassignments, UDT field defaults, and function/method parameter defaults.
- Loop range validation: `for i = start to end by step` bounds are checked as int-like expressions.
- Switch validation: bool-case checking for expressionless `switch`, and comparable case-type checking for `switch expr`.
- Smarter inference for `request.security(..., expression)`, including tuple expressions requested from another timeframe.
- Smarter map/matrix/array element inference for `map.get`, `matrix.get`, and collection methods.
- `builtins_v6.json` expanded to 231 function entries with more `ta.*`, `math.*`, `str.*`, `request.*`, `map.*`, `matrix.*`, `chart.point.*`, and `input.text_area`.
- Real-world seed corpus expanded from 80 to 100 Pine files.


### Inspect command

`pine2ast inspect` is the integration-oriented command for AST2Python/optimizer pipelines. It parses a script and emits a compact JSON payload containing diagnostics, inputs, strategy calls, request calls, plot calls, alert conditions, drawing calls and dependency metadata.

```bash
python -m pine2ast inspect strategy.pine --json inspect.json
```

This command does not execute Pine code and does not access the network.


## v0.2.0 milestone highlights

- Added `P2A1605 UNKNOWN_FIELD` for unresolved UDT fields.
- Added UDT member access validation and field reassignment type checks.
- Added optimizer/AST2Python inspection helpers: `extract_alertconditions()`, `extract_drawing_calls()`, and `extract_dependencies()`.
- Added `pine2ast inspect`, which emits compact JSON for diagnostics, inputs, strategy calls, request calls, plots, alerts, drawings and dependency metadata.
- Expanded the seeded real-world corpus to 150 clean `.pine` fixtures.
- Added v0.2.0 regression checks; stdlib runner reports `100 passed`.

Example:

```bash
python -m pine2ast inspect strategy.pine --json inspect.json
python -m pine2ast validate-corpus tests/fixtures/real_world --json corpus.json
```

### v0.2.1 schema and diagnostics tooling

```bash
pine2ast schema-check strategy.pine --json schema.json
pine2ast diagnostics-report strategy.pine --json diagnostics.json
```

`schema-check` validates the stable JSON-facing AST contract: `schema_version`, language metadata, node kinds, node count, and `SourceSpan` presence/sanity for every AST node.

`diagnostics-report` groups parser/semantic diagnostics by severity and code, which is useful for CI gates and optimizer ingestion reports.

## v0.2.3 CI/SARIF and semantic-report milestone

This release adds another production-integration layer for CI and downstream AST2Python/optimizer consumers:

```bash
python -m pine2ast sarif strategy.pine --json diagnostics.sarif
python -m pine2ast semantic-report strategy.pine --json semantic.json
```

Highlights:

- SARIF 2.1.0 diagnostics export for code-scanning dashboards and CI artifacts.
- `semantic-report` CLI with symbol/scope/type/qualifier summaries.
- New `P2A1806 BRANCH_TYPE_MISMATCH` diagnostic for incompatible ternary branch types.
- Real-world fixture seed increased to 300 Pine files.
- Stdlib test runner reports `120 passed` in this release package.

The SARIF exporter is intentionally read-only: it converts existing diagnostics into a machine-readable report and never executes Pine code.

## v0.2.14 quality/CI hardening

This release adds the reproducible release-quality layer required by the residual P0 hardening block:

```bash
pip install -e .[dev]
python tools/run_quality_gate.py --strict-dev-tools
python -m pytest --cov=pine2ast --cov-report=term-missing
python -m ruff check .
python -m black --check .
python -m mypy pine2ast
```

GitHub Actions now runs the package on Python 3.10, 3.11 and 3.12 with lint, format, coverage and the release quality wrapper. In minimal sandboxes without dev dependencies, `tools/run_quality_gate.py` records skipped optional tools explicitly; it never silently marks missing `pytest-cov`, `ruff`, `black` or `mypy` as real passes.

## v2.15.0 fixture hardening

Curated regression assets now include:

- 57 valid Pine fixtures under `tests/fixtures/valid/`;
- 57 golden AST JSON files under `tests/fixtures/golden_ast/valid/`;
- 57 golden diagnostics JSON files;
- 23 invalid fixtures with companion `.diagnostics.json` expected-code contracts.

Useful checks:

```bash
pytest tests/integration/test_golden_ast_contract.py
pytest tests/integration/test_invalid_diagnostics_contract.py
python -m pine2ast golden tests/fixtures/valid/declarations/basic_indicator.pine --ast tests/fixtures/golden_ast/valid/declarations/basic_indicator.ast.json --compare --ignore-spans
```

The stdlib fallback runner remains unit-first for constrained agents:

```bash
PYTHONPATH=. python -S tools/run_tests_no_pytest.py
PYTHONPATH=. python -S tools/run_tests_no_pytest.py --include-integration
```
