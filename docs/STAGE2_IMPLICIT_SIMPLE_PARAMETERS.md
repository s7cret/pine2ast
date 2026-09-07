# Stage 2: typed function parameter bounds

This change infers the effective qualifier bound of typed Pine v5/v6 function
parameters before validating their bodies. It applies in the frontend to ordinary
and exported functions, including the ordinary declarations produced by the
locked-library linker. It does not change methods, untyped-parameter inference,
Pine v1-v4 behavior, catalogue membership, or runtime/compiler code.

## Source authority (accessed 2026-09-08)

The official [v5 library qualified-type rules](https://www.tradingview.com/pine-script-docs/v5/concepts/libraries/#qualified-type-control)
and [v6 library rules](https://www.tradingview.com/pine-script-docs/concepts/libraries/#qualified-type-control)
describe trying series first, then simple when the body requires a weaker value.
Their exported EMA example infers a simple integer length; a changing bar index
cannot supply it. Exported results cannot be const/input, and reference values
remain series.

The [v6 function qualifier rules](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/#qualifier-keywords)
state the same default for typed ordinary functions. Untyped parameters inherit
callsite qualifiers; explicit declarations constrain accepted values. The shared
v5/v6 frontend owner preserves these distinctions, so linked source does not need
a second inference policy after projection. The v5 library text is the direct
authority for the v5 exported example; it is not evidence of a historical v1-v4
backport.

## Contract and implementation

The source declaration `export smooth(float value,int count=2)=>ta.ema(value,count)`
previously failed with P2A1405/P2A2008 in both v5 and v6. The preserved initial
diagnostic evidence is `.runtime/evidence/implicit-simple-initial-trace.json` in
the host workspace. It now validates with `value: series float` and
`count: simple int`.

AST `Parameter.explicit_qualifier` still represents only written syntax. A
frontend-only model map stores the effective declaration bound. Body symbols,
default validation, callable inference and consumer argument binding read the
same bound. The consumer keeps its existing schema and exact builtin identities:
`pine:function:ta.ema`, `pine:function:ta.ema#canonical`,
`NAMESPACE_FUNCTION`; its length argument has expected/actual type `int` and
maximum/actual qualifier `simple`. Linked USER_FUNCTION calls retain their own
symbol plus `#signature`, and enforce this maximum for provided and defaulted
arguments.

The new owner associates arguments through the existing version-aware signature
resolver. It records typed parameter dependencies through arguments and lexical
initializer expressions. A finite worklist propagates required simple bounds
through helpers; each eligible parameter is processed at most once, including
cyclic dependency graphs. This is independent of the existing sixteen-iteration
return-type pass. Incompatible types, explicit series, a remaining series source,
and const/input-only requirements are still rejected by normal validation.
Reference parameters never become simple.

## Verification and limits

All 56 new tests pass on Python 3.11 and 3.13. They cover raw and linked functions,
positional/named/default arguments, literal/input acceptance and series rejection,
explicit bounds, type/const-required controls, lexical shadowing, references,
recursive-library rejection, a 25-helper dependency chain, and unchanged v1-v4
behavior. No old test or expected value changed.

Full parser runs each report **1315 passed, 10 failed, 1 collection error, 0
skipped**. The ten failure node IDs exactly match the preceding input-defval
baseline: pre-existing source newline checks and Windows file-mode, symlink,
no-follow and subprocess limitations. The collection error is the unavailable
POSIX `resource` module. These are not green Linux evidence.

A separate real compiler/runtime probe on both Python versions links two written
calls with an input length, checks independently chosen final constant-input EMA
values `[10.0, 20.0]`, and compares the entire restored checkpoint with continuous
execution. This checks settled constant inputs and restore, not the unresolved
modern EMA warmup seed. The reproducible probe and observations are in
`.runtime/evidence/implicit-simple-compiled-*`.

Ruff, Black and Mypy checks pass for the changed semantic files. The float17 and
input8 immutable source bundles remain intact, and this wave edits none of those
files. All six catalogue packs and their signature denominator remain unchanged.

This is a declaration-bound improvement, not full StatefulLanguage or Stage 2
acceptance. Follow-up probes preserved in
`.runtime/evidence/implicit-simple-alias-review-before.json` expose separate
existing limitations: simple-returning UDF calls are still classified as series,
and reassigned local aliases still acquire series. Exported methods and untyped
per-call polymorphism are also outside this change. Those owners require their
own source-backed changes and tests.
