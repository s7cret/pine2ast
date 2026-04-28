# Current limitations v3.9

Pine2AST v3.9 / package 0.3.9 is a frontend contract-hardening release for `runtime_contract_v1.4`. It is not a TradingView runtime, broker, or generated-code executor.

## What v3.9 verifies

- AST schema stays at `1.0`; no schema drift was introduced.
- Every Pine2AST AST node kind is mapped in `tests/fixtures/runtime_contract_v1_4/frontend_node_mapping.json`.
- Schema-valid frontend features outside the runtime contract have stable diagnostics; imports currently emit `P2A1507` as a warning because online library resolution is not part of `runtime_contract_v1.4`.
- Semantic pass boundaries are named for declaration/indexing, scope/symbols, type inference, qualifier inference, builtin validation, strategy-context validation, and unsupported-feature extraction while preserving existing diagnostics.

## What v3.9 does not guarantee

- No new TradingView compile-oracle fixture is verified. The 30 v3.6 expansion fixtures remain `pending_external_oracle`.
- AST2Python generated runtime execution issues are outside Pine2AST scope and must be fixed downstream.
- PineLib runtime parity for request/security, visual objects, broker behavior, reference history, and full collection/UDT semantics remains downstream work.
- `builtins_v6.json` is a named supported subset/internal confidence matrix, not an official complete TradingView API snapshot.

## Required honest packaging

Use `oracle_expansion_pending` release suffix and `bash scripts/release_gate.sh --allow-pending-oracle` until fixture-specific TradingView evidence closes the pending oracle set.
