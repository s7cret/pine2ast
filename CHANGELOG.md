# Changelog

## 5.0.0rc6 — Stage 6 corrected delivery

- Fixed invalid duplicate package-data TOML key and restored standards-compliant builds.
- Corrected historical `study()` handling for Pine v1-v4.
- Rebuilt the v6 catalog from the authoritative snapshot, including `calc_on_every_history_tick`.
- Assigned unique Stage 6 diagnostic IDs and removed diagnostic-code collisions.
- Enforced the final diagnostic ceiling after version-semantic validation.
- Recomputed aggregate frontend/semantic gates after all static passes.
- Replaced parse-time `verified_rule_ids` claims with `applicable_rule_ids`.
- Added packaging, wheel RECORD, clean-install, all-version smoke, and regression evidence.
- Synchronized the Stage 6 review probes with the dedicated `P2A2101`–`P2A2110` diagnostics.
- Replaced self-attested requirement labels with a concrete 66-node evidence graph bound to collected pytest nodes and JUnit outcomes.
- Added tamper-evident official-source records for every TradingView documentation URL referenced by the frontend requirements.
- Closed Ruff, Black, MyPy, and 90% branch-aware package coverage gates without excluding critical modules.
- Separated timing-sensitive performance tests from coverage instrumentation while retaining them in the complete suite.
- Kept coordinated Ast2Python acceptance explicit and fail-closed; producer review readiness does not authorize release.

## 5.0.0rc6 — Stage 6 semantic closure

- Added a version-exact static-semantic hardening pass for Pine v1-v6.
- Closed historical/modern declaration, namespace, collection, parameter, and spelling availability gaps.
- Added a normative requirement catalog with explicit downstream ownership boundaries.
- Split verified static coverage, internal catalog completeness, official-reference completeness, and runtime/oracle parity into independent axes.
- Added official-document provenance hashes, adjacent-version differential tests, deterministic fuzzing, mutation gates, and a Stage 6 review report.
- Updated package description and version-support documentation without adding compatibility aliases or source rewriting.

## 5.0.0rc6 Stage 5

- Implements version-bound historical static semantics for Pine v1, v2, v3, and v4.
- Adds official-source-linked historical corpus and adjacent-version differential gates.
- Adds stable historical symbol identity checks and all-version consumer bundles.
- Preserves fail-closed boundaries: historical catalogs are conservative snapshots, not asserted exhaustive manuals.
- Retains Stage 1-4 version, catalog, semantic-facts, mutation, reproducibility, and packaging gates.

## 5.0.0rc6 — Stage 4 hardening

- Added deterministic corpus, differential, fuzz, contract-mutation and performance gates.
- Added `pine2ast.consumer_bundle.v1` and explicit fail-closed Ast2Python coordinated boundary.
- Made catalog build tooling independent of caller `PYTHONPATH` and working directory.

# Changelog

## 5.0.0rc6

### Stage 3

- Bound lexer, parser and semantic analyzer to one hash-verified version context.
- Added structured syntax/semantic policies for v5 and v6.
- Added deterministic callable fixed-point inference for UDF signatures.
- Made overload resolution fail closed on invalid and ambiguous calls.
- Added stable overload IDs, parametric return-rule IDs and operator rule IDs.
- Added complete node/call facts in `pine.semantic_facts.v1`.
- Added sealed source -> AST -> facts -> support -> frontend lineage.
- Added pinned-catalog static completeness gates for v5/v6.

### Stages 1–2

- Unified Pine version identity.
- Removed legacy compatibility/runtime coupling.
- Added canonical sparse catalog and deterministic packs v1–v6.
