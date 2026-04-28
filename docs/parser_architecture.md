# Parser Architecture (v3.5)

v3.5 modularizes the Pine v6 parser without changing the AST schema or accepted grammar.

## Public API

The stable import remains:

```python
from pine2ast.parser import Parser
```

`pine2ast.parser.parser.Parser` is now a thin facade composed from focused mixins. Existing callers should not import implementation mixins directly unless they are working on parser internals.

## Modules

- `pine2ast/parser/parser.py` — public `Parser` facade only.
- `pine2ast/parser/base.py` — parser state, parse orchestration, diagnostics, token helpers, lookahead predicates, `ParserResult`, and span utilities.
- `pine2ast/parser/expressions.py` — expression, prefix/postfix, primary, tuple expression, call/member/history-reference parsing.
- `pine2ast/parser/statements.py` — statement forms, blocks, variable/tuple assignment statements, conditionals, switches, loops, and function bodies.
- `pine2ast/parser/declarations.py` — import/type/enum/function/method declarations, parameter parsing, and type references.
- `pine2ast/parser/precedence.py` — precedence table used by expression parsing.

## Compatibility guardrails

This release is intentionally behavior-preserving:

- No AST schema changes.
- Pine block braces `{}` remain unsupported.
- Bracket postfix syntax (`expr[n]`) remains `HistoryRefExpr`; it is not array indexing.
- `input` remains parsed as an identifier/function namespace, not as a declaration qualifier.
- Semantic validation stays outside the parser.
- v3.3/v3.4 TradingView oracle evidence is preserved; v3.5 does not claim new Pine Editor evidence.

## Migration notes for contributors

When changing parser behavior, place the change in the smallest owning module and keep facade imports stable. Prefer adding or updating golden fixtures for any intentional AST change. If a future parser change needs an AST schema change, version it explicitly and document the compatibility impact in the changelog and audit.

Run the focused parser gates before broader release gates:

```bash
python -m pytest tests/unit/test_parser_* tests/integration/test_golden_ast_contract.py
python -m pine2ast test-fixture tests/fixtures/valid/basic_indicator.pine
```
