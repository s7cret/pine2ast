# Stage 2: simple/series typed function results

This separate wave follows the immutable typed-parameter-bound snapshot. It
propagates proven simple results of typed Pine v5/v6 functions into callers,
including locked-library calls. It keeps series results and does not specialize
untyped functions or change catalogue/runtime/compiler contracts.

## Primary rules (accessed 2026-09-08)

The official [v5 library rules](https://www.tradingview.com/pine-script-docs/v5/concepts/libraries/#qualified-type-control)
and [v6 library rules](https://www.tradingview.com/pine-script-docs/concepts/libraries/#qualified-type-control)
show a simple string result produced by joining simple string parameters. A
series contribution makes the calculated result series; exported results cannot
be weaker than simple. The [v6 function rules](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/#qualifier-keywords)
also distinguish a typed series parameter from an explicitly simple parameter,
and describe the result's dependence on the calculation's qualifiers.

Accordingly, `length(simple int n)=>n+1` must produce a simple integer. Its result
can supply the length of `ta.ema`, but cannot supply the const defval of
`input.int`. An explicit series parameter, a series guard, a price-series
calculation, or data retrieved from a reference must preserve series.

Mutable locals are deliberately unchanged. The official [v6 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/#mutable-variables-are-always-series)
states that mutable variables are series and documents a v5 const-mutable
exception. The current [variable declaration rules](https://www.tradingview.com/pine-script-docs/language/variable-declarations/#qualifier-keywords)
describe stronger qualifiers from reassignment values and control flow. These
sources do not establish a blanket simple-RHS relaxation for v5/v6 local aliases;
that earlier probe is not treated as affirmative parity evidence.

## Implementation and producer/consumer contract

The frontend computes result facts before its normal validating walk, using the
existing expression/type inference owner and the already inferred parameter
bounds. Each typed function can narrow once from the conservative series result
to a proven simple result. Thus forward dependency chains converge without the
old sixteen-iteration limit; recursive unresolved dependencies remain series.
Exact inferred return types accompany proven result facts.

The shared expression owner recursively preserves lexical identifier facts and
the guard qualifiers of if/switch return paths. Builtin calls with fixed series
returns remain series. Function symbols carry the result qualifier; existing
node facts and argument facts consume it without a new AST or consumer schema.
Source-written parameter qualifiers and exact call/overload identities remain
unchanged.

## Verification and remaining work

The initial new 42-case run recorded 24 failures and 18 passing negative
controls. Two further v5/v6 cases verify exact integer result types across 25
forward helpers. All **44** new cases pass on Python 3.11 and 3.13; all 56 cases
from the preceding parameter-bound wave remain green. No existing test or
expected value changed. Tests cover raw/imported functions, arithmetic, local
initializers, scalar builtins, forward helpers, branch-local values, series
guards, references, const-required controls and rejected series arguments.

Full runs each report **1359 passed, 10 failed, 1 collection error, 0 skipped**.
The failure node IDs match the preceding wave exactly. They are the already
recorded Windows source-newline/file-mode/symlink/no-follow/subprocess issues;
the collection error is the unavailable POSIX resource module. These local runs
do not replace Linux acceptance evidence. Ruff, Black and Mypy pass for the
changed semantic sources.

An actual linked compiler/runtime probe checks the independently authored result
`2+1=3` on every bar, use of that result as an EMA length, and exact continuation
after JSON checkpoint restore. Its EMA assertion concerns a settled constant
input, not warmup-seed parity. Evidence is saved under
`.runtime/evidence/callable-result-*` in the host workspace.

This wave retains conservative series results for const/input expressions and
zero-parameter functions. Completing their result types requires preserving the
exported-result minimum qualifier through library projection while allowing
ordinary functions their own rules. It must not infer library provenance from a
renamed identifier or weaken consumer source/fact verification. That is the next
separate linker/producer change. Methods, untyped per-call polymorphism and the
historical mutable-variable exception also remain separate work. Stage 2 is not
accepted by this change.
