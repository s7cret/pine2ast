# OpenPine contract

Pine2AST 4.0 emits `openpine.frontend.v1` metadata for downstream OpenPine packages.

```python
from pine2ast import parse_code
from pine2ast.openpine_contract import build_openpine_contract_payload

result = parse_code(source)
payload = build_openpine_contract_payload(result, source_path="script.pine")
```

## Top-level sections

| Section | Contract | Meaning |
|---|---|---|
| `static_validation` | `openpine.static_validation.v1` | reusable static issues and rule summaries |
| `requests` | `openpine.requests.v1` | `request.*` calls, context arguments, dynamic/static blockers |
| `strategy` | `openpine.strategy.v1` | declarations, entries, exits, management and risk calls |
| `collections` | `openpine.collections.v1` | constructors, mutations, accesses, method-form signatures |
| `types` | `openpine.types.v1` | UDTs, enums, fields, constructors, field accesses |
| `methods` | `openpine.methods.v1` | user-defined method declarations/calls |
| `callables` | `openpine.callables.v1` | function/method/call binding facts |
| `control_flow` | `openpine.control_flow.v1` | loops, static iteration hints, history refs |

## Design rule

Contracts describe frontend facts and blockers. They do not allocate runtime objects, fetch symbols, schedule requests, or simulate strategies. Downstream packages should treat runtime-only metadata as a handoff contract, not as proof of execution support.


## Semantic snapshot sidecar

Pine2AST 4.0 also exposes `pine2ast.semantic_snapshot.v1` as a sidecar contract for CI/debugging. It is not a replacement for the AST or `openpine.frontend.v1`; it serializes semantic-model facts such as symbols, scopes, pass deltas, and node type/qualifier rows so downstream packages can compare frontend state without importing Pine2AST internals.

CLI:

```bash
pine2ast semantic-snapshot strategy.pine --json semantic.snapshot.json
pine2ast inspect strategy.pine --semantic-snapshot --json inspect.with-semantic.json
```


## Schema inventory

Pine2AST 4.0 exposes a compact structural schema inventory for downstream preflight checks:

```python
from pine2ast.openpine_contract import openpine_contract_schema, validate_openpine_contract_payload

schema = openpine_contract_schema()
issues = validate_openpine_contract_payload(payload)
```

CLI:

```bash
pine2ast contract-schema --json openpine.schema.json
```

The schema inventory is intentionally not a full JSON Schema for every nested row. It validates the stable outer shape, public section contracts, and additive compatibility rules.
