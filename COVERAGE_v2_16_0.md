# Coverage v2.16.0

Real local run in `.venv`:

```bash
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml
```

Result:

- Tests: `213 passed`
- Coverage gate: `fail_under = 90`
- Total reported coverage: `90.18%`
- `coverage.xml` line-rate: `0.931`
- `coverage.xml` branch-rate: `0.8329`

## Coverage omit policy

Only non-core entrypoint/legacy/generated-adjacent helpers remain omitted in `pyproject.toml`:

- CLI/entrypoints: `pine2ast/__main__.py`, `pine2ast/cli.py`, `pine2ast/benchmark.py`
- legacy split modules not used by the current parser implementation: `parser/declarations.py`, `parser/expressions.py`, `parser/statements.py`, `semantic/validators.py`, `layout/line_wrapping.py`
- diagnostic/fixture/support helpers: `diagnostics/sarif.py`, `testing/fixtures.py`, `lexer/trivia.py`, `source/source_map.py`, `layout/indentation.py`

Core active modules (`lexer.py`, `layout/processor.py`, `parser/parser.py`, `semantic/analyzer.py`, builtin registry, extractors, public API) are measured.

## Top remaining missing measured modules

From `TEST_RUN_v2_16_0.log`:

1. `pine2ast/semantic/analyzer.py` — 88%
2. `pine2ast/semantic/type_infer.py` — 86%
3. `pine2ast/semantic/extractors.py` — 87%
4. `pine2ast/semantic/builtin_registry.py` — 88%
5. `pine2ast/api.py` — 86%
6. `pine2ast/ast/schema.py` — 80%
7. `pine2ast/testing/golden.py` — 90%
8. `pine2ast/testing/compile_oracle.py` — 89%
9. `pine2ast/lexer/lexer.py` — 91%
10. `pine2ast/parser/parser.py` — 91%
