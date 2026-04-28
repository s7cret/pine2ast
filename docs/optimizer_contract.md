# Optimizer / AST2Python contract (v2.20 freeze)

`pine2ast inspect` is the stable JSON handshake for optimizer and AST2Python consumers.
The current contract remains additive-compatible v1:

- `schema_version`: `1`
- `contract`: `pine2ast.inspect.optimizer.v1`
- `producer` / `tool`: producer name, package version, and contract id
- `source`: input path metadata (`path`, `name`)
- `script`: top-level Pine declaration metadata (`type`, `title`, `pine_version`)
- `ok`, `diagnostics`, `unsupported_features`: parse/semantic status and machine-readable blockers
- `inputs`: extracted `input.*` declarations with defaults/ranges/options
- `strategy_calls`: `strategy.*` calls with name, arg count and span
- `request_calls`: `request.*` calls with name, arg count and span
- `plots`, `alerts`, `drawings`: visual/alert integration calls
- `dependencies`: imports, import aliases, namespaces, builtin/user/method/UDT/external/unknown calls

## Versioning policy

Do not remove or rename v1 fields without bumping the inspect contract id and schema version.
Additive fields are allowed in v1 when they do not change existing field meaning. AST schema
changes remain governed by `Program.schema_version` / `docs/ast_schema.md`; the inspect contract
must not smuggle AST-shape changes without the explicit AST schema bump.

A contract bump is required for any of these changes:

- changing field types or nullability for existing fields;
- changing `[]` expression semantics (history references remain `HistoryRefExpr`, not array indexing);
- changing declaration keyword/qualifier treatment such as making `input` a declaration keyword;
- moving semantic validation into parser recovery;
- adding incompatible Pine block syntax such as `{}` blocks.

## Unsupported features

`unsupported_features` is derived from emitted diagnostics. It is intentionally a consumer-facing
summary, not a separate parser or semantic rule engine. A script can still include full diagnostics
for recovery detail while `unsupported_features` lists the blocking ERROR/FATAL items that downstream
optimizer code should treat as unsupported.

TradingView compile-oracle status is external to this JSON contract. When Pine Editor access is not
available, release artifacts must stay `oracle_pending` and must not claim oracle verification.

## Golden fixtures

v2.20 freezes executable snapshots under `tests/fixtures/optimizer_contract_v2_20/` covering:

- basic strategy inputs;
- TP/SL/trailing-style strategy exits;
- `request.security` tuple payloads;
- multiple input types and enum-style options;
- array/map usage;
- plot/alert/drawing mixes;
- import alias external calls.

Run:

```bash
python -m pytest tests/integration/test_optimizer_contract_v2_20.py
```
