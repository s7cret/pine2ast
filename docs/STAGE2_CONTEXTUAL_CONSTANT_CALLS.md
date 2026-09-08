# Contextual untyped calls and definition-visible constants

The existing independent 40-case metadata table contained eight remaining
failures: untyped argument calls, a nested call, a conditional argument and a
function reading an earlier constant global, each in Pine v5/v6. This block
provides the missing authoritative call-specific type/qualifier evidence and
definition-visible constant values. The ordinary compiler path now obtains the
table's unchanged literal defaults; it does not run an alternate evaluator.

`CallableContext` uses the existing SignatureResolver and callable body walker.
Untyped parameters inherit each actual call's qualified types; explicitly typed
parameters retain their established bounds. Exported and verified linked
functions retain their simple minimum. The normal typed declaration pass remains
authoritative: exhausting optional contextual analysis cannot erase a bound it
already established. Untyped contexts without sufficient evidence remain series.

Proofs bind the declaration, exact call and ordered parameter/argument identities.
Their type/qualifier maps and symbol snapshots are immutable. Cached body proofs
depend on the exact declaration and ordered qualified argument types, not on a
function spelling alone. The value visitor uses that same proof when consuming
numeric promotions, so an int and a float call do not share an aggregate numeric
type. The existing value cache retains separately tagged scalar arguments.

Globals are reconstructed in source order at the function definition. Only
ordinary immutable scalar declarations with admitted const initializers can
supply values. Reassignment disqualifies them. Function locals, later declarations
and caller locals cannot be borrowed. Nested global/default evaluation pushes
the declaration's own scope and an empty lexical value frame. Entire-body purity
and unsupported-operation rejection remain in force, including unselected paths.

The existing aggregate callable inference also consumes defaults selected by the
same authoritative proof. This fixes an existing coverage gap where `value(x=2)`
had a known call result but the body identifier retained unknown type. It does not
guess default positions or bypass arity, duplicate-name or scope validation.

Type/qualifier analysis executes no function body. It shares explicit limits of
64 call depth, 4096 work visits per root, 262144 visits per owner and 4096 cached
contexts. The existing bounded constant-value visitor keeps its own reviewed
limits. Exhaustion leaves unavailable value evidence; no callbacks run.

Reviewed 2026-09-08: the [current UDF rules](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/)
describe separate call scopes and untyped parameters inheriting their arguments'
types. The [v5 UDF rules](https://www.tradingview.com/pine-script-docs/v5/language/user-defined-functions/)
describe argument-dependent results, final-expression returns and optional
parameters. The respective [v5 type system](https://www.tradingview.com/pine-script-docs/v5/language/type-system/)
and [current type system](https://www.tradingview.com/pine-script-docs/language/type-system/)
establish the qualifier hierarchy and const calculations. No current rule is
silently backported to v1–v4; the earlier paths remain unchanged. The absence of a
TradingView-server oracle for the v5 metadata examples remains disclosed.

The 92 new tests cover literal expected values, call-specific numeric promotion,
source visibility, defaults, negative exact bindings, fixed qualifiers, mutation,
reference effects, budgets and proof immutability. Four earlier provisional
negative fixtures are corrected separately: the global now depends on bar_index
and the untyped call receives bar_index. Their original node IDs and every
assertion are retained; independent positives cover the previously negative
constant inputs. Their initial failures and the separate fixture snapshot are
preserved. No earlier immutable source bundle or expected table is rewritten.

This block changes no consumer schema, compiler evaluator, library projection,
runtime manifest or host implementation. Full local checks, inherited Windows
limitations, exact source composition and independent review belong to the
separate receipts. It does not claim complete Stage 2 acceptance.

## Global binding identity correction

The initial 92-case snapshot used a broad reassigned-name set in the global type
prepass. A different function-local or block-local variable with the same spelling
could therefore prevent a real global constant from being used. The original
snapshot and full checks are preserved. Twelve additional cases reproduce four
false rejections and retain eight actual-global-reassignment negatives.

One internal source inventory now associates module reassignments with exact
declaration identities, following source order and lexical block/loop bindings.
It skips function bodies, where assigning to a global is forbidden by the normal
language validator. Both the global type prepass and constant-value admission
consume the same immutable set of declaration identities. The ordinary body
walker's previous rule remains unchanged outside that trusted global prepass.
This inventory resolves no expression types, function calls or runtime values.
The revised block contains 104 new cases in total and retains the separate four
fixture-input corrections with every old assertion and node ID unchanged.
