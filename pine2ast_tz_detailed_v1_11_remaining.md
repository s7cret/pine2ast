# Pine2AST — ТЗ 1.11 на остаток доработок после v2.13.0

**Версия документа:** 1.11  
**Дата:** 2026-04-27  
**База кода:** `pine2ast_interpipe_v2_13_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_12_0`

## 1. Статус v2.13.0

В v2.13.0 закрыт крупный registry/reporting/corpus bigblock:

1. Пакет поднят до `0.2.13`.
2. Полный stdlib runner прошёл: `175 passed`.
3. Real-world corpus прошёл в чистой `/tmp`-рабочей копии:
   - `file_count=300`;
   - `ok_count=300`;
   - `error_count=0`.
4. Quality gate прошёл:
   - `ok=true`;
   - `warning_count=1`;
   - `error_count=0`.
5. Schema smoke прошёл:
   - `parse_ok=true`;
   - `schema.ok=true`.
6. Builtin coverage расширен:
   - `function_count=278`;
   - `variable_count=103`;
   - `missing_expected=0`.
7. Добавлен registry metadata v2 pack для:
   - `request.financial`;
   - `request.dividends`;
   - `request.earnings`;
   - `request.splits`;
   - `request.currency_rate`;
   - `request.seed`.
8. Добавлены typed constants:
   - `display.*`;
   - `line.style_*`;
   - `label.style_*`;
   - `position.*`;
   - `barmerge.gaps_*`;
   - `barmerge.lookahead_*`;
   - `dividends.*`, `earnings.*`, `splits.*`.
9. Добавлены strategy risk signatures:
   - `strategy.risk.allow_entry_in`;
   - `strategy.risk.max_drawdown`;
   - `strategy.risk.max_intraday_loss`;
   - `strategy.risk.max_cons_loss_days`;
   - `strategy.risk.max_intraday_filled_orders`.
10. Добавлены committed baseline JSON reports:
    - diagnostics report;
    - builtin coverage;
    - semantic report.
11. Поддержан overload `line.new(chart.point, chart.point, ...)` без ослабления numeric overload validation.

AST schema не менялась.

## 2. Остаток P0/P1

### P0 — external TradingView compile oracle

`tests/fixtures/compile_oracle/strategy_namespace/metadata.json` всё ещё содержит internal `pine2ast_status=pass`, но фактический TradingView compile status остаётся `pending_external_oracle`.

Нужно проверить в TradingView Pine Editor:

| Fixture | Expected |
|---|---|
| `indicator_strategy_long_allowed.pine` | compile ok |
| `library_strategy_long_allowed.pine` | compile ok |
| `indicator_strategy_equity_forbidden.pine` | compile error |
| `strategy_closedtrades_allowed.pine` | compile ok |
| `indicator_closedtrades_forbidden.pine` | compile error |

После проверки обновить `tradingview_status`, `checked_at`, `oracle`.

### P1 — registry parameter metadata v3

Следующий pack:

1. More drawing/table setters:
   - `line.set_*` variants;
   - `label.set_*` variants;
   - `box.set_*` variants;
   - `table.cell_set_*` variants.
2. More `ta.*` functions with parameter metadata:
   - `ta.stdev`, `ta.variance`, `ta.vwma`, `ta.wma`, `ta.linreg`, `ta.supertrend`.
3. More `math.*` and `str.*` signatures with strict argument validation.
4. More request metadata details:
   - currency enum constants if needed;
   - financial period constants if they are confirmed in official docs.

### P1 — diagnostics baseline expansion

Сейчас baseline reports есть для `01_ma_indicator.pine`. Следующий шаг:

```bash
pine2ast diagnostics-report tests/fixtures/real_world/02_strategy_basic.pine
pine2ast semantic-report tests/fixtures/real_world/02_strategy_basic.pine
pine2ast diagnostics-report tests/fixtures/real_world/85_v19_chart_points.pine
pine2ast semantic-report tests/fixtures/real_world/85_v19_chart_points.pine
```

Цель: зафиксировать baseline на strategy и chart.point overload.

### P1 — pytest/ruff/black/mypy clean pass

В текущем окружении used runner: `python -S tools/run_tests_no_pytest.py`. Перед production-интеграцией нужно в обычном dev env прогнать:

```bash
pip install -e .[dev]
pytest
ruff check .
black --check .
mypy pine2ast || pyright
```

### P2 — import resolution v2 backlog

Без изменений:

- optional external library resolver;
- offline cache;
- import lockfile;
- exported symbols/types/enums from imported libraries.

## 3. DoD для следующего релиза

1. Обновить external TradingView compile oracle, если доступен Pine Editor.
2. Закрыть registry metadata v3 pack.
3. Расширить committed baseline reports минимум на strategy и chart.point fixtures.
4. Не менять AST schema без version bump и docs.
