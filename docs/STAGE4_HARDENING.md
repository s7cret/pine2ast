# Pine2AST 5.0.0rc6 — Stage 4 hardening

Stage 4 makes producer correctness reviewable. It does not convert Pine2AST into a
runtime and does not claim TradingView execution parity.

## Hard gates

- deterministic catalog drift check;
- positive, negative and v5/v6 differential corpus;
- deterministic version-resolution fuzzing;
- strict producer bundle and hash lineage validation;
- contract mutation gate;
- portable time/memory/scaling ceilings;
- legacy-path and forbidden-symbol hygiene.

## Consumer boundary

`pine2ast.consumer_bundle.v1` carries one Pine version context, AST v2, canonical
semantic facts, source spans and hashes. Pine2AST can prove producer conformance but
cannot self-authorize Ast2Python. Coordinated acceptance remains
`PENDING_COORDINATED_CONSUMER` until the exact Ast2Python 5.0.0rc6 consumer validates
the supplied vector.
