# Pine2AST — ТЗ 1.10 на остаток доработок после v2.12.0

**Версия документа:** 1.10  
**Дата:** 2026-04-27  
**База кода:** `pine2ast_interpipe_v2_12_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_11_0`

## 1. Статус v2.12.0

В v2.12.0 закрыт крупный bigblock hardening:

1. Поднята версия пакета до `0.2.12`.
2. Полный stdlib runner прошёл: `167 passed`.
3. Добавлен focused regression suite `tests/unit/test_bigblock_v2_12.py` на 11 проверок.
4. Расширена narrowing semantics:
   - `if not na(x) and not na(y)`;
   - nested `and`;
   - negative `or` без unsound narrowing;
   - branch-local `else if` facts;
   - `INFO P2A1903 UNSTABLE_NA_NARROWING` для `na()` guard без stable path.
5. Расширен `builtins_v6.json` по priority metadata:
   - drawing constructors/setters;
   - `strategy.entry/exit/order`;
   - `request.security/security_lower_tf`;
   - `input.int/float/bool/string/timeframe`.
6. Builtin coverage закрыт: `missing_expected=0`, `function_count=276`.
7. Compile-oracle metadata для `strategy_namespace` поднята до schema v2 с internal pine2ast status.

AST schema не менялась.

## 2. Остаток P0/P1

### P0 — полный clean corpus/quality run

В текущем окружении полный corpus/quality прогон снова срывался внешними helper-процессами, которые сканируют старые `/mnt/data/work_v28` и `/mnt/data/work_v29` пути.

Нужно повторить в чистом окружении:

```bash
python -S tools/run_tests_no_pytest.py
python -S -m pine2ast.cli validate-corpus tests/fixtures/real_world --json CORPUS_RUN_v2_12_0.json
python -S -m pine2ast.cli quality-gate tests/fixtures/real_world --json QUALITY_GATE_v2_12_0.json
python -S -m pine2ast.cli schema-check tests/fixtures/real_world/01_ma_indicator.pine --json SCHEMA_CHECK_v2_12_0.json
```

DoD:

- stdlib runner полностью проходит;
- `file_count=300`;
- `error_count=0`;
- quality gate `ok=true`;
- schema report `ok=true`.

### P0 — external TradingView compile oracle

`tests/fixtures/compile_oracle/strategy_namespace/metadata.json` теперь содержит internal `pine2ast_status=pass`, но фактический TradingView compile status остаётся `pending_external_oracle`.

Нужно проверить в TradingView Pine Editor:

| Fixture | Expected |
|---|---|
| `indicator_strategy_long_allowed.pine` | compile ok |
| `library_strategy_long_allowed.pine` | compile ok |
| `indicator_strategy_equity_forbidden.pine` | compile error |
| `strategy_closedtrades_allowed.pine` | compile ok |
| `indicator_closedtrades_forbidden.pine` | compile error |

После проверки обновить `tradingview_status`, `checked_at`, `oracle`.

### P1 — registry parameter metadata v2

В v2.12 закрыт первый priority pack. Следующий pack:

1. Больше `request.*` signatures:
   - `request.financial`;
   - `request.dividends`;
   - `request.earnings`;
   - `request.splits`;
   - `request.currency_rate`;
   - `request.seed`.
2. Drawing/style enums as typed constants:
   - `line.style_*`;
   - `label.style_*`;
   - `box` style constants;
   - `table` position constants;
   - `display.*` as display enum instead of loose `any`.
3. Strategy risk helpers:
   - `strategy.risk.*` richer params.
4. More precise qualifier metadata for `input.* active/display`.

### P1 — diagnostics baseline reports

Добавить committed baseline JSON для:

```bash
pine2ast diagnostics-report tests/fixtures/real_world/01_ma_indicator.pine
pine2ast builtin-coverage
pine2ast semantic-report tests/fixtures/real_world/01_ma_indicator.pine
```

Цель: агентам проще сравнивать изменение diagnostics без полного corpus run.

### P2 — import resolution v2 backlog

Без изменений:

- optional external library resolver;
- offline cache;
- import lockfile;
- exported symbols/types/enums from imported libraries.

## 3. DoD for next release

1. Clean corpus/quality run в чистом окружении.
2. Обновить TradingView compile oracle metadata, если доступен Pine Editor.
3. Закрыть второй pack registry metadata по `request.*` и typed constants.
4. Не менять AST schema без version bump и docs.
