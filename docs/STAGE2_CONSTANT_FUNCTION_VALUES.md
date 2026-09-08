# Bounded constant values for pure user functions

This separate producer block adds value evidence to already admitted const
user-function calls in Pine v5 and v6. For example, `value()=>math.round(2.5)`
now gives `input.int(value())` default 3. It changes no call qualifier, language
version, catalog identity, consumer schema, compiler evaluator or runtime API.

The existing `SemanticFactBuilder._evaluate_const` remains the expression owner.
The new helper stores only bounded work, cache and lexical-frame state. A call
must have exact resolved USER_FUNCTION identity and overload, a matching source
declaration span, completed const call and declaration qualifiers, and a supported
scalar result. Exported and verified linked results retain their simple minimum
and cannot acquire constant evidence.

Before computing a value, the owner checks the entire transitive function body
and all defaults, including unused branches. Its initial pure subset comprises
finite numeric and bool literals, immutable ordinary locals, numeric arithmetic
and comparisons, exact boolean operations, ternaries, reviewed numeric builtins,
and other admitted pure constant functions. Binding uses exact argument nodes,
parameter positions and declaration-default ASTs. Lexical names select only
bindings established in the current function frame; no global value lookup is
performed. Frames, caches and values do not mutate the AST or semantic model.

The initial block rejects structural if/switch, loops, reassignment, persistent
declarations, reference operations, stateful calls, histories, unverified bool or
string conversion and remainder. Unsupported code cannot be hidden in an unused
branch or before a literal return. Earlier v1–v4 folding remains unchanged.

Limits are shared across nested operations: 64 function frames, 4096 work visits
per root request, 262144 visits per builder, and at most 4096 total cached purity
and value entries. Expression nesting and integer size are also bounded. Cycles
and exhausted limits leave the value unknown, without invoking callbacks. Cache
keys include exact declaration identity and tagged scalar arguments.

## Authority and evidence boundary

Reviewed 2026-09-08: the [current UDF documentation](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/)
describes result qualifiers from calculations and arguments, independent call
scopes, and the prohibition on recursion. The [v5 UDF documentation](https://www.tradingview.com/pine-script-docs/v5/language/user-defined-functions/)
describes returns from the final body value and their dependence on each call's
arguments. Together with the [v5 const-expression rule](https://www.tradingview.com/pine-script-docs/v5/language/type-system/),
this supports the historical pure-const inference. A TradingView-server oracle
for these v5 cases remains unavailable; that limitation is preserved.

The independent frozen 40-case metadata table is unchanged. This block closes
exactly four missing-value cases, improving normal compiled metadata checks from
28 to 32 matches. Six cases still need callsite qualifier inference for untyped
parameters; two need global initializer sequencing. This block does not bypass
those producer gates or claim full Stage 2 acceptance.

New tests use literal expected numbers, independent versioned integer division,
lexical isolation, exported/linked negatives, malformed identity/default evidence,
transitive cycles, and resource exhaustion. Existing round and variadic tests
and their expectations remain unchanged. Immutable before/final snapshots and
the full local Windows limitations are recorded in separate review receipts.

## Numeric promotion correction after independent review

The first frozen revision lost an admitted int-to-float conversion while moving
values through a typed local or a selected ternary branch. In Pine v5,
`float n=5` followed by `n/2` consequently produced constant 2 instead of 2.5.
A mixed int/float ternary followed by division had the same defect.

The revised visitor consumes the existing shared owner's exact expression type
before returning a value to its parent operation. When that admitted type is
float, an integer value widens to float. No new type or coercion resolver is
introduced. Explicit int casts and v5/v6 division rules stay intact. Non-finite
or unrepresentable conversions remain without value evidence. This follows
the numeric promotion described in the official [v5 type system](https://www.tradingview.com/pine-script-docs/v5/language/type-system/)
and [current type system](https://www.tradingview.com/pine-script-docs/language/type-system/).

The separate regression table covers typed locals, ternary branches, aliases,
nested returns/calls, builtin results, explicit int controls and nonconst defaults.
Original UDF94 tests and all round/variadic expectations are unchanged. The
original UDF4 snapshot and its failing independent observations remain preserved;
the correction is isolated from the unfinished contextual-call/global work.
