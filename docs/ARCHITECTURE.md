# Architecture

Pine2AST is a frontend package. It accepts Pine Script source and produces AST JSON, diagnostics, semantic facts, and OpenPine metadata. It does not execute bars, fetch data, run strategies, or emulate TradingView runtime behavior.

```text
SourceNormalizer
  -> Lexer
  -> LayoutProcessor
  -> Parser
  -> AST schema validation
  -> SemanticPipeline
  -> inspect/openpine contracts
```

## Core modules

| Module | Responsibility |
|---|---|
| `pine2ast.source` | encoding, BOM/CRLF normalization, source-map helpers |
| `pine2ast.lexer` | tokenization, annotations, strings, comments, trivia support |
| `pine2ast.layout` | indentation, line wrapping, Pine-style layout tokens |
| `pine2ast.parser` | recursive-descent + Pratt expression parsing |
| `pine2ast.ast` | node model, schema validation, walking, serialization |
| `pine2ast.semantic` | profiles, scopes, type/qualifier facts, signatures, static checks |
| `pine2ast.inspect_contract` | stable in-process payload for downstream tooling |
| `pine2ast.openpine_contract` | Thin public façade for the OpenPine frontend metadata contract |
| `pine2ast.openpine_contracts` | Split contract extractors for collections, types, callables, requests, strategy, control flow, validation, and payload assembly |
| `pine2ast.compatibility` | release-feature matrix and compatibility metadata |

## Semantic pipeline

The 4.0 line keeps `SemanticAnalyzer` as the compatibility orchestrator, while statement/expression/validation/scope logic and static rules live in smaller mixins, passes, and helpers:

```text
declaration_index
scope_symbols
type_inference
qualifier_inference
builtin_validation
collection_validation
static_validation
strategy_context_validation
unsupported_feature_extraction
declaration_cardinality
```

The static layer validates rules that do not require runtime data: dynamic request blockers, declaration/profile rules, collection generic arity, collection method signatures, exported-library shape, `strategy.exit()` action requirements, const-int division typing, and UDT sort-field selectors.

## Boundary with runtime packages

Pine2AST emits metadata for runtime-facing features but does not perform runtime work:

- `request.*` calls are described, not executed.
- strategy order calls are described, not filled.
- collections and UDTs are typed, not allocated.
- history references are surfaced, not evaluated over bars.
- unsupported runtime-only behavior is reported through diagnostics or contract status.
