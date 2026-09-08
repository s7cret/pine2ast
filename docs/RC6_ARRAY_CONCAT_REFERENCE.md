# Array concatenation reference and named receiver contract

The specialized collection signature now retains the first array's concrete
type as the result of `array.concat`. Function arguments are `id1` and `id2`;
the method payload is `id2`. This matches the existing version catalog and
requires no catalog row or availability change. Pine v4's documented example
pushes through the returned ID and observes the mutation in the first array:
https://www.tradingview.com/pine-script-docs/v4/essential/arrays/#concatenation

Namespace collection calls infer the receiver from its named argument (`id1`
for concat, otherwise `id`) or the first positional argument. The existing
binding validator still checks duplicate, unknown, missing and ill-typed
arguments. This also repairs reversed named array, matrix and map calls.

The new 84 tests cover function calls in v4/v5/v6, methods in v5/v6, concrete
int/float/bool/string arrays, named argument order and invalid bindings.
All prior tests and fixtures remain unchanged. Both local Python versions
pass the 93 focused tests (84 new plus 9 existing). Full local collection has
1677 JUnit rows: 1666 pass, 10 existing Windows failures and one existing
resource-module collection error. The Linux inventory is expected to contain
1679 tests; this document does not claim a completed joint Linux run.

Runtime reference identity, mutation and rollback are verified separately in
the runtime owner. This producer change introduces no runtime evaluator,
reference implementation, compiler workaround or catalog support expansion.
