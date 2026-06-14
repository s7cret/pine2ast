# Roadmap after 4.0.0

This roadmap keeps Pine2AST focused on frontend/static semantics. Runtime parity belongs to OpenPine runtime, PineLib, AST2Python, market-data, and backtest packages.

## 4.0.x stabilization

- Keep `pine.ast_contract.v1` stable.
- Keep `openpine.frontend.v1` additive and backwards compatible.
- Keep official-name and signature-ready coverage at 100%.
- Keep Python modules under the architecture budget unless a deliberate exception is documented.
- Add more oracle fixtures for real-world v5/v6 scripts.

## 4.1 targets

- Expand precise overload metadata for `request.*`, `strategy.*`, visual objects, arrays, matrices, maps, strings, math, and TA namespaces beyond broad machine-readable readiness.
- Add more negative fixtures for UDT constructors, enum usage, method receiver typing, and collection method forms.
- Move more static checks from compatibility mixins into independent passes without diagnostic-code churn.
- Make external reference-snapshot refreshes part of release preparation.

## Longer-term frontend work

- Formalize a typed AST or semantic IR if downstream lowering needs stronger guarantees than metadata facts.
- Split `SemanticAnalyzer` further into independent passes.
- Add property/fuzz tests for lexer/layout/parser recovery.
- Track TradingView documentation updates through explicit reference snapshots and release-feature entries.
