# Constant rounding facts and resolved builtin binding

This separate Stage 2 block fixes the producer constant-value owner. In Pine v5
and v6, `input.int(math.round(2.5))` previously carried default 2 because the
producer used Python's rounding rule. It now carries 3. The negative tie -2.5
becomes -2. Explicit precision selects a float result, including precision 0 and
negative precision. Reversed named arguments use their admitted parameter
positions rather than their order in the source.

## Primary rule and independent expectations

Reviewed 2026-09-08:

* The official [v5 reference](https://in.tradingview.com/pine-script-reference/v5/#fun_math.round)
  and [v6 reference](https://www.tradingview.com/pine-script-reference/v6/#fun_math.round)
  specify nearest rounding with “ties rounding up”, a float result when precision
  is supplied, and propagation of `na`.
* The [v4 April 2021 release notes](https://www.tradingview.com/pine-script-docs/v4/release-notes/)
  establish the precision overload's introduction. This block leaves the old
  unqualified v1–v4 constant-folding behavior unchanged; it does not backport the
  modern folding implementation.
* The [v5 migration guide](https://www.tradingview.com/pine-script-docs/v5/migration-guides/to-pine-version-5/)
  documents namespace and parameter-name changes. Binding follows the producer's
  exact symbol, overload and argument identities instead of spelling aliases.

The new test table contains manually specified neighboring integers and decimal
multiples. It does not import compiler or runtime outputs as expected values.
The independent host metadata table remains unchanged. The existing runtime
rounding implementation was inspected for a parity audit, but does not supply
test expectations or execute during producer folding.

## Owner contract

`SemanticFactBuilder` still owns constant facts. It consumes its already-resolved
`CallBindingFact`, requires a resolved stateless builtin call, and maps source
argument node identities to exact parameter positions. Unknown overloads,
missing or duplicated argument mappings, and unreviewed call forms yield no
constant evidence. Modern round additionally checks its exact parameter names
and overload arity. No user-defined call is folded merely because of its name.

`constant_numbers.round_constant` is a bounded numeric kernel, not an additional
source evaluator. It accepts finite numbers and uses decimal scaling with
integer quotient/remainder comparison, making the half-tie rule explicit.
Unchanged results and zero results from extreme precision are decided before
allocating powers. Oversized integers remain without constant evidence. An
explicit `na` precision is distinct from omission and cannot become an integer
rounding result.

The semantic-facts schema, catalog identities and version denominator are
unchanged. No runtime, compiler, generated artifact or checkpoint code changes
are included. Existing integer-division version rules are covered independently
for all six versions. Old tests and their expectations are not edited.

## Scope limits

This block does not implement constant UDF evaluation or global-initializer
qualifier sequencing. Other existing non-round cast/math folding retains its
operation semantics while requiring resolved call binding; that is not a claim
that Python bool/string conversion, remainder or every numeric edge equals Pine.
Those remain separate owner work. No full Stage 2 acceptance or TradingView-server
parity is claimed. Immutable source snapshots and full local test limitations
are recorded in the workspace review receipt.

## Reviewed variadic correction

Independent review of the first frozen revision found that strict binding stopped
emitting existing `min`/`max` constant values. The earlier catalog described only
the first argument; extra arguments had no parameter name, index or expected
type. Those programs already failed consumer-bundle admission before the rounding
change. The regression was in producer value facts, not a previously working
compiled input path.

The revised catalog marks the existing `values` parameter variadic only in v5
and v6. Every positional argument now receives the selected parameter's exact
name, index and numeric type. Constant folding consumes those admitted mappings,
checks original AST argument order and source binding form, and permits a repeated
parameter index only for an explicitly selected variadic parameter. Missing type
evidence and extra string or bool arguments do not receive constant evidence.
Canonical IDs, the version denominator and the four older catalog packs remain
unchanged. Catalog changes are frozen separately from the rounding source delta.

The official [v5 min reference](https://in.tradingview.com/pine-script-reference/v5/#fun_math.min)
and [v6 min reference](https://www.tradingview.com/pine-script-reference/v6/#fun_math.min)
describe positional numeric aggregates; `max` has the corresponding contract.
This correction preserves the internal parameter name `values`. It does not
introduce named `number0` or `number1` syntax: named variadic parity remains
unverified. The runtime manifest's variadic binding needs a separate owner review;
producer bundle admission alone does not establish generated execution parity.

The original four-file snapshot and failing independent probes remain immutable.
The revision adds independent numeric, nested-rounding, type-error and malformed
binding controls without changing the original 102 rounding cases or expectations.
