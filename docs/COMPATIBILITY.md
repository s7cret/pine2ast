# Compatibility

Pine2AST 4.0 targets verified Pine Script v5/v6 frontend compatibility, not full TradingView runtime parity.

## Language profiles

| Profile | Entry point | Notes |
|---|---|---|
| Pine v6 | `ParseOptions(version=6)` | default strict frontend profile |
| Pine v5 | `ParseOptions(version=5)` | native static profile, not v6-compat warning mode |
| Legacy compatibility | `strict_v6=False` for older callers | retained for older OpenPine integrations |

Version-aware rules include bool semantics, numeric condition checks, declaration parameters, `dynamic_requests`, removed `strategy.* when` parameters, const-int division typing, and registry selection.

## Registry and signature coverage

The package includes versioned v5/v6 registries and official-reference snapshots. Name coverage and machine-readable signature readiness are checked separately:

```bash
python -m pine2ast.semantic.signature_coverage --version 5 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.semantic.signature_coverage --version 6 --fail-on-missing --fail-under-signature-ready-ratio 1.0
```

`missing_count = 0` means official names are represented. It does not mean every overload, qualifier rule, or runtime behavior is fully implemented.

## Release-feature matrix

The v6 release-feature matrix lives at:

```text
pine2ast/compatibility/release_features_v6_4_0.json
```

Statuses distinguish parser support, static validation, signature-only support, runtime-contract metadata, and unsupported diagnostics. The matrix is validated by `python -m pine2ast.release --root .`.

## Out of scope

- bar-by-bar execution;
- market data retrieval;
- broker emulator / fills / PnL;
- realtime rollback semantics;
- full TradingView UI behavior;
- online import resolution.
