# Grammar notes

Pine Script v6 blocks are indentation-based. `{}` blocks are intentionally not part of valid UDT/enum/function body syntax.

Important decisions:

- `[]` is parsed as `HistoryRefExpr`, not array indexing.
- `input` is not a declaration qualifier keyword; `input.*()` yields an input qualifier during semantic inference.
- `indicator`, `strategy`, `library` are parsed as call expressions and upgraded to `DeclarationStatement` only in global declaration position.
- Parser syntax and semantic validation are separate layers.


## v0.1.2 grammar hardening

```ebnf
tuple_expr := "[" expr ("," expr)* "]"
```

`tuple_expr` is accepted only in expression position. `tuple_decl` remains a statement-level construct when the bracketed target list is followed by `=`.

`pine2ast bench` records stage-level timings for normalizer, lexer, layout, parser, and semantic analyzer.

## v0.2.10 strategy namespace semantic policy

Pine2AST separates strategy namespace constants from strategy runtime state:

| Script context | Usage | Pine2AST expectation |
|---|---|---|
| `indicator()` | `strategy.long` / `strategy.short` | allowed as direction constants |
| `library()` | `strategy.long` / `strategy.short` | allowed as direction constants |
| `indicator()` | `strategy.equity`, `strategy.position_size`, `strategy.closedtrades.*`, `strategy.opentrades.*` | semantic error `P2A1505` |
| `strategy()` | `strategy.closedtrades.entry_price(0)`, `strategy.closedtrades.entry_comment(0)`, `strategy.opentrades.entry_comment(0)` | allowed and typed |

Compile-oracle fixtures live in `tests/fixtures/compile_oracle/strategy_namespace/metadata.json`.
Their `status` is intentionally `pending_oracle` until a TradingView compile check can update it.

## v2.11 semantic note: flow-sensitive `na()` narrowing

The parser keeps Pine source structure unchanged, but SemanticAnalyzer now records
scope-local non-`na` facts for common guards:

```pinescript
if not na(x) and x > 0
    y = x + 1

if not na(obj.field)
    y = obj.field

if na(x)
    y = 0
else
    z = x + 1
```

These facts are exposed in `SemanticModel.non_na_paths` and in
`semantic-report` scope rows as `non_na_paths`. Symbol-only facts remain
available via `Scope.non_na_symbols` for backward compatibility.

## v2.13 typed builtin constants note

Starting with v2.13, the builtin registry keeps a larger typed-constant snapshot for
Pine v6 enum-like namespaces. Examples include `display.*`, `line.style_*`,
`label.style_*`, `barmerge.gaps_*`, `barmerge.lookahead_*`, and request data
field constants such as `dividends.gross`, `earnings.actual`, and
`splits.numerator`.

The parser still treats these names as normal member-access expressions. The
SemanticAnalyzer resolves them via `builtins_v6.json`, so AST schema remains
stable while argument validation becomes more precise.
