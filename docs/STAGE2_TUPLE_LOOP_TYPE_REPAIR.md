# Tuple and for-in result type repair

This repair is based on producer `89f07e70da0aa329d1442f2ace15ef6b9b7ee20f`.
It contains two separate functional changes, two new test files, and this document.
No existing test, expected result, catalog row, AST revision, consumer capability,
or runtime contract changes. The explicit method receiver qualifier work is excluded.

The existing compiler regression `test_tuple_from_loop_or_udf` must compile a
function returning `[i, i + 1]` from a range loop and retain its literal trace
`[7, 7, 7]`. Producer 89f07 instead reported `tuple<unknown,int>` and rejected its
own consumer bundle because expression type coverage was incomplete.

Phase 1 routes modern tuple element inference through the existing trusted child
callback, as binary and unary expressions already do. The shared tuple type rule
still constructs the result. Individual child inference can read lexical identifier
types and contextual callable proofs; a previously cached aggregate tuple type is
never trusted. The default legacy callback and v1–v4 dispatch are unchanged.

Phase 2 repairs the shared callable body walk: a `for ... in` element no longer
receives an unconditional `int` type. The existing `for_in_target_types` owner
provides the element and optional index types from the actual iterable type.
Range loop counters retain `int`. The existing walker, scope copies, contextual
work charging, and series qualifier remain in place; no loop body executes during
analysis and no second collection type resolver is introduced.

Both regressions have separate exact-source lineage controls. Published producer
7170736 accepted the range tuple, a float array's indexed tuple, and its scalar
element return with the expected types in v5/v6. Producer 89f07 rejected the two
tuple forms and incorrectly admitted the scalar float element as `int`. These
before observations remain archived; later results do not replace them.

The 42 new cases assert independently written types for range and nested loops,
local/global shadowing, mixed numeric tuples, contextual/defaulted calls, and
scalar/indexed array elements of int, float, and string types. Negative controls
retain unresolved-element and series-to-simple rejection. All 42 pass on Python
3.11 and 3.13. Black, Ruff, and the focused mypy checks pass.

Full local producer runs encounter the existing Windows `resource` import error
in the performance gate. Its collection failure remains recorded, and continued
runs retain the error while exercising the other tests. Full Linux acceptance
and the unchanged compiler suite are separate verification requirements; this
document does not claim either merely from the focused checks.
