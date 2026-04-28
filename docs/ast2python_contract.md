# AST2Python integration contract

AST2Python should consume `pine2ast inspect` as the high-level integration contract and the serialized
AST only when it needs statement/expression-level lowering. For v2.20, the inspect contract is frozen
as `pine2ast.inspect.optimizer.v1`; see `docs/optimizer_contract.md` for field definitions and bump
rules.

Key boundaries:

- The parser owns syntax recovery and AST construction.
- Semantic validation stays in the semantic layer.
- Optimizer/AST2Python consumers should gate on `ok`, `diagnostics`, and `unsupported_features`
  before lowering.
- The AST schema is not changed by v2.20.
