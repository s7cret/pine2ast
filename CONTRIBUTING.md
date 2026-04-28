# Contributing

Pine2AST is a parser, AST serializer and semantic-analysis library for Pine Script v6. Contributions should preserve the public AST contract unless a schema migration is explicitly planned and versioned. Prefer small, evidence-backed changes over broad rewrites.

## Ground rules

- Do not add C/JavaScript-style brace blocks. Pine layout is indentation/newline driven.
- Do not reinterpret `[]` as generic array indexing; in Pine parsing here it is history reference syntax unless a versioned design says otherwise.
- Do not treat `input` as a declaration keyword/qualifier.
- Do not fake TradingView evidence. Pending external oracle status is acceptable for RC work; production claims require evidence files.
- Keep `builtins_v6.json` schema versioned and validate every registry edit with tests.
- Keep generated/release evidence consistent: root final files describe the current release; older release packages and manifests belong in archive directories.

## Adding syntax

1. Start with a minimal `.pine` sample that demonstrates the syntax in real Pine form.
2. Add lexer/layout tests if tokenization, comments, wrapping or indentation are involved.
3. Add parser tests that assert the node kind and important fields, not incidental span details.
4. If JSON AST output changes, add or update a golden fixture intentionally. Do not bulk-refresh goldens without explaining the semantic reason.
5. Run:

```bash
python -m pytest tests/unit/test_parser_* tests/integration/test_golden_ast_contract.py
python -m pine2ast test-fixture tests/fixtures/valid/basic_indicator.pine
```

Parser changes should be behavior-preserving unless the changelog calls out the fix. If a syntax change affects semantic analysis, add both parser and semantic tests.

## Adding or changing an AST node

AST nodes live under `pine2ast/ast/`. A new node is a compatibility-sensitive change:

1. Define the node with stable, JSON-serializable fields.
2. Update serializers/schema validation if needed.
3. Add tests for construction and serialized JSON shape.
4. Add golden AST coverage for a representative fixture.
5. Document the change in `docs/ast_schema.md` and the changelog.
6. If existing output changes, state whether this is a bug fix or a schema migration.

For v3.x hardening releases, avoid AST schema changes unless explicitly required.

## Adding a semantic rule

Semantic rules should produce deterministic diagnostics with stable codes.

1. Add or reuse a diagnostic code in `pine2ast/diagnostics/codes.py`.
2. Implement the rule in the semantic analyzer or focused helper module.
3. Add positive and negative tests. A good rule test proves both that valid Pine is accepted and invalid Pine emits the expected diagnostic code.
4. If the rule depends on declaration context (`indicator`, `strategy`, `library`) or local/global scope, test each relevant context.
5. Update `docs/semantic_model.md` when the rule changes documented behavior.

Do not hide uncertain TradingView behavior behind a hard error. If the behavior is not externally verified, document it as an internal policy or keep it as a warning/backlog item.

## Adding a builtin signature

Builtin signatures are data-driven in `pine2ast/semantic/builtins_v6.json`.

1. Preserve `schema_version` and `pine_version` unless a registry schema migration is intentional.
2. Add the function/variable/type/namespace entry with explicit parameter names, required/optional status, return type and qualifier where known.
3. Add unit tests for positional and named arguments, duplicate arguments, required arguments, and obvious type/qualifier checks.
4. Run builtin coverage/report commands:

```bash
python -m pine2ast builtin-coverage --json reports/final/BUILTIN_COVERAGE_FINAL.json
python -m pytest tests/unit tests/integration
```

The registry is an internal expected snapshot, not a complete official TradingView map. If a change is based on official docs, record the source/date in the PR or changelog.

## Golden AST fixtures

Golden fixtures protect downstream consumers. Update them only when output changes are intentional.

Recommended flow:

```bash
python -m pine2ast golden tests/fixtures/valid/example.pine --ignore-spans
python -m pine2ast golden tests/fixtures/valid/example.pine --ignore-spans --compare
python -m pytest tests/integration/test_golden_ast_contract.py
```

When reviewing a golden diff, check node kind, declaration ordering, expression shape, diagnostics, and schema version. Avoid accepting noisy span-only changes unless the test is configured to ignore spans.

## Compile-oracle fixtures

Compile-oracle fixtures connect local expectations to TradingView evidence.

1. Add the `.pine` fixture under the appropriate category in `tests/fixtures/compile_oracle/`.
2. Update category `metadata.json` with fixture name, context, usage, expected result, local status and TradingView status.
3. If TradingView was actually checked, add evidence under a `TV_ORACLE_EVIDENCE_*` directory and reference it from release docs.
4. If TradingView was not checked, use `pending_external_oracle`; do not mark it pass/fail.
5. Run:

```bash
python tools/compile_oracle_report.py --path tests/fixtures/compile_oracle --json reports/final/COMPILE_ORACLE_FINAL.json
```

Production releases must have no pending P0 oracle fixtures. RC releases may use `--allow-pending` and must be named `oracle_pending`.

## Test gates

Use the full pytest gate when dependencies are available:

```bash
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml
```

Use the fallback runner only for low-dependency environments:

```bash
/usr/bin/python tools/run_tests_no_pytest.py
/usr/bin/python tools/run_tests_no_pytest.py --include-integration
```

The fallback runner executes plain stdlib-compatible tests and reports controlled skips for pytest-only modules or unsupported fixtures. It is not a replacement for the full release gate.

Full release gate:

```bash
bash scripts/release_gate.sh
python tools/build_release_zip.py . pine2ast_interpipe_v3_4_oracle_verified.zip --manifest RELEASE_MANIFEST_v3_4_oracle_verified.json
python tools/check_release_manifest.py RELEASE_MANIFEST_v3_4_oracle_verified.json
sha256sum pine2ast_interpipe_v3_4_oracle_verified.zip
```

## Documentation expectations

Every user-visible behavior change should update at least one of README, docs, changelog or limitations. If a surface is deferred, say so directly. Clear limitation docs are better than broad compatibility claims.
