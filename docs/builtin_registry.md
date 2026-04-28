# Builtin registry notes

`pine2ast/semantic/builtins_v6.json` is a named supported subset/internal confidence matrix used by semantic analysis. It is intentionally not a claim of complete TradingView/Pine official API coverage or an official TradingView snapshot.

## Schema validation

`load_builtin_registry()` validates the JSON before exposing it. The validator checks required top-level sections, function entry identity, required function fields, supported function metadata keys, return and parameter type references, parameter array shape, duplicate parameter names, variable type/qualifier shape, supported scopes/kinds, qualifier bounds, removed/deprecated version markers, and overload shape when `overloads` is present.

Use `validate_builtin_registry(registry)` in tests for corrupt or generated registry payloads. The validator is intentionally stricter than the runtime analyzer: malformed compatibility metadata should fail at load time instead of weakening semantic diagnostics.

## Coverage taxonomy

`builtin_registry_coverage_report()` separates coverage into explicit buckets:

- `internal_expected` / `missing_internal_expected`: curated project confidence set. Missing entries are actionable regressions/backlog.
- `official_unmapped`: known official Pine members not yet modeled in `builtins_v6.json`. These do not make internal coverage fail.
- `known_deferred`: known official or quasi-official surface intentionally deferred.
- `known_unsupported`: known surface intentionally unsupported by this parser/semantic layer.

The report keeps legacy fields (`expected_count`, `missing_expected`, `coverage_ratio`) as aliases for the internal expected snapshot only. A green `missing_expected=[]` means the project snapshot is closed; it does **not** mean official Pine builtin coverage is complete.

## v2.19 compatibility-layer notes

v2.19 expands named/type-aware metadata for common `label.*`, `box.*`, and `table.*` setters so strict builtin namespace and signature validation can catch unknown names, wrong argument counts, wrong argument types, and qualifier violations without moving semantic checks into the parser.

`any` and `unknown` returns remain in the registry for collection/generic surfaces that are not fully specialized yet. They are compatibility placeholders and official backlog, not fabricated TradingView signatures; see coverage output `official_unmapped` and changelog notes for the honest mapping status.
