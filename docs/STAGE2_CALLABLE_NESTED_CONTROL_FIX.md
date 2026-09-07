# Stage 2: nested control qualifier correction

This P1 correction supersedes the nested-control behavior of the original
callable-result six-file snapshot, which remains preserved as historical
evidence. It does not include the proposed exported-result minimum context API.

Independent review reproduced a false admission in v5 and v6: a function with a
simple outer condition and a nested `if bar_index>0` or `switch bar_index` was
classified as returning simple. The result incorrectly supplied the simple-only
length of `ta.ema`. Direct series conditions and nested ternaries already rejected.
The original review and exact before observations remain in the host workspace's
`.runtime/evidence/callable-result-initial-independent-review.json` and
`callable-nested-control-before-py311.json` / `py313.json`.

The cause was using a type-inference utility that recursively flattens return
leaves. Such leaves preserve value types, but omit conditions and loop behavior.
The new shared `structural_qualifier_sources` utility returns immediate value
roots and guards. Recursive qualifier inference therefore sees each inner
if/switch condition and each for/for-in/while expression's existing qualifier.
The original type-only `returned_expressions` implementation is unchanged.

The parameter-constraint owner uses the same utility. This preserves dependencies
on nested guards when it infers a simple bound. A typed boolean `choose` used
inside a nested expression supplying EMA length must be simple: an input argument
is permitted, while a series argument is rejected. No qualifier is weakened and
no loop qualifier, version gate, runtime state, catalogue or compiler API changes.

## Exact lineage

Isolated `python -I` probes loaded each explicitly selected snapshot tree:

| Source snapshot | input `choose` caller | series `choose` caller | parameter maximum |
| --- | --- | --- | --- |
| input8 + implicit8, without callable6 | rejected | rejected | series |
| original callable6 added | accepted | incorrectly accepted | series |
| this P1 correction | accepted | rejected | simple |

These observations match on Python 3.11 and 3.13. The active input/implicit-only
candidate therefore had a conservative false rejection for this sibling case;
its behavior must not be described as the callable6 false admission. The
reproducible script and six receipts are
`.runtime/evidence/callable-sibling-lineage-*`.

## Verification

The independent new matrix initially reported **40 failed, 16 passed**. It now
passes all **56** cases on both Python versions. Cases cover raw/imported
functions, expression/predicate switch, else-if, repeated nesting, branch-local
guard aliases, for/for-in/while values, valid simple controls, exact integer
facts, and the nested guard's inferred parameter bound. Negative cases check the
specific qualifier diagnostic and consumer rejection, with no unrelated syntax
or type error accepted as a substitute.

Focused suites pass **191** cases on each Python: the new 56, the prior 44
callable-result cases, the prior 56 parameter-bound cases, and 35 existing loop
type-evidence cases. Full parser suites each report **1415 passed, 10 failed,
1 collection error, 0 skipped**. The ten failure node IDs exactly match the
preceding run, and every previous test node ID is preserved. The existing Windows
source-newline/file-mode/symlink/no-follow/subprocess failures and missing POSIX
resource collection dependency still require real Linux checks.

The original independent eight-trial probe now rejects every series case, with
actual qualifier series, on both Python versions. Ruff, Black and Mypy checks
pass for the correction. Existing tests, assertions and all prior frozen bundles
are unchanged. The correction is separate from exported-result floor design and
does not constitute full Stage 2 acceptance.
