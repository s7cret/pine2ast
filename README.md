# Pine2AST 5.0.0rc6

Pine2AST is a version-exact static frontend for Pine Script versions 1 through 6.

The frontend resolves one immutable `PineVersionContext`, selects one hash-bound
version pack, parses the source, performs binding/type/qualifier/overload analysis,
and emits complete Semantic Facts and a sealed consumer bundle.

## Support boundary

- Pine v1-v4: documented historical **static semantic snapshots**, reconstructed
  from official migration guides and archived manuals. These are not claimed as
  exhaustive historical reference-manual catalogs.
- Pine v5-v6: pinned static catalog snapshots with complete internal metadata.
- Runtime, broker emulator, market data, and TradingView oracle parity are outside
  Pine2AST and require downstream acceptance.

No source-version guessing, nearest-version fallback, v5-to-v6 rewrite, legacy
compatibility parser, or runtime-contract coupling is present.


## Pine version support in 5.0.0rc6 Stage 6

Pine2AST resolves the language version exactly once into `PineVersionContext` and carries the same version and catalog hash through parsing, static analysis, AST v2, Semantic Facts, and the consumer bundle.

| Pine | Version resolution | Verified static requirements | Internal catalog status | Runtime/TV parity |
|---:|---|---:|---|---|
| v1 | exact; missing annotation defaults to v1 | 20/20 | pinned historical snapshot | not claimed |
| v2 | exact `//@version=2` | 19/19 | pinned historical snapshot | not claimed |
| v3 | exact `//@version=3` | 15/15 | pinned historical snapshot | not claimed |
| v4 | exact `//@version=4` | 20/20 | pinned historical snapshot | not claimed |
| v5 | exact `//@version=5` | 21/21 | static-complete pinned pack | not claimed |
| v6 | exact `//@version=6` | 21/21 | static-complete pinned pack | not claimed |

The percentages above describe the audited **Pine2AST static frontend requirement set**. They do not turn internal symbol counts into an official TradingView coverage percentage and do not include runtime execution, data alignment, realtime rollback, broker fills, or TradingView-oracle equality.

See [`docs/VERSION_SEMANTICS_COVERAGE.md`](docs/VERSION_SEMANTICS_COVERAGE.md) and [`docs/STAGE6_SEMANTIC_REVIEW.md`](docs/STAGE6_SEMANTIC_REVIEW.md).
