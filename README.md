# Pine2AST

Pine2AST is a Python parser/frontend for a verified Pine Script v6 subset. It normalizes Pine source into structured AST JSON, semantic diagnostics, and frontend metadata for downstream tooling such as AST2Python.

Pipeline:

```text
SourceNormalizer -> Lexer -> LayoutProcessor -> Parser -> AST -> SemanticAnalyzer
```

Pine2AST owns parsing, normalized AST JSON, semantic diagnostics, compile-oracle evidence, and frontend-to-runtime compatibility metadata.

It does **not** execute Pine code, run backtests, fetch market data, optimize parameters, emulate TradingView orders, or claim full Pine v6 / TradingView parity. The current claim is a **verified Pine v6 subset** backed by fixture-specific evidence.

## Scope & Status

| Claim | Status |
|---|---|
| Pine v6 parsing (subset) | supported — see `tests/fixtures/real_world` and `tests/fixtures/compile_oracle` |
| AST JSON contract `pain.ast_contract.v1` | stable |
| Semantic diagnostics (subset) | supported — scopes, types, qualifiers, history refs, method receivers |
| Builtin registry | versioned subset (475 functions / 161 variables / 213 methods / 239 constants) |
| **Full TradingView Pine v6 parity** | **not claimed** |
| Pine execution (bar-by-bar, var/varip, barstate.*) | out of scope — lives in `pinelib` runtime |
| Backtest / broker emulator | out of scope |
| `request.*` data fetching | local diagnostics only — runtime is data-layer concern |
| Realtime tick / rollback semantics | not implemented |

## Release compatibility

| pine2ast | AST contract | Runtime contract | ast2python | pinelib |
|---|---|---|---|---|
| 2.17.x | `pain.ast_contract.v1` | `1.4` | 2.17.x | 2.17.x |
| 2.18.x | `pain.ast_contract.v1` | `1.4` | 2.18.x | 2.18.x |

A runtime contract mismatch is a deterministic `P2A_CONTRACT_VERSION_MISMATCH` error — never a silent fallback.

Current compile-oracle snapshot:

- fixtures: `35`
- ok: `35`
- pending: `0`
- invalid: `0`
- platform-blocked: `0`

## Install

```bash
python -m pip install -e .
```

For development:

```bash
python -m pip install -e '.[dev]'
```

## Quick start

```python
from pine2ast import ast_to_json, parse_code

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
pine2ast inspect strategy.pine --json inspect.json
pine2ast schema-check strategy.pine --json schema.json
pine2ast diagnostics-report strategy.pine --json diagnostics.json
pine2ast diagnostics-diff diagnostics.json baseline.json
pine2ast quality-gate tests/fixtures/real_world --json quality.json
```

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | parse ok, no `ERROR`/`FATAL` diagnostics |
| 1 | `ERROR` diagnostics |
| 2 | `FATAL` diagnostics |
| 3 | internal error |

## Development gates

```bash
python -m ruff check .
python -m black --check .
python -m mypy pine2ast
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml
bash scripts/release_gate.sh
```

Fallback without pytest:

```bash
/usr/bin/python tools/run_tests_no_pytest.py
/usr/bin/python tools/run_tests_no_pytest.py --include-integration
```

The fallback runner is a low-dependency smoke/regression aid. It does not replace the full pytest/coverage gate.

## Implemented areas

- UTF-8/BOM/CRLF source normalization.
- Stateful lexer for literals, strings, comments/annotations, operators, and identifiers.
- Layout processing with `NEWLINE`/`INDENT`/`DEDENT` and line wrapping support.
- Recursive-descent + Pratt parser.
- Stable AST node model and JSON serialization.
- Semantic diagnostics for scopes/symbols, assignment forms, bool-v6 checks, history references, selected local-builtin restrictions, and method receiver typing.
- Versioned Pine v6 builtin subset registry.
- Integration-oriented `inspect` contract for downstream AST2Python/optimizer-style consumers.

## Limitations

- Pine2AST is not a TradingView runtime.
- Oracle evidence covers the committed fixture corpus, not the entire Pine language.
- `pine2ast/semantic/builtins_v6.json` is a supported-subset/confidence matrix, not a complete official builtin map.
- Imports are parsed/diagnosed locally; there is no online import resolver.
- Unsupported areas should surface as diagnostics rather than silent approximations.

## License

MIT. See `LICENSE`.

## Installation, Docker, and Publication

```bash
./scripts/install.sh --dev
docker compose run --rm pine2ast
```

## Acknowledgements

This project was developed with AI-assisted engineering workflows. The license and release obligations are defined only by `LICENSE` and the repository documentation above.

## Support / Donations

OpenPine development is independent and MIT-licensed. Donations are optional and help keep the public tooling maintained.

- Telegram: https://t.me/OpenPine
- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`

Support does not affect license terms, feature access, or project guarantees.
