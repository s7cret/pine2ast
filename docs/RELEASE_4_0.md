# Pine2AST 4.0 release notes

Pine2AST 4.0.0 is the GitHub-ready production frontend release for the OpenPine toolchain. It consolidates the pre-4.0 hardening line into one clean release surface: stable public contracts, 100% machine-readable official-name/signature readiness, deterministic distribution hygiene, canonical documentation, and strict release gates.

## Highlights

- package version bumped to `4.0.0`;
- top-level README and canonical docs rewritten for public GitHub deployment;
- bundled release-feature matrix moved to `release_features_v6_4_0.json`;
- bundled release manifest moved to `release_4_0_manifest.json`;
- golden AST and inspect fixtures refreshed to producer version `4.0.0`;
- release gates require 100% v5/v6 signature-readiness for official names;
- deterministic source-zip and wheel-smoke workflows are documented as part of the tag checklist;
- architecture budget remains enforced at `--max-lines 700`.

## Contract compatibility

4.0.0 keeps the stabilized public integration identifiers:

- `pine.ast_contract.v1`;
- `openpine.frontend.v1`;
- `runtime_contract_v1_4`;
- `pine2ast.semantic_snapshot.v1`.

This means downstream OpenPine packages can treat 4.0.0 as a production frontend release without changing their contract IDs. Semantic/runtime parity is still bounded by the documented frontend/runtime split.

## Runtime boundary

Pine2AST remains a frontend/static-semantics package. It does not execute scripts, fetch market data, emulate broker fills, calculate PnL, run backtests, or claim full TradingView runtime parity.

## Release gate

The 4.0 release gate should include:

```bash
python -m compileall -q pine2ast tests
python -m pytest -q
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term
python -m pine2ast.quality duplicates pine2ast
python -m pine2ast.quality architecture pine2ast --max-lines 700
python -m pine2ast.semantic.signature_coverage --version 5 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.semantic.signature_coverage --version 6 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.compatibility.release_features
python -m pine2ast.contracts.validation tests/fixtures/valid/declarations/basic_indicator.pine
python -m pine2ast.distribution manifest --root .
python -m pine2ast.release --root . --json RELEASE_MANIFEST.json
bash scripts/wheel_smoke.sh
```

Full CI should additionally run `ruff`, `black --check`, `mypy`, and OpenPine cross-repository smoke tests in an environment with dev dependencies installed.

## GitHub tag checklist

1. Start from a clean checkout.
2. Install dev dependencies with `python -m pip install -e '.[dev]'`.
3. Run `bash scripts/release_gate.sh`.
4. Build the deterministic source archive with `python -m pine2ast.distribution build-zip --root . --output ../pine2ast-4.0.0.zip`.
5. Verify the archive with `unzip -tq ../pine2ast-4.0.0.zip`.
6. Run OpenPine cross-repository smoke tests before publishing the tag.
