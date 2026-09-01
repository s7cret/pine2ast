# Stage 5 — Pine v1-v4 historical static semantics

Stage 5 extends the single-version kernel and canonical catalog to Pine v1-v4.
Each version has an independent hash-bound syntax/semantic policy and a sequential
delta from its adjacent version.

Implemented high-risk deltas include:

- v1 default identity, comma-separated statements, self/forward references,
  eager expressions, bool-to-number arithmetic, and `security()` lookahead-on.
- v2 control flow, user functions, reassignment, continued self/forward references,
  and mutable-security-expression rejection.
- v3 removal of self/forward references and bool-to-number arithmetic, tuple
  declarations, numeric conditions, and `security()` lookahead-off.
- v4 typed declarations, `var`, `varip`, arrays, compound assignment, explicit
  type for `na`, historical pre-namespace built-ins, unified `input()`, and lazy ternary.

The v1-v4 catalogs are conservative documented historical snapshots. The absence
of a complete official machine-readable historical reference manual prevents an
honest claim of exhaustive API parity. Unknown or unverified behavior remains
fail-closed.
