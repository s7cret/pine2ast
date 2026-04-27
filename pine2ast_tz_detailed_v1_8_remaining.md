# Pine2AST — ТЗ 1.8 на остаток доработок после v2.10.0

**Версия документа:** 1.8  
**Дата:** 2026-04-27  
**База кода:** `pine2ast_interpipe_v2_10_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_9_0`

## 1. Статус v2.10.0

В v2.10.0 закрыты пункты из ТЗ 1.7:

1. Расширен builtin registry по coverage backlog:
   - `str.tonumber`;
   - missing `line.*`, `label.*`, `box.*`, `table.*`, `polyline.*`;
   - `strategy.closedtrades.entry_comment/exit_comment`;
   - `strategy.opentrades.entry_comment`.
2. `builtin_registry_coverage_report()` теперь показывает `missing_expected=0` по текущему expected backlog.
3. Добавлена semantic metadata для flow-sensitive `na` narrowing в true-ветке `if not na(x)`.
4. Добавлены compile-oracle fixtures + metadata для strategy namespace policy.
5. `pine2ast.__main__` переведён на lazy CLI import.
6. `load_builtin_registry()` переведён с `importlib.resources` на локальный `Path(__file__).with_name`, чтобы убрать зависимость от медленного resource discovery в ограниченных окружениях.

Фокусная проверка v2.10: зелёная. Schema smoke: зелёный.

## 2. Остаток P0/P1

### P0 — полный clean-environment regression run

В текущем окружении полный runner/corpus снова был сорван внешними helper-процессами, которые непрерывно проверяют старые `/mnt/data/work_v28/work_v29` пути.

Нужно повторить в чистом окружении:

```bash
python -S tools/run_tests_no_pytest.py
python -S -m pine2ast.cli validate-corpus tests/fixtures/real_world --json CORPUS_RUN_v2_10_0.json
python -S -m pine2ast.cli quality-gate tests/fixtures/real_world --json QUALITY_GATE_v2_10_0.json
python -S -m pine2ast.cli schema-check tests/fixtures/real_world/01_ma_indicator.pine --json SCHEMA_CHECK_v2_10_0.json
```

DoD:
- stdlib runner полностью проходит;
- `file_count=300`;
- `error_count=0`;
- quality gate `ok=true`;
- schema report `ok=true`.

### P1 — расширить flow-sensitive narrowing

Текущий v2.10 поддерживает только минимальный idiom:

```pinescript
if not na(x)
    y = x + 1
```

Следующий hardening:

1. `if not na(x) and x > 0` — narrowing внутри правой части `and` и body.
2. `if not na(obj.field)` — member-path narrowing metadata.
3. `if na(x) else` — narrowing в `else` branch.
4. Не переносить narrowing за пределы scope.
5. Добавить JSON/semantic-report representation для narrowing metadata.

### P1 — compile-oracle status update

Файлы уже добавлены в:

```text
tests/fixtures/compile_oracle/strategy_namespace/
```

Нужно заменить `pending_oracle` на фактический TradingView compile result:

| Context | Usage | Expected |
|---|---|---|
| indicator | `strategy.long` | allowed as constant |
| library | `strategy.long` | allowed as constant |
| indicator | `strategy.equity` | forbidden |
| strategy | `strategy.closedtrades.entry_price/comment` | allowed |
| indicator | `strategy.closedtrades.entry_price` | forbidden |

### P1 — more builtin signatures with real parameter metadata

Coverage backlog закрыт по expected names, но многие registry entries всё ещё имеют неполные `parameters`.

Приоритет:
1. `line.new`, `label.new`, `box.new`, `table.new`, `polyline.new` реальные параметры и типы.
2. `strategy.entry/exit/order` более точные optional params.
3. `request.*` signatures.
4. `input.*` options/min/max/step metadata.

### P2 — import resolution v2 backlog

Без изменений:
- optional external library resolver;
- offline cache;
- import lockfile;
- exported symbols/types/enums from imported libraries.

## 3. DoD for next release

1. Clean full regression run.
2. Расширить narrowing минимум на `and` и `else` для `na(x)`.
3. Обновить compile-oracle metadata реальными статусами, если доступен TradingView oracle.
4. Не менять AST schema без version bump и docs.
