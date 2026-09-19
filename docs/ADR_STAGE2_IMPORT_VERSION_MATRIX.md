# ADR: Stage 2 library import version matrix (F2)

Status: accepted for linker admission. Origin-preserving *execution* of mixed
v5/v6 bodies remains a follow-on (F2.2 runtime/lowering), not a silent
`//@version` rewrite.

## Decision

| Consumer | Library | Result |
|---|---|---|
| 1–4 | any | `rejected_by_language` — no `import` |
| any | 1–4 | `rejected_by_language` — no `library()` |
| 5 | 5 | allowed |
| 6 | 6 | allowed |
| 6 | 5 | allowed — v6 may import v5 libraries |
| 5 | 6 | `rejected_by_language` — v5 cannot import v6 libraries |

Authority: TradingView Libraries documentation (`import` is explicit-version);
Pine v6 FAQ that v6 scripts can use v5 libraries and the reverse is not true.

## Non-goals of this change

- Do not rewrite library `//@version` to the consumer version.
- Do not evaluate library bodies with a process-wide `pine_version`.
- Do not treat a closed scalar-expression subset as full mixed-version support.
- Same-version linking remains the default path and must keep working.

## Identity

Each linked source records `pine_version` on every unit in the linkage receipt
so later lowering/runtime can bind origin policy without guessing from the root
script.
