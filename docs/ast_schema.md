# AST schema

`Program` содержит:

```json
{
  "kind": "Program",
  "schema_version": "1.0",
  "language": "pine",
  "language_version": 6,
  "version": 6,
  "annotations": [],
  "declaration": {},
  "items": []
}
```

Каждый node содержит `kind` и `span`. Semantic-ссылки в JSON не образуют циклов; типы и квалификаторы хранятся в `SemanticModel.node_types` / `node_qualifiers`.

Основные группы nodes:

- declarations: `DeclarationStatement`, `ImportDeclaration`, `TypeDeclaration`, `EnumDeclaration`, `FunctionDeclaration`, `MethodDeclaration`.
- statements: `VarDeclaration`, `TupleDeclaration`, `Reassignment`, `ExpressionStatement`, `BreakStatement`, `ContinueStatement`.
- structures: `IfStructure`, `SwitchStructure`, `ForRangeStructure`, `ForInStructure`, `WhileStructure`.
- expressions: `Identifier`, `Literal`, `MemberAccessExpr`, `CallExpr`, `GenericInstantiationExpr`, `HistoryRefExpr`, `UnaryExpr`, `BinaryExpr`, `ConditionalExpr`.


## v0.1.1 schema extension

`GenericInstantiationExpr` represents Pine generic/template call callee suffixes, for example `array.new<float>()`.

```json
{
  "kind": "GenericInstantiationExpr",
  "base": {"kind": "MemberAccessExpr"},
  "type_args": [{"kind": "TypeRef", "name": "float"}]
}
```

This is an additive minor-schema node; existing node meanings are unchanged.


## v0.1.2 additions

- `TupleExpr`: expression-level tuple, e.g. `f() => [a, b]`, with `elements: list[Expression]`.
- Benchmark output schema v1: `schema_version`, per-file timing stages, `token_count`, `ast_node_count`, `diagnostic_count`, `peak_memory_mb`, and optional baseline regression fields.

## Schema validation helper

`pine2ast.ast.schema.validate_ast_schema(program)` validates the structural AST contract used by downstream consumers:

- Program-level `schema_version`, `language`, and `language_version` metadata.
- SourceSpan presence on every AST node.
- Basic span coordinate/order sanity.
- Node count and node kind histogram for integration reports.

CLI equivalent:

```bash
pine2ast schema-check file.pine --json schema.json
```

## v2.15.0 golden fixture contract

Golden AST regression fixtures are stored under:

```text
tests/fixtures/golden_ast/valid/
```

They mirror the curated valid fixture tree under:

```text
tests/fixtures/valid/
```

For each curated valid fixture there must be:

```text
<fixture>.ast.json
<fixture>.diagnostics.json
```

Invalid fixtures use companion diagnostic-code contracts:

```json
{
  "schema_version": 1,
  "expected_codes": ["P2A...."],
  "expected_min_severity": "ERROR"
}
```

Additional parser-recovery diagnostics are allowed for invalid fixtures, but every expected code must be emitted and at least one expected diagnostic must be ERROR/FATAL.

## Runtime contract v1.4 frontend bridge

Pine2AST schema remains `1.0` for this milestone: no node kind, field meaning, or JSON shape changed. The runtime bridge is an additive contract layer documented in `docs/runtime_contract_v1_4_frontend_mapping.md` and backed by `tests/fixtures/runtime_contract_v1_4/frontend_node_mapping.json`.

Guardrails kept unchanged:

- Pine blocks are indentation/layout based; `{}` is not accepted as a Pine block form.
- `input` is not a declaration qualifier.
- Square-bracket history references remain `HistoryRefExpr`; array/map access must be represented through modeled builtin/member calls until a future schema version explicitly adds another node kind.
- Semantic/runtime checks stay outside parser code.
