# Optimizer / AST2Python inspect contract

`pine2ast inspect` emits the stable integration payload for downstream optimizer and AST2Python consumers.

```bash
python -m pine2ast inspect tests/fixtures/inspect_contract/optimizer_strategy.pine --json inspect.json
```

Contract fields:

- `schema_version`: currently `1`.
- `contract`: `pine2ast.inspect.optimizer.v1`.
- `producer` / `tool`: producer name, package version, and contract id.
- `source.path` / `source.name`: caller-provided path metadata, for traceability only.
- `script`: top-level declaration type/title/Pine version when available.
- `ok`, `unsupported_features`, and `diagnostics`: parser/semantic status and downstream blocker summary.
- `inputs`: extracted `input.*` declarations with literal defaults/ranges/options.
- `strategy_calls`, `request_calls`, `plots`, `alerts`, `drawings`: downstream-relevant calls with `name`, `arg_count`, and source span.
- `dependencies`: imports, aliases, namespaces, builtin calls, user calls, methods, UDT constructors, external calls and unknown calls.

Committed contract fixtures:

- Source: `tests/fixtures/inspect_contract/optimizer_strategy.pine`
- Expected JSON: `tests/fixtures/inspect_contract/optimizer_strategy.inspect.json`
- v2.20 snapshot suite: `tests/fixtures/optimizer_contract_v2_20/`

The fixture suite covers strategy, inputs, request, alert, drawing, external import call, array/map namespace usage and plot extraction. See `docs/optimizer_contract.md` for the v2.20 freeze and schema-bump policy.
