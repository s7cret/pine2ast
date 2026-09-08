# Contextual child types in arithmetic

This correction preserves the admitted type of a nested call when its parent is
an arithmetic or unary expression in Pine v5/v6. For example, with `float BASE=5`,
`f(x=BASE)=>x/2`, and `g(n)=>f()+n`, `g(1)` has type float and value 3.5. Previously
the parent could be typed int while its constant value was 3.5, admitting an
invalid `input.int(g(1))` and selecting an integer builtin overload.

The modern inference facade now supplies its context-aware child inference to
the existing operator type owner. The callback is an internal Python callable,
never a serialized producer hint. The operator rules themselves are unchanged.
Versioned integer division is handled before this route, and Pine v1–v4 continue
using the default callback-free path. No value evaluator, AST schema, library
context, compiler or runtime contract changes are included.

Only arithmetic and unary facade entrypoints use the new callback in this
bounded correction. Tuple/history changes are not included. Calls still use the
existing source-qualified context, recursion guards, cached admitted arguments,
and depth/work/cache limits; recursive child inference charges that owner.

The new 42-case matrix checks default arguments, explicit global arguments,
locally promoted returns, nested arithmetic, true integer division, input.int
rejection and exact math.abs overload selection in both supported versions.
The independent sixteen-case compiled metadata probe also verifies rejection of
integer inputs and the exact float defaults 2.5, 3.5 and 1.75.

Two remainder cases intentionally test only type evidence. Their independent
mathematical expected value is still 0.5; the existing pure constant visitor
does not fold remainder and its observed constant value remains unknown. The
original unpublished draft asserted value folding and failed; that draft and
before/after logs are preserved separately. This correction does not claim
modulo constant-fold support or mark those two value observations as passing.

The original context11 bundle and its independent failing receipt remain
immutable. This is a separate functional/test/doc delta over that source. The
exported-method A1 tests and their preimplementation failures are unrelated and
are not part of this publication delta.
