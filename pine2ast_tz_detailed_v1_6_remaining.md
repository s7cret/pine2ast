# Pine2AST — ТЗ 1.6 на остаток доработок после v2.8.0

**Версия документа:** 1.6  
**Дата:** 2026-04-27  
**База кода:** `pine2ast_interpipe_v2_8_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_7_0`

## 1. Статус v2.8.0

В v2.8.0 активный stdlib-runner проходит `143 passed`. Real-world corpus на 300 fixtures остаётся зелёным: `ok_count=300`, `error_count=0`. Quality gate зелёный: `warning_count=1` (`P2A1304` expected local history warning), `info_count=1` (`P2A1506` unknown builtin registry member soft-mode).

Закрыто после v2.7.0:

1. Parser-level recovery для malformed `for [a, b, c] in ...` с `P2A1902`.
2. Strategy namespace policy v2:
   - state variables требуют `strategy()`;
   - constants разрешены в library/indicator contexts;
   - order/risk calls остаются strategy-only.
3. `strategy.closedtrades.*` / `strategy.opentrades.*` добавлены как read-only builtin accessors.
4. Unknown builtin namespace members переведены в soft `INFO P2A1506`, кроме `request.*`.
5. Forward tuple return shape сохраняет tuple arity до полного semantic pass.

## 2. Остаток P0/P1

### P0 — устранить двойную диагностику malformed for-in

Сейчас `for [a, b, c] in ...` может получить `P2A1902` и в parser diagnostics, и в semantic diagnostics. Это безопасно, но нужно выбрать политику:

- либо дедуплицировать одинаковый code/span/message в `parse_code`;
- либо пометить parser-level `P2A1902` как primary, semantic-level как fallback only.

DoD:
- один активный тест на отсутствие дублей;
- не ломать recovery и AST target names.

### P1 — namespace registry coverage

`P2A1506 UNKNOWN_BUILTIN_MEMBER` добавлен как `INFO`, потому что registry неполная. Для строгого режима нужно:

1. Расширить `builtins_v6.json` по namespaces:
   - `ta.*`;
   - `math.*`;
   - `str.*`;
   - `color.*`;
   - `line/label/box/table/polyline.*`;
   - `strategy.closedtrades.*` / `strategy.opentrades.*` до полного списка.
2. Добавить option `strict_builtin_namespaces: bool = False`.
3. В strict mode unknown members известных namespaces переводить из `INFO` в `ERROR`, кроме allowlisted extension namespaces.
4. Добавить registry coverage report.

### P1 — richer strategy validation

Нужно уточнить policy для libraries:

- constants вроде `strategy.long` должны оставаться разрешёнными;
- state vars в library сейчас диагностируются как strategy-only;
- нужно сверить с TradingView compile oracle, разрешены ли library wrappers над `strategy.equity` / `strategy.closedtrades.*`.

DoD:
- fixtures для indicator/strategy/library;
- compile-oracle metadata;
- отдельная таблица allowed/forbidden strategy namespace usages.

### P1 — flow-sensitive `na` narrowing

Добавить минимальную модель narrowing:

```pinescript
float x = na
if not na(x)
    y = x + 1
```

Требования:
- не считать `x` definitely non-na вне блока;
- внутри блока можно ослабить warnings/errors, если они появятся в future type flow;
- не смешивать parser и semantic.

### P1 — user function return inference v2

Сейчас v2.8 сохраняет tuple arity для forward calls, но не строит полноценный return model. Нужно:

1. Собрать return shape для expression body и block body.
2. Учитывать `if/switch` structures как return value.
3. Поддержать mixed int/float union → float.
4. Для несовместимых branches выдавать diagnostic только там, где результат используется в typed context.

### P2 — import resolution v2 backlog

Без изменений:

- optional external library resolver;
- offline cache;
- import lockfile;
- analysis of exported symbols from imported libraries.

## 3. DoD for next release

1. `python -S tools/run_tests_no_pytest.py` stays green.
2. Corpus/quality/schema remain green on 300 fixtures.
3. Add active tests for diagnostic dedupe or parser/semantic primary/fallback policy.
4. No public AST schema break without docs/schema version bump.
5. Update changelog and remaining-TZ document.
