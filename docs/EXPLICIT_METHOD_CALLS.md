# Explicit receivers for user methods

The existing source-anchored `MethodCandidates` owner now resolves a method in
function notation (`m(receiver, ...)`) as well as receiver-dot notation. The first
argument is checked by the same `SignatureResolver`, with the declaration's receiver
type and qualifier. Remaining arguments, named binding, defaults and overload
identities use the same path; there is no second function interpreter.

Pinned same-version Pine 5/6 libraries also admit `alias.method(receiver, ...)`.
The linker's typed preview records the exact original **callee range**, not merely
the start of a call: chained calls can share a start offset. Visibility is restricted
to the explicit source unit and its exported declarations. Local private helpers
remain accessible in their source unit. The selected callee is alpha-renamed without
wrappers, argument rearrangement or replacement of method bodies. Dot calls retain
their existing visibility and ambiguity rules.

The AST shape is unchanged. A compiler-only consumer capability,
`user_method_function_calls_v1`, is mandatory when explicit calls occur. Its presence
is derived from bounded AST data, not supplied call facts. Source-free verification
reuses the existing closed AST decoder and fresh semantic replay, including for the
otherwise unchanged AST 2.0 shape. Calls without this feature retain the old route.
The capability is not a PineLib operation or an invented catalogue builtin.

New tests cover versions 5/6, receiver types and qualifiers, named receivers,
namespace disambiguation, nominal identity, source visibility, recursive declaration
cycles, deterministic projection, preserved text/comments and fully resealed forged
facts. No methods are backported to versions 1–4.

Scope is the existing admitted method-declaration profile. Cross-version imports,
receiver defaults absent from that profile and complete mixed function/method
same-name overload semantics are **not** accepted by this change. Ordinary function
name lookup retains its previous priority; the new path does not silently reclassify
an ordinary function as a method. Full Stage 2 remains in progress.

Primary specification context, not external execution evidence:
- https://www.tradingview.com/blog/en/method-syntax-in-pine-script-36909/
- https://www.tradingview.com/pine-script-docs/v5/language/methods/
- https://www.tradingview.com/pine-script-docs/concepts/libraries/
