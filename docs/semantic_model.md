# Semantic model

`pine2ast` keeps syntax recognition and semantic validation separate.

## Scope and symbol pass

The parser emits AST nodes even for constructs that require later validation. `SemanticAnalyzer` then builds lexical scopes and symbol records for declarations, assignments, methods, functions, user-defined types, enums, loops, and local blocks.

## Validation responsibilities

Semantic validation owns checks that depend on symbol context or Pine rules beyond token grammar, including:

- `=` declaration vs `:=` reassignment rules;
- multiple declaration and shadowing diagnostics;
- method receiver and namespace/builtin call checks;
- forbidden local-scope builtins;
- Pine v6 boolean/history-reference constraints;
- builtin named-argument and qualifier validation from `builtins_v6.json`.

The parser intentionally does not reject these context-sensitive cases unless the source is syntactically impossible.

## Release-candidate boundaries

- `input` is not a declaration keyword or qualifier in the grammar.
- `[]` is modeled as `HistoryRefExpr`; array indexing is not claimed.
- Pine blocks are indentation/layout based, not `{}` based.
- The AST schema remains `1.0` for `v3.0-rc1`; any incompatible schema change requires an explicit schema-version bump.
