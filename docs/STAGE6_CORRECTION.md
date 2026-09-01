# Pine2AST 5.0.0rc6 — Stage 6 correction

This correction supersedes the earlier Stage 6 delivery.

Confirmed defects fixed:

- invalid duplicate key in `pyproject.toml`;
- historical `study()` regression for Pine v1-v4;
- stale v6 catalog materialization for `calc_on_every_history_tick`;
- reused diagnostic identifiers;
- version-semantic diagnostics bypassing `max_diagnostics`;
- aggregate artifact gates being calculated before the final static pass;
- parse metadata incorrectly naming all applicable rules as verified.

Verification boundary:

- the complete delivered test suite passes;
- Stage 4 and Stage 5 producer gates pass;
- wheel and sdist build and install cleanly;
- Pine v1-v6 minimal programs pass from the installed wheel;
- coordinated Ast2Python RC6 acceptance remains pending;
- merge and release remain unauthorized.
