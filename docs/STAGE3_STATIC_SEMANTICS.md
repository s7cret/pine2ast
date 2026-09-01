# Stage 3 — version-bound parser and static semantics

Stage 3 binds lexer, parser, semantic passes, catalog, policies and emitted facts to
one immutable `PineVersionContext`. The caller cannot override the source version.
Every policy validates both `pine_version` and `catalog_hash` before use.

The production gate covers the exact pinned v5/v6 catalog snapshot. Every active
symbol has a stable `symbol_id`; every parametric return has an explicit
`return_rule_id`; every overload has an `overload_id`; every operator has a static
rule ID. This is deliberately described as **100% completeness of the pinned,
hash-bound catalog**, not as complete parity with every TradingView runtime feature.

`pine.semantic_facts.v1` contains deterministic facts for every AST node, including
resolved type, qualifier, nullability, symbol/overload identity, coercions, scope,
statefulness, call form, receiver type and version-specific semantic rule IDs.

Frontend lineage is sealed as:

`source manifest -> AST -> semantic facts -> support profile -> frontend artifact`.

No artifact invents a Git commit. Unpinned local builds explicitly use
`source_state=UNCOMMITTED_LOCAL_BUILD` and `commit=null`.
