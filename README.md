# Pine2AST 5.0.0rc5

> Production Pine Script v5/v6 frontend for OpenPine: parser, AST JSON, static diagnostics, semantic snapshots, and OpenPine metadata contracts.

[![Version](https://img.shields.io/badge/version-5.0.0rc5-blue)](https://github.com/s7cret/pine2ast) [![Python](https://img.shields.io/badge/python-%3E%3D3.11-blue)](https://github.com/s7cret/pine2ast) [![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/s7cret/pine2ast)


**GitHub description:** Pine2AST parses Pine Script v5/v6 into stable AST and metadata contracts for OpenPine, with static diagnostics, semantic snapshots, compatibility gates, and CI-friendly quality reports.

**Suggested topics:** `pine-script`, `tradingview`, `parser`, `ast`, `static-analysis`, `compiler-frontend`, `algorithmic-trading`, `python`.

## What Pine2AST is

Pine2AST is the frontend of the OpenPine toolchain. It reads Pine Script source, tokenizes it, parses it, runs static semantic passes, and emits machine-readable contracts consumed by downstream tooling.

```text
Pine source -> Pine2AST -> AST JSON / diagnostics / OpenPine frontend metadata
                              │
                              └─> AST2Python -> PineLib runtime modules
```

The package is intentionally focused on parsing and static contracts. It does not execute Pine code and does not emulate TradingView runtime behavior.

## 4.0 contract status

| Area | Status |
|---|---|
| Pine profiles | v5 and v6 static profiles. |
| AST JSON | Stable `pine.ast_contract.v1`. |
| OpenPine metadata | Catalog `openpine.frontend.v2`. |
| Semantic snapshot | `pine2ast.semantic_snapshot.v1` for CI/debugging. |
| Runtime marker | `runtime_contract_v1_4` for downstream compatibility. |
| Builtin coverage | Version-aware builtin and namespace checks. |
| Collections | Static contracts for `array<T>`, `matrix<T>`, and `map<K,V>`. |
| UDT / enum / methods | Parsed and represented in semantic facts where supported. |
| `request.*` / `strategy.*` | Static metadata and diagnostics only. |
| Runtime/backtest | Out of scope; handled by PineLib, Backtest Engine, and OpenPine. |

## What it does

- Parses Pine v5/v6 source into a stable AST contract.
- Emits JSON suitable for CI pipelines, AST2Python, and OpenPine inspection.
- Produces diagnostics, SARIF-style reports, semantic snapshots, and schema checks.
- Validates builtin namespace usage and release-feature compatibility.
- Exposes OpenPine-facing metadata contracts for strategy registration, inputs, dependencies, and static capabilities.
- Provides corpus, golden, benchmark, and quality-gate commands for maintainers.

## What it does not do

Pine2AST is not a TradingView runtime. It does not execute scripts, fetch market data, allocate runtime objects, simulate orders, calculate PnL, or claim full TradingView parity. Those responsibilities belong to downstream runtime/backtest packages.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Install from GitHub tag:

```bash
python -m pip install 'git+https://github.com/s7cret/pine2ast.git@v4.0.2'
```

## Python quick start

```python
from pine2ast import ParseOptions, ast_to_json, parse_code

source = '''//@version=6
indicator("Demo", overlay=true)
plot(close)
'''

result = parse_code(source, ParseOptions(version=6))
print(result.ok)
print(ast_to_json(result.ast))
```

OpenPine inspection payload:

```python
from pine2ast import ParseOptions, parse_code
from pine2ast.inspect_contract import build_inspect_payload

result = parse_code(source, ParseOptions(version=6))
payload = build_inspect_payload(
    result,
    source_path="inline.pine",
    include_openpine_contract=True,
)
print(payload["openpine_contract"]["schema_version"])
```

## CLI quick start

```bash
pine2ast parse strategy.pine --json strategy.ast.json
pine2ast validate strategy.pine
pine2ast inspect strategy.pine --openpine-contract --json inspect.json
pine2ast semantic-snapshot strategy.pine --json semantic.snapshot.json
pine2ast schema-check strategy.pine --json schema.json
pine2ast contract-check strategy.pine --json contract.json
pine2ast diagnostics-report strategy.pine --json diagnostics.json
pine2ast sarif strategy.pine --json diagnostics.sarif.json
pine2ast quality-gate tests/fixtures/real_world --json quality.json
```

Release and compatibility helpers:

```bash
pine2ast builtin-coverage --json builtin_coverage.json
python -m pine2ast.semantic.signature_coverage --version 5 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.semantic.signature_coverage --version 6 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.distribution manifest --root .
python -m pine2ast.quality architecture pine2ast --max-lines 700
```

## Repository layout

```text
pine2ast/
  lexer/                  tokenization and trivia
  parser/                 Pine grammar parser
  ast/                    node model, schema, serialization
  semantic/               semantic passes, builtin registries, signatures
  diagnostics/            diagnostic model, formatter, SARIF/report output
  openpine_contracts/     OpenPine-facing metadata contracts
  compatibility/          release and signature compatibility matrices
  layout/                 indentation and line wrapping helpers
  tests/                  fixtures, golden files, contract tests
```

## Quality gates

```bash
python -m compileall -q pine2ast tests
python -m ruff check .
python -m black --check .
python -m mypy pine2ast
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m pine2ast.distribution manifest --root .
python -m pine2ast.release --root .
bash scripts/wheel_smoke.sh
```

## Documentation

- `docs/ARCHITECTURE.md` — frontend pipeline and module ownership.
- `docs/COMPATIBILITY.md` — v5/v6 compatibility matrix and runtime boundary.
- `docs/OPENPINE_CONTRACT.md` — OpenPine-facing metadata contract.
- `docs/DEVELOPMENT.md` — local setup and quality gates.
- `docs/RELEASE_4_0.md` — release notes and tag checklist.
- `docs/ROADMAP.md` — post-4.0 frontend work.
- `docs/SECURITY.md` — parser input limits and safe integration guidance.

## License

MIT. See `LICENSE`.

## Support

OpenPine development is independent and MIT-licensed. Support is optional and does not change license terms, feature access, or project guarantees.

- Telegram: https://t.me/OpenPine
- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`