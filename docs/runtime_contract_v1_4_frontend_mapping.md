# runtime_contract_v1.4 frontend mapping

Status: `oracle_expansion_pending` / frontend contract hardening. This document does **not** claim new TradingView compile verification or full Pine v6 parity.

Release train metadata: `pain-stack-pine-v6-2026.04-r1`; `pine_language_version=6`; `pine_docs_baseline=2026-04`; `runtime_contract=1.4`. The April 2026 Pine-language-relevant baseline delta is UDT collection sorting via `sort_field` for `array.sort`, `array.sort_indices`, and `matrix.sort`. Pine Editor word-wrap is documented as non-runtime/editor UX and is not a parser/runtime parity claim.

Machine-readable mapping: `tests/fixtures/runtime_contract_v1_4/frontend_node_mapping.json`.

## Scope

This bridge states what Pine2AST may hand to AST2Python/PineLib under `runtime_contract_v1.4`:

- every schema node kind must appear in the mapping;
- every mapped item lists required/optional JSON fields (excluding `span`, which all AST nodes carry);
- every node kind is either lowerable/runtime-supported for the contract layer or has a stable unsupported diagnostic code;
- unsupported behavior must be surfaced before runtime via `P2A1507` or a more specific semantic diagnostic.

## Preserved parser/schema guardrails

- No Pine blocks via `{}`.
- `input` is not a declaration qualifier.
- `[]` remains `HistoryRefExpr`; Pine collection access is not silently reinterpreted as generic array indexing.
- Semantic checks remain outside the parser.
- AST schema stays `1.0`; this milestone adds contract metadata and tests only.

## Current unsupported/partial bridge points

`ImportDeclaration` is schema-valid and semantically indexed, but `runtime_contract_v1.4` does not define online import resolution. Pine2AST therefore emits `P2A1507` as a warning marker when imports are present. Downstream tools may still record aliases, but must not treat external library bodies as resolved runtime code.

Several node kinds are structurally lowerable while still depending on runtime support for exact Pine parity:

- `HistoryRefExpr`: valid only for runtime series/history. Reference-object history requires PineLib's explicit reference-history decision.
- `CallExpr` / `MemberAccessExpr` / `GenericInstantiationExpr`: valid for the modeled builtin subset. Unknown namespaces, unsupported signatures, and deferred builtins must remain diagnostics, not runtime surprises.
- `TypeDeclaration`, `MethodDeclaration`, `TupleDeclaration`, `TupleExpr`, `ForInStructure`: represented in schema and AST2Python's supported-node catalog, but full Pine reference/collection parity depends on PineLib work outside Pine2AST.

## Oracle status

The v3.6-v3.8 compile-oracle expansion fixtures remain pending unless fixture-specific TradingView Pine Editor evidence exists. The sign-in blockers in `TV_ORACLE_ATTEMPT_v3_7/` and `TV_ORACLE_ATTEMPT_v3_8/` are not compile evidence. Use the pending release gate mode until pending count is zero.

## Verification

Contract tests:

```bash
python -m pytest tests/unit/test_runtime_contract_v1_4.py
```

Full frontend gate:

```bash
python -m ruff check .
python -m black --check .
python -m mypy pine2ast
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml
python -m pine2ast quality-gate tests/fixtures/real_world --json reports/final/QUALITY_GATE_FINAL.json
python tools/check_release_manifest.py RELEASE_MANIFEST_v3_9_runtime_contract_v1_4_oracle_expansion_pending.json
bash scripts/release_gate.sh --allow-pending-oracle
```
