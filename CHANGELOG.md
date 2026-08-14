# Changelog

## 4.0.2

- Refreshed package, release-manifest, semantic-snapshot, and generated producer metadata for the coordinated OpenPine 4.0.2 stack.
- Preserved the Pine v6 AST and semantic contracts without parser behavior changes.

## 4.0.1

- Published the hardened OpenPine 4.0.1 stack while preserving `pine.ast_contract.v1`, `openpine.frontend.v1`, and `runtime_contract_v1_4`.
- Aligned package, producer, lock, documentation, and release-gate metadata for reproducible immutable-SHA consumers.

## 4.0.0

Pine2AST 4.0.0 is the GitHub-ready production frontend release for the OpenPine toolchain. It consolidates the 3.x hardening work into a clean public release surface with stable contracts, canonical docs, deterministic distribution hygiene, and strict release gates.

### Added

- Canonical `docs/RELEASE_4_0.md` notes and GitHub tag checklist.
- Bundled 4.0 release manifest: `pine2ast/compatibility/release_4_0_manifest.json`.
- Bundled v6 release-feature matrix: `pine2ast/compatibility/release_features_v6_4_0.json`.

### Changed

- Package and producer metadata bumped to `4.0.0`.
- Top-level README rewritten for deployment as the public GitHub release description.
- Golden AST and inspect fixtures refreshed to producer version `4.0.0`.
- Release-readiness docs and scripts now use 4.0 artifact names.

### Compatibility

- No public contract ID change from the stabilized 3.x line.
- AST contract remains `pine.ast_contract.v1`.
- OpenPine frontend contract remains `openpine.frontend.v1`.
- Semantic snapshot contract remains `pine2ast.semantic_snapshot.v1`.
- Runtime profile marker remains `runtime_contract_v1_4`.

## 3.2.0

Pine2AST 3.2.0 is the final functional hardening step before release-polish. It keeps public contracts stable while adding deterministic artifact hygiene and stronger release gates.

### Added

- Dependency-free distribution manifest and deterministic source-zip builder:
  - `python -m pine2ast.distribution manifest --root .`
  - `python -m pine2ast.distribution build-zip --root . --output pine2ast-3.2.0.zip`
- Release manifest check for source-archive file selection.
- Canonical `docs/RELEASE_3_2.md` notes.
- Wheel install smoke script: `bash scripts/wheel_smoke.sh`.

### Changed

- Package and producer metadata bumped to `3.2.0`.
- Release feature matrix and bundled manifest renamed to the 3.2 line.
- README and development gates now include distribution hygiene, wheel-install smoke, and final release checklist commands.
- Legacy quality-gate artifact names were aligned with the 3.2 release line.

### Compatibility

- No breaking contract change.
- AST contract remains `pine.ast_contract.v1`.
- OpenPine frontend contract remains `openpine.frontend.v1`.
- Semantic snapshot contract remains `pine2ast.semantic_snapshot.v1`.

## 3.1.0

Pine2AST 3.1.0 is a post-3.0 hardening release for the OpenPine frontend line. It keeps public AST and OpenPine contract identifiers stable while tightening release gates and maintainability budgets.

### Added

- Public dependency-free contract validator for:
  - `pine.ast_contract.v1`;
  - `pine2ast.inspect.optimizer.v1`;
  - `openpine.frontend.v1`;
  - `pine2ast.semantic_snapshot.v1`.
- CLI/API contract check path through `pine2ast contract-check` and `pine2ast.contracts.validation`.
- Semantic snapshot sidecar contract through `pine2ast semantic-snapshot` and `--semantic-snapshot` on inspect payloads.
- Architecture budget quality gate.
- Release manifest architecture-budget and public-contract smoke checks.

### Changed

- Semantic validation mixin split into smaller focused modules for builtin namespace checks, type checks, collection checks, call validation, and member validation.
- Golden AST and inspect fixtures refreshed to producer version `3.1.0`.
- v6 release-feature matrix aligned with the 3.1 line.

### Compatibility

- Stable AST contract remains `pine.ast_contract.v1`.
- Stable OpenPine contract remains `openpine.frontend.v1`.
- Runtime profile marker remains `runtime_contract_v1_4`.

## 3.0.0

Pine2AST 3.0.0 promotes the project from a parser-prototype release line to an OpenPine frontend release line.

### Added

- Explicit Pine v5/v6 language profiles.
- Public `ParsePipeline` staging API.
- Version-aware `SignatureResolver` and signature coverage reporting.
- Shared `PineInferenceEngine` for type/qualifier facts.
- Collection signature validation for `array<T>`, `matrix<T>`, and `map<K,V>`.
- Static validation pass for dynamic requests, exported libraries, strategy exits, generic collection arity, and v6 const-int division.
- `openpine.frontend.v1` metadata sections for static validation, requests, strategies, collections, types, methods, callables, and control flow.
- Release manifest helper: `python -m pine2ast.release`.

### Changed

- Package version is `3.0.0`.
- AST contract id corrected to `pine.ast_contract.v1` before 3.x stabilization.
- CLI and OpenPine contract module are thin public façades.
- Golden AST and inspect fixtures refreshed to producer version `3.0.0`.

### Non-goals

- Pine2AST does not execute Pine scripts or emulate TradingView runtime/backtest behavior.
