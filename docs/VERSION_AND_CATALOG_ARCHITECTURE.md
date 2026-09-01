
# Pine version and catalog architecture (5.0.0rc6)

`PineVersionContext.pine_version` is the only Pine language-version value carried
through the frontend. It is resolved once from `//@version=N`; an absent annotation
resolves to Pine v1 exactly as TradingView specifies. Callers may assert an expected
version but cannot override the source.

The version catalog has one canonical source:

- `catalog_source/symbols.jsonl` — stable symbol identities;
- `catalog_source/semantics.jsonl` — content-addressed semantic definitions;
- `catalog_source/deltas/v1..v6.jsonl` — sparse, real changes only;
- `pine2ast/catalog_data/packs/pine_v1..v6.pack.json` — deterministic runtime packs.

Pine v1–v4 packs are explicit `HISTORICAL_STATIC_SNAPSHOT` placeholders and are not claimed
as production parsers. Pine v5/v6 packs are losslessly migrated from the exact RC5
registries. The old registry files are retained only under `catalog_migration_inputs`
for audit and are excluded from the wheel.

Pine2AST owns parse/bind/type/qualifier/overload/static-diagnostic facts. It does not
store Ast2Python, PineLib, simulation, or live-support decisions in its catalog.
