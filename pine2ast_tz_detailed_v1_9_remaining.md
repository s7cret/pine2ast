# Pine2AST — ТЗ 1.9 на остаток доработок после v2.11.0

**Версия документа:** 1.9  
**Дата:** 2026-04-27  
**База кода:** `pine2ast_interpipe_v2_11_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_10_0`

## 1. Статус v2.11.0

В v2.11.0 закрыт основной P1-блок из ТЗ 1.8 по flow-sensitive narrowing:

1. `if not na(x) and x > 0` — non-`na` факт для `x` сохраняется в scope тела `if`.
2. `if not na(obj.field)` — member-path факт сохраняется как `obj.field` в `SemanticModel.non_na_paths`.
3. `if na(x) ... else ...` — non-`na` факт для `x` сохраняется в `else` scope.
4. Narrowing остаётся scope-local и не течёт в global/sibling scopes.
5. `semantic-report` получил schema version 2 и отдаёт `non_na_paths`, `non_na_symbols`, `narrowing_count`.

AST schema не менялась.

## 2. Остаток P0/P1

### P0 — полный clean-environment regression run

В текущем окружении полный runner/corpus снова срывался внешними helper-процессами, которые проверяют старые `/mnt/data/work_v28` и `/mnt/data/work_v29` пути. Нужно повторить в чистом окружении:

```bash
python -S tools/run_tests_no_pytest.py
python -S -m pine2ast.cli validate-corpus tests/fixtures/real_world --json CORPUS_RUN_v2_11_0.json
python -S -m pine2ast.cli quality-gate tests/fixtures/real_world --json QUALITY_GATE_v2_11_0.json
python -S -m pine2ast.cli schema-check tests/fixtures/real_world/01_ma_indicator.pine --json SCHEMA_CHECK_v2_11_0.json
```

DoD:

- stdlib runner полностью проходит;
- `file_count=300`;
- `error_count=0`;
- quality gate `ok=true`;
- schema report `ok=true`.

### P1 — углубить narrowing semantics

Следующий hardening:

1. `if not na(x) and not na(y)` — оба факта должны попадать в body scope.
2. `if not na(x) or fallback` — не сужать `x` в body, потому что `or` не гарантирует non-`na`.
3. `if not na(x) and (x > 0 and x < 10)` — сохранить факт через вложенные `and`.
4. `else if na(x)` — корректная branch-local metadata без переноса фактов между ветками.
5. Добавить diagnostics/tests, если narrowing факт применяется к literal или expression без stable path.

### P1 — compile-oracle status update

Файлы в `tests/fixtures/compile_oracle/strategy_namespace/` всё ещё требуют фактического TradingView compile status вместо `pending_oracle`.

Требуется проверить:

| Context | Usage | Expected |
|---|---|---|
| indicator | `strategy.long` | allowed as constant |
| library | `strategy.long` | allowed as constant |
| indicator | `strategy.equity` | forbidden |
| strategy | `strategy.closedtrades.entry_price/comment` | allowed |
| indicator | `strategy.closedtrades.entry_price` | forbidden |

### P1 — registry parameter metadata

Coverage по expected names закрыт, но часть builtin entries всё ещё содержит неполные `parameters`.

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

1. Полный clean regression run в чистом окружении.
2. Закрыть nested-`and` narrowing и negative `or` case.
3. Обновить compile-oracle metadata реальными статусами, если доступен TradingView oracle.
4. Не менять AST schema без version bump и docs.
