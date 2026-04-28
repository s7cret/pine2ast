# Pine2AST

Pine2AST is a Python parser/frontend for a verified Pine Script v6 subset. It normalizes Pine source into structured AST JSON, semantic diagnostics, and frontend metadata for downstream tooling such as AST2Python.

Pipeline:

```text
SourceNormalizer -> Lexer -> LayoutProcessor -> Parser -> AST -> SemanticAnalyzer
```

Current package version: `0.3.9` / Pine2AST release `v3.9`.

## Stack release scope

This repository is one component of the April 2026 stack train:

- stack release: `pain-stack-pine-v6-2026.04-r1`
- Pine language baseline: `pine_language_version=6`
- documentation baseline: `pine_docs_baseline=2026-04`
- runtime contract: `runtime_contract=1.4`
- manifest: `RELEASE_STACK_MANIFEST_2026_04_R1.json`

Pine2AST owns parsing, normalized AST JSON, semantic diagnostics, compile-oracle evidence, and frontend-to-runtime compatibility metadata.

It does **not** execute Pine code, run backtests, fetch market data, optimize parameters, emulate TradingView orders, or claim full Pine v6 / TradingView parity. The current claim is a verified Pine v6 subset/oracle snapshot backed by fixture-specific evidence.

Current compile-oracle snapshot:

- fixtures: `35`
- ok: `35`
- pending: `0`
- invalid: `0`
- platform-blocked: `0`

Future Backtest Engine and Optimizer packages are independent future layers and are not part of the current Pine2AST release claim.

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

See `docs/current_limitations_v3_9.md` for the current limitation map.

Important guardrails:

- Pine2AST is not a TradingView runtime.
- Oracle evidence covers the committed fixture corpus, not the entire Pine language.
- `pine2ast/semantic/builtins_v6.json` is a supported-subset/confidence matrix, not a complete official builtin map.
- Imports are parsed/diagnosed locally; there is no online import resolver.
- Unsupported areas should surface as diagnostics rather than silent approximations.

## Documentation map

- `CHANGELOG_v3.9.md` — current release notes.
- `docs/current_limitations_v3_9.md` — current limitations.
- `docs/runtime_contract_v1_4_frontend_mapping.md` — runtime-contract bridge notes.
- `docs/parser_architecture.md` — parser implementation notes.
- `RELEASE_STACK_MANIFEST_2026_04_R1.json` — stack metadata and release guardrails.

## License

MIT. See `LICENSE`.

## Acknowledgements

This project was developed with AI-assisted engineering workflows. The license and release obligations are defined only by `LICENSE` and the repository documentation above.

## Support / Donations

If this project saves you time or helps your trading/research infrastructure, tips are appreciated:

- TON: `UQAyIr2sQ4-_Q5L-4VINcU18khDas5GPbAlYEkQN6S_qzui2`
- SOL: `EbxMUK2W4RGeQZCTRFrdgpEJvnqtyczPZvBrQa1cYJnQ`

Donations are optional and do not affect the MIT license terms.
