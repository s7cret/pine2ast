# Pine2AST — ТЗ 1.7 на остаток доработок после v2.9.0

**Версия документа:** 1.7  
**Дата:** 2026-04-27  
**База кода:** `pine2ast_interpipe_v2_9_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_8_0`

## 1. Статус v2.9.0

В v2.9.0 закрыты следующие пункты из ТЗ 1.6:

1. Дедупликация повторных diagnostics на стыке parser recovery и semantic fallback.
2. Добавлен `ParseOptions.strict_builtin_namespaces`.
3. `P2A1506 UNKNOWN_BUILTIN_MEMBER` теперь:
   - `INFO` в default mode;
   - `ERROR` в strict builtin namespace mode.
4. Добавлена CLI-команда `builtin-coverage` и API `builtin_registry_coverage_report()`.
5. Улучшено forward return-shape inference для user functions:
   - literals;
   - ternary;
   - if/switch structures;
   - numeric `int|float -> float`;
   - tuple branch merge по arity.

Активный stdlib runner: `147 passed`.

## 2. Остаток P0/P1

### P0 — полный corpus/quality rerun в чистом окружении

В текущей среде полный `validate-corpus` был сорван фоновой проверкой файлов `/mnt/data`. Нужно повторить в чистом окружении без file-prefetch side effects:

```bash
python -S tools/run_tests_no_pytest.py
python -S -m pine2ast.cli validate-corpus tests/fixtures/real_world --json CORPUS_RUN_v2_9_0.json
python -S -m pine2ast.cli quality-gate tests/fixtures/real_world --json QUALITY_GATE_v2_9_0.json
python -S -m pine2ast.cli schema-check tests/fixtures/real_world/01_ma_indicator.pine --json SCHEMA_CHECK_v2_9_0.json
```

DoD:
- `file_count=300`;
- `error_count=0`;
- quality gate `ok=true`;
- schema report `ok=true`.

### P1 — расширение builtin registry по coverage report

Использовать `BUILTIN_COVERAGE_v2_9_0.json` как backlog generator.

Приоритет:
1. `ta.*`: momentum/trend helpers (`rsi`, `atr`, `crossover`, `crossunder`, `change`, `highest`, `lowest`, `valuewhen`).
2. `math.*`: scalar math helpers (`abs`, `round`, `floor`, `ceil`, `sqrt`, `pow`, `log`, `exp`, trig).
3. `str.*`: text helpers (`contains`, `startswith`, `endswith`, `replace`, `split`, `length`).
4. Drawing namespaces: `line`, `label`, `box`, `table`, `polyline`.
5. Full `strategy.closedtrades.*` / `strategy.opentrades.*` accessor list.

DoD:
- coverage report показывает меньше `missing_expected`;
- default mode остаётся soft;
- strict mode корректно падает только на реально unknown members.

### P1 — compile-oracle metadata для strategy namespace policy

Нужно подтвердить policy через TradingView compile oracle fixtures:

| Context | Usage | Expected |
|---|---|---|
| indicator | `strategy.long` | allowed as constant |
| library | `strategy.long` | allowed as constant |
| indicator | `strategy.equity` | forbidden |
| library | `strategy.equity` | needs oracle confirmation |
| strategy | `strategy.closedtrades.entry_price(0)` | allowed |
| indicator | `strategy.closedtrades.entry_price(0)` | forbidden |

DoD:
- metadata YAML/JSON рядом с fixtures;
- docs table in `docs/grammar.md` or dedicated semantic doc.

### P1 — flow-sensitive `na` narrowing

Минимальный target:

```pinescript
float x = na
if not na(x)
    y = x + 1
```

Требования:
- не считать `x` definitely non-na вне блока;
- narrowing хранить в semantic scope, не в parser;
- не ломать текущую permissive assignability for `na`.

### P2 — import resolution v2 backlog

Без изменений:
- optional external library resolver;
- offline cache;
- import lockfile;
- exported symbols/types/enums from imported libraries.

## 3. DoD for next release

1. Full corpus/quality/schema rerun в чистом окружении.
2. Расширить registry минимум по `ta/math/str` expected members.
3. Сохранить `python -S tools/run_tests_no_pytest.py` зелёным.
4. Не менять AST schema без version bump и docs.
