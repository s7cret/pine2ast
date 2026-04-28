# Coverage policy

Pine2AST uses coverage as a release signal, not as a cosmetic number. The v3.7 gate keeps core package coverage at or above the configured threshold while documenting every active omit.

## Required gate

```bash
.venv/bin/python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml
```

The XML report is written to `coverage.xml`; the terminal report is captured in `reports/final/TEST_RUN_FINAL.log` by `scripts/release_gate.sh`.

## Omit policy

A file may remain omitted only when one of these is true:

1. It is tiny process glue better covered by subprocess smoke tests than line coverage.
2. It is timing/environment-sensitive and line coverage would incentivize brittle tests.
3. It is a compatibility shim with no independent runtime behavior.
4. It is a test helper module rather than shipped parser/semantic logic.

## Current v3.7 omissions and reasons

- `pine2ast/__main__.py`: module entry-point shim; covered through CLI invocation paths and direct `pine2ast.cli.main` tests.
- `pine2ast/benchmark.py`: timing-oriented helper. CLI/quality smoke tests exercise the public commands, but threshold line coverage would be noisy because results depend on host timing.
- `pine2ast/layout/indentation.py`, `pine2ast/layout/line_wrapping.py`: one-line compatibility modules retained for import stability; behavior is in `LayoutProcessor` and parser integration fixtures.
- `pine2ast/testing/fixtures.py`: test helper module, not runtime parser logic.
- `pine2ast/lexer/trivia.py`: legacy trivia compatibility surface; lexer token/trivia behavior is covered through lexer tests.

## v3.6 cleanup completed

v3.6 removes prior omissions for:

- `pine2ast/cli.py` via focused happy/error/report CLI tests.
- `pine2ast/diagnostics/sarif.py` via JSON-shape and file-output tests.
- `pine2ast/source/source_map.py` via direct constructor coverage.
- `pine2ast/semantic/validators.py` via direct runtime-surface tests.
- `pine2ast/parser/declarations.py`, `pine2ast/parser/expressions.py`, `pine2ast/parser/statements.py` after v3.5 parser modularization made them first-class implementation modules.

Omitted files must not be used to hide known failing runtime code.
