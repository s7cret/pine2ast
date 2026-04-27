# Pine2AST — ТЗ 1.2 на остаток доработок после merge v2.4.0

**Версия документа:** 1.2  
**Дата:** 2026-04-26  
**База кода:** `pine2ast_interpipe_v2_4_0`  
**Предыдущий нормативный документ:** `pine2ast_tz_detailed_v1_1.md`  
**Цель:** довести объединённую ветку v2.4 до полного semantic-hardening покрытия без регресса v2.x CLI/corpus/quality/schema функциональности.

---

## 1. Статус v2.4.0

v2.4.0 — безопасная интеграционная точка на базе v2.3.0. В релизе сохранены:

- v2.3 CLI и package entrypoint;
- corpus validator и 300 real-world fixtures;
- quality gate;
- benchmark CLI;
- SARIF/diagnostic/semantic reports;
- AST schema validator;
- текущий v2.3 regression baseline.

Из v1.18.0 добавлены legacy reference материалы:

- `docs/legacy/v1_18/CHANGELOG_v1.*.md`;
- `docs/legacy/v1_18/VERIFICATION_SUMMARY.md`;
- `tests/fixtures/legacy_v1_18_valid/*.pine`.

Активные v1.18 hardening unit tests не включены в основной тестовый набор v2.4, потому что механическое включение даёт несовместимости AST/semantic contract между ветками.

---

## 2. Почему нужен этап 1.2

Прямая замена ядра v2.3 на v1.18 не подходит:

1. v1.18 возвращает часть старых semantic-hardening проверок.
2. Но v1.18 ломает часть v2.x bigblock сценариев: CLI inspect payload, quality gate, schema/diagnostic reports, tuple-expression contract, extractor behavior.
3. v2.3 содержит более свежий production layer и должен оставаться базой.

Задача 1.2 — не заменить ядро, а аккуратно перенести недостающие hardening checks из v1.18 в v2.x AST/semantic contract.

---

## 3. Обязательные принципы доработки

1. База остаётся v2.4/v2.3-compatible.
2. Нельзя ломать существующие v2.x тесты.
3. Нельзя менять публичную AST schema без явного schema minor/major bump.
4. Любая перенесённая v1.18 проверка добавляется test-first.
5. Старые v1.18 тесты нужно адаптировать к v2.x diagnostic codes, если смысл проверки тот же.
6. Для `[...]` expression нужно зафиксировать единый AST contract:
   - либо оставить `TupleExpr` как canonical v2.x node;
   - либо добавить backward-compatible alias/adapter `ArrayLiteralExpr`, не ломая сериализацию.
7. Semantic analyzer остаётся отдельным слоем; parser не должен выполнять type/signature checks.

---

## 4. Milestone A — compatibility harness для v1.18 тестов

### Цель

Сделать перенос v1.18 hardening проверок контролируемым, а не ручным.

### Задачи

1. Создать каталог:

```text
tests/unit_legacy_v1_18/
```

2. Перенести туда старые `test_hardening_v1_4.py` ... `test_hardening_v1_18.py`.
3. Добавить mapping layer для кодов диагностик:

```python
LEGACY_CODE_MAP = {
    "UNKNOWN_MEMBER": "UNKNOWN_FIELD",
    "ARGUMENT_TYPE": "TYPE_MISMATCH" или "ARGUMENT_TYPE" если код сохранён,
    "UNKNOWN_FUNCTION": новый код или UNKNOWN_PARAMETER/UNDECLARED_VARIABLE по фактической модели,
}
```

4. Для каждого старого теста указать статус:

| Статус | Значение |
|---|---|
| `ported` | тест адаптирован и проходит в v2.x contract |
| `obsolete` | проверка покрыта новым v2.x тестом |
| `blocked` | требует изменения semantic model |
| `invalid` | тест противоречит текущему ТЗ или Pine v6 |

### DoD

- Есть отчёт `docs/legacy/v1_18/PORTING_MATRIX.md`.
- Нет активных падающих тестов в основном наборе.

---

## 5. Milestone B — UDT/enum/type hardening

### Перенести/добавить проверки

1. Duplicate UDT fields.
2. Duplicate enum members.
3. Unknown type in variable declaration.
4. Unknown type in function/method parameter.
5. Unknown type in UDT field.
6. UDT constructor required fields.
7. UDT constructor unknown/duplicate fields.
8. UDT constructor field type mismatch.
9. Known/unknown enum member access.
10. Unknown UDT field read/reassignment.

### Диагностические коды

Использовать v2.x naming, не плодить дубли:

```text
UNKNOWN_TYPE
UNKNOWN_FIELD
TYPE_MISMATCH
ARGUMENT_COUNT
DUPLICATE_NAMED_ARGUMENT
REDECLARATION или новые DUPLICATE_FIELD/DUPLICATE_ENUM_MEMBER, если нужно точное различение
```

Если `DUPLICATE_FIELD` и `DUPLICATE_ENUM_MEMBER` возвращаются — добавить их в `diagnostics/codes.py` и diagnostic reports.

### DoD

- Добавлены unit tests на каждый пункт.
- `python -S tools/run_tests_no_pytest.py` остаётся зелёным.

---

## 6. Milestone C — function/method signature hardening

### Перенести/добавить проверки

1. User function unknown named argument.
2. User function missing required argument.
3. User function argument type mismatch.
4. Duplicate positional + named parameter.
5. Method receiver type mismatch.
6. Method argument type mismatch.
7. Unknown method on typed scalar/UDT/collection.
8. UDT field is not callable.
9. Method declaration inside local block.
10. Function/method parameter default type mismatch.

### Особое правило

Встроенные collection methods (`array.*`, `map.*`, `matrix.*`) должны проверяться и в function-form, и в method-form:

```pinescript
array.push(values, close)
values.push(close)
map.put(m, "k", 1.0)
m.put("k", 1.0)
```

---

## 7. Milestone D — collection/generic type inference

### Перенести/добавить проверки

1. `array.from(...)` infers element type.
2. `array.new<float>()` preserves generic element type.
3. `array.get()` returns element type.
4. `array.push()` rejects wrong element type.
5. `map.get()` returns value type.
6. `map.put()` validates key/value types.
7. `matrix.get()` returns element type.
8. `matrix.set()` validates element type.
9. Mixed numeric array literal widens `int + float -> float`.
10. Mixed non-numeric array literal rejects typed array assignment.

### AST contract decision

v2.x currently uses `TupleExpr` for `[...]`. Before adding tests, decide and document:

- `TupleExpr` means Pine tuple/list expression, used for tuple returns and options arrays; or
- introduce `ArrayLiteralExpr` as subtype/alias with serialization compatibility.

Recommended for minimal breakage:

```python
ArrayLiteralExpr = TupleExpr
```

as compatibility alias only, while keeping JSON kind stable unless schema bump is accepted.

---

## 8. Milestone E — tuple return/destructuring hardening

### Перенести/добавить проверки

1. Builtins returning tuple define typed tuple targets: `ta.bb`, `ta.macd`.
2. `request.security(..., tuple_expr)` preserves element types.
3. User function tuple return drives destructuring target types.
4. Tuple destructuring rejects non-tuple initializer.
5. Tuple destructuring rejects wrong arity.
6. Tuple target overflow/underflow diagnostics are stable.
7. `_` target must not leak symbol.

### DoD

- `TupleDeclaration` has semantic target types in symbol table.
- `extract_inputs`/optimizer payload remain unchanged from v2.3 expectations.

---

## 9. Milestone F — expression/operator type validation

### Перенести/добавить проверки

1. Arithmetic rejects non-numeric operands except valid string concatenation rule.
2. Unary `not` requires bool operand.
3. Reassignment type mismatch.
4. UDT field reassignment type mismatch.
5. Conditional branch type mismatch visible to typed assignment.
6. Function/method return type visible to typed assignment.
7. Switch case result type consistency.
8. For range bounds require integer-like expressions.

---

## 10. Milestone G — extractors and optimizer compatibility

Нельзя регрессить v2.3 extractor behavior.

### Проверить

1. `extract_inputs()`:
   - variable name fallback;
   - title positional/named;
   - options from tuple/list/`array.from`;
   - enum member options as stable names;
   - `input.source()` with series defval.
2. `extract_strategy_calls()`.
3. `extract_request_calls()`.
4. `extract_plots()`.
5. `extract_dependencies()`.
6. `extract_alertconditions()`.
7. `extract_drawing_calls()`.

---

## 11. Milestone H — registry hardening

### Добавить/проверить registry entries

Минимально расширить `builtins_v6.json` без смены AST schema:

```text
plotshape
plotchar
barcolor
bgcolor
color.new
color.rgb
color.from_gradient
label.new
label.set_text
line.new
line.set_xy1
line.set_xy2
box.new
table.new
table.cell
str.format
str.tostring
math.max
math.min
math.abs
math.round
ta.highest
ta.lowest
ta.change
ta.crossover
ta.crossunder
timeframe.change
request.financial
request.security_lower_tf
array.from
array.push
array.pop
map.new<string, float>
map.put
map.get
matrix.new<float>
matrix.get
matrix.set
```

### DoD

- Unknown function diagnostics не должны срабатывать на типовых Pine v6 calls из реального корпуса.
- Registry loader продолжает валидировать `schema_version` и `pine_version`.

---

## 12. Milestone I — tests/CI/quality

### Обязательные команды

```bash
python -S tools/run_tests_no_pytest.py
python -S -m pytest -q          # если окружение поддерживает pytest без sitecustomize-зависаний
python -S -m pine2ast.cli validate tests/fixtures/real_world --json corpus.json
python -S -m pine2ast.cli quality tests/fixtures/real_world --json quality.json
```

### Цели

1. Основной stdlib runner зелёный.
2. v1.18 porting matrix не содержит `blocked` по критичным semantic checks.
3. Real-world corpus остаётся не меньше 300 файлов.
4. Все новые checks покрыты unit tests.
5. В `docs/ast_schema.md` отражены любые изменения AST contract.

---

## 13. Приоритет выполнения

| Приоритет | Блок |
|---:|---|
| P0 | Compatibility harness + porting matrix |
| P0 | UDT/enum/type hardening |
| P0 | tuple return/destructuring hardening |
| P1 | function/method signature hardening |
| P1 | collection/generic inference |
| P1 | operator/branch type validation |
| P2 | registry expansion |
| P2 | legacy fixture graduation into active real-world corpus |

---

## 14. Acceptance criteria для v2.5.0

v2.5.0 можно выпускать, когда:

1. Все v2.4 baseline tests проходят.
2. Не меньше 80% legacy v1.18 hardening tests имеют статус `ported` или `obsolete`.
3. Нет `blocked` по UDT/enum/type/tuple destructuring critical checks.
4. `tests/fixtures/real_world` содержит минимум 300 файлов.
5. `tests/fixtures/legacy_v1_18_valid` либо перенесены в active corpus, либо имеют documented reason, почему остались legacy.
6. `docs/legacy/v1_18/PORTING_MATRIX.md` обновлён.
7. `CHANGELOG_v2.5.0.md` содержит список перенесённых hardening checks.
