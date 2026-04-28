# Diagnostics contract

pine2ast diagnostics are part of the optimizer-facing contract. Codes are stable within the
`P2A` namespace and should not be renamed or repurposed between releases.

## Payload shape

Every diagnostic JSON object emitted by `parse`, `validate`, `diagnostics-report`, `inspect`,
SARIF conversion inputs, and golden helpers uses the same fields:

- `severity`: `INFO`, `WARNING`, `ERROR`, or `FATAL`.
- `code`: stable machine-readable code such as `P2A1102`.
- `message`: human-readable explanation. Wording may be clarified, but code meaning remains stable.
- `span`: source location with start/end line and column when available.

## Stability rules

- Add new codes for new rule classes; do not recycle an old code for a different rule.
- Keep parser/layout checks in parser/layout layers and semantic checks in `SemanticAnalyzer`.
- Invalid fixture contracts assert expected codes, not exact recovery noise, because parser recovery may
  legitimately add secondary diagnostics.
- ERROR/FATAL diagnostics make `ParseResult.ok` false; WARNING diagnostics do not.

## v2.17 semantic matrix

The v2.17 stabilization matrix locks these rule families:

| Rule family | Stable code(s) |
| --- | --- |
| `=` declaration vs `:=` reassignment | `P2A1102`, `P2A1103` |
| const reassignment | `P2A1104` |
| Pine v6 bool contexts and `na` bool rejection | `P2A1201`, `P2A1202`, `P2A1203` |
| history reference validation | `P2A1301`, `P2A1302`, `P2A1303`, `P2A1304`, `P2A1305` |
| break/continue placement | `P2A1701` |
| nested functions/methods and method receivers | `P2A1601`, `P2A1602`, `P2A1603` |
| import alias redeclaration | `P2A1102` |
| strict unknown builtin namespace members | `P2A1506` |
| unknown namespaces/objects | `P2A1101` |

See `tests/unit/test_semantic_rule_matrix_v2_17.py` and
`tests/integration/test_invalid_diagnostics_contract.py` for executable contract coverage.
