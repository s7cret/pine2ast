# Stage 2 scalar signature candidate

Baseline: `7107e797e32c360d2fce90a6416297ef2076351e`.
This is a bounded producer correction, not Stage 2 acceptance or builtin runtime parity.
The 60 original observations are preserved in
[stage2_scalar_signature_baseline.json](stage2_scalar_signature_baseline.json).
They are pre-fix observations, not expected results.

## Independent evidence

| Source | Audited contract |
| --- | --- |
| [Official v3 reference](https://fr.tradingview.com/pine-script-reference/v3/) | `round(x)` returns integer and has no precision signature. SMA/WMA take source and length. |
| [Official v4 reference](https://in.tradingview.com/pine-script-reference/v4/) | One-argument rounding returns integer; precision rounding returns float. `pow` takes base and exponent. |
| [Official v4 release notes, April 2021](https://www.tradingview.com/pine-script-docs/v4/release-notes/) | Adds precision to round. |
| [Official v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/) | Documents legacy-to-modern scalar parameter names, `nz(x,y)` renaming, conventional RSI simple-int length, and removal of the floating RSI ratio overload. A historical series-int second RSI argument selects the ratio overload through numeric promotion. |
| [Official v5 reference](https://in.tradingview.com/pine-script-reference/v5/) | NA replacement has simple/series numeric, color and boolean results. |
| [Official v6 reference](https://www.tradingview.com/pine-script-reference/v6/) | Round without precision, ceil and floor return int. Precision rounding returns float. Scalar math supports argument-dependent qualifiers; `na` has simple/series boolean results. |
| [Official v6 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/) | Boolean values cannot be NA and the NA builtins no longer accept them. |

Sources were inspected on 2026-09-07. Historical v1/v2 behavior continues the
existing explicit v3-to-v2-to-v1 static projection. There is no claimed
TradingView compile-oracle receipt for those versions or for this wave.

## Exact producer contracts

- `math.round#canonical` is one required numeric argument returning int.
  `math.round#overload:0` has two required arguments and returns float; precision
  is admitted only in v4-v6. Global historical spelling is `round(x, precision)`;
  modern spelling is `math.round(number, precision)`.
- Abs preserves int via a distinct integer overload; ceil/floor return int.
  Exp and sqrt require a numeric argument. Modern names use `number`; historical
  names use `x`. Pow retains `base` and `exponent`.
- Scalar math qualifiers follow the strongest supplied argument. NA testing and
  replacement have a simple floor. Numeric NA replacement still promotes int to
  float when necessary; a boolean/color replacement can determine an NA source's
  scalar type. Boolean NA remains rejected in v6.
- `float(x)` now has required numeric/NA argument evidence. A follow-up compiled
  NA probe exposed the frozen name-only entry: on all six versions parsing
  `plot(float(na))` succeeded but bundle validation reported
  `S4_CALL_ARGUMENT_TYPE_EVIDENCE`. The v6 reference explicitly supplies this
  numeric cast parameter; string conversion remains a separate function.
- Modern RSI length is simple int. Historical RSI retains `#overload:0` for
  conventional `x,y` and `#overload:1` for the ratio. Only the conventional
  overload requires persistent history. Legacy SMA/WMA and other canonically
  stateful builtins retain their state identity through namespace projection.
- Overload-only groups no longer acquire an invented zero-argument canonical
  signature. `SignatureResolver.candidate_entries()` gives detached audit rows
  from the same deduplication that resolution uses; it is not a runtime admission
  API. Shape comparison includes complete parameters, receiver, return type,
  return qualifier and return rules. Call-form projection remains the consumer's
  responsibility: legacy global calls are `FUNCTION`, modern namespaced calls
  are `NAMESPACE_FUNCTION`.

Frozen RC5 input files, version rules, historical projection inputs, canonical
symbol IDs and existing named semantic rule IDs remain unchanged. The existing
catalog builder produces new content-addressed definitions and pack hashes for
the corrected contracts. New named return rules describe scalar overload
selection; existing NA return-rule identity is retained. The report does not
reinterpret old content hashes as the corrected behavior.

## Validation and review split

`tests/test_scalar_signature_contract.py` adds 372 independently specified tests
covering v1-v6 positive cases, negative arity/type/names, version boundaries,
overload identity, qualifiers and statefulness. No expected data comes from a
runtime implementation or a generated catalog.

On Python 3.11 and 3.13, the new suite plus existing NZ/generic and Stage 2/3/5
regressions passed: **633 tests on each interpreter**. An additional 3.11
focused semantic/catalog/coverage run passed **67 tests**. The
regression/unit/nominal/library run passed 170 tests and encountered six existing
Windows environment restrictions: five POSIX no-follow/symlink cases and one
release-gate directory/subprocess case. These checks are not skipped or weakened;
the full mandatory gate requires the Linux CI environment.

The catalog generator `--check` reports no drift and zero migration losses.
Black, Ruff and targeted mypy validation cover the changed Python owner files.

Two old test-input assumptions must be reviewed separately:
`tests/test_generic_collection_fact_identity.py` and `tests/test_nz_return_rule.py`
used modern named NZ parameters in v1-v4. Their input spelling now follows the
official migration table; expected types and collected node IDs are unchanged.
The latter now asserts successful parsing before inspecting type evidence.
