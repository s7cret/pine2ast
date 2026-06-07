# ТЗ: 100% покрытие Pine Script v5/v6 parity matrix

> **Цель**: Довести `parity_matrix.json` до 161→0 UNVERIFIED/NOT_STARTED entries.
> **Текущее состояние**: 582/743 DONE_VERIFIED (78.3%), 161 осталось.
> **Ветка**: `fix/runtime-contract-foundation-2026-04-28` → `s7cret/pine2ast`

---

## Обзор остатка

| Группа | Кол-во | Статус | Что делать |
|--------|--------|--------|-----------|
| A. Drawing (functions) | 33 | parser IMPLEMENTED, нет тестов | Написать parser test + semantic test |
| B. Drawing (methods) | 15 | parser IMPLEMENTED, нет тестов | Написать method-style test |
| C. Drawing (types) | 6 | parser IMPLEMENTED, нет тестов | Написать type test |
| D. Map functions | 10 | parser IMPLEMENTED, нет тестов | Написать function test |
| E. Matrix functions | 50 | parser IMPLEMENTED, нет тестов | Написать function test |
| F. request.* functions | 3 | parser IMPLEMENTED, нет тестов | Написать function test |
| G. volume_row type | 1 | parser IMPLEMENTED, нет тестов | Написать type test |
| H. Strategy functions | 19 | parser IMPLEMENTED, нет тестов | Написать function test |
| I. Strategy variables | 19 | parser IMPLEMENTED, нет тестов | Написать variable test |
| J. Plot functions | 10 | parser DONE_VERIFIED, semantic UNVERIFIED | Только semantic verify |
| K. NOT_STARTED | 5 | **Реализовать в builtins_v6.json** + parser + semantic | Имплементация с нуля |
| L. UNSUPPORTED | 5 | Оставить как есть | Ничего (log.*, request.economic, runtime.error) |

**Итого к реализации**: 161 entry (A–K), из них 5 с нуля, 156 — написать тесты для верификации.

---

## K. NOT_STARTED — Имплементация с нуля (5 entries)

Эти функции **уже есть** в `builtins_v6.json` (в секции functions), но **не зарегистрированы** как переменные в парсере и не имеют тестов.

### K.1 `strategy.closedtrades.max_drawdown_percent(trade_num) → float`

```
# Pine Script вызов:
strategy.closedtrades.max_drawdown_percent(0)  // максимальная просадка сделки #0 в %

# Контракт:
# - Вход: trade_num (int) — индекс закрытой сделки (0-based)
# - Выход: float — максимальная просадка в процентах
# - Эквивалент: strategy.closedtrades.max_drawdown(trade_num) / strategy.closedtrades.entry_price(trade_num) * 100

# Тест-кейс для парсера:
aapl = strategy.closedtrades.max_drawdown_percent(0)
plot(aapl)

# Ожидаемый AST:
# VariableDeclaration(name="aapl", init=FunctionCall("strategy.closedtrades.max_drawdown_percent", args=[IntLiteral(0)]))
```

### K.2 `strategy.closedtrades.max_runup_percent(trade_num) → float`

Аналогично K.1, но max_runup в %.

### K.3 `strategy.opentrades.max_drawdown_percent(trade_num) → float`

Аналогично K.1, но для открытых сделок.

### K.4 `strategy.opentrades.max_runup_percent(trade_num) → float`

Аналогично K.2, но для открытых сделок.

### K.5 `strategy.risk.max_position_size(direction, qty) → void`

```
# Pine Script вызов:
strategy.risk.max_position_size("long", 100)   // макс. позиция long = 100 контрактов
strategy.risk.max_position_size("short", 50)    // макс. позиция short = 50

# Контракт:
# - Вход: direction (string: "long"/"short"), qty (float/int)
# - Выход: void (side-effect function)
# - Это strategy risk management function, не возвращает значение
```

### K.6 Что нужно сделать для K.1–K.5

1. **builtins_v6.json**: Проверить что entries существуют в секции `functions`. Если нет — добавить:
   ```json
   "strategy.closedtrades.max_drawdown_percent": {
     "signature": "strategy.closedtrades.max_drawdown_percent(trade_num) → float",
     "params": [{"name": "trade_num", "type": "int"}],
     "return_type": "float",
     "category": "strategy",
     "tv_versions": ["v5", "v6"]
   }
   ```
   Аналогично для остальных 4.

2. **Тест-файлы**: Создать `tests/fixtures/tv_parity_syntax_corpus/functions/strategy_closedtrades_max_drawdown_percent.pine`:
   ```pine
   //@version=6
   strategy("test", overlay=true)
   a = strategy.closedtrades.max_drawdown_percent(0)
   ```
   
3. **Semantic тест**: Проверить что тип возвращаемого значения — `float`.

4. **Обновить parity_matrix.json**: `NOT_STARTED` → `DONE_VERIFIED` для всех 5 entries.

---

## A. Drawing Functions — Parser Verification (33 entries)

Все эти функции **реализованы** в парсере (registered в builtins_v6.json + парсятся корректно). Нужно **написать тесты**, доказывающие что парсер правильно создаёт AST.

### A.1 Таблица drawing functions

| # | Функция | Тест-кейс (минимальный Pine) | Ожидаемый AST |
|---|---------|------------------------------|---------------|
| 1 | `box.new(left, top, right, bottom, ...)` | `b = box.new(bar_index[10], high[10], bar_index, low, border_color=color.red)` | FunctionCall("box.new", 5 positional args + 1 named) |
| 2 | `box.set_bg_color(b, c)` | `box.set_bg_color(b, color.blue)` | FunctionCall("box.set_bg_color", [Var("b"), ColorRef]) |
| 3 | `box.set_border_color(b, c)` | `box.set_border_color(b, color.green)` | FunctionCall("box.set_border_color", ...) |
| 4 | `box.set_border_width(b, w)` | `box.set_border_width(b, 2)` | FunctionCall("box.set_border_width", [Var("b"), Int(2)]) |
| 5 | `box.set_text(b, txt)` | `box.set_text(b, "hello")` | FunctionCall("box.set_text", [Var("b"), String]) |
| 6 | `box.set_text_color(b, c)` | `box.set_text_color(b, color.white)` | FunctionCall("box.set_text_color", ...) |
| 7 | `box.set_text_halign(b, h)` | `box.set_text_halign(b, text.align_left)` | FunctionCall with enum arg |
| 8 | `box.set_text_valign(b, v)` | `box.set_text_valign(b, text.align_top)` | FunctionCall with enum arg |
| 9 | `box.set_text_size(b, s)` | `box.set_text_size(b, size.normal)` | FunctionCall with enum arg |
| 10 | `box.delete(b)` | `box.delete(b)` | FunctionCall("box.delete", [Var]) |
| 11 | `label.new(x, y, text, ...)` | `l = label.new(bar_index, high, "test", color=color.green, style=label.style_label_down)` | FunctionCall with many named args |
| 12 | `label.set_text(l, txt)` | `label.set_text(l, "new text")` | FunctionCall |
| 13 | `label.set_textcolor(l, c)` | `label.set_textcolor(l, color.yellow)` | FunctionCall |
| 14 | `label.set_tooltip(l, t)` | `label.set_tooltip(l, "tip")` | FunctionCall |
| 15 | `label.set_size(l, s)` | `label.set_size(l, size.large)` | FunctionCall |
| 16 | `label.set_textalign(l, a)` | `label.set_textalign(l, text.align_center)` | FunctionCall |
| 17 | `label.delete(l)` | `label.delete(l)` | FunctionCall |
| 18 | `line.new(x1, y1, x2, y2, ...)` | `ln = line.new(bar_index[10], high[10], bar_index, low, color=color.red, width=2)` | FunctionCall |
| 19 | `line.set_color(ln, c)` | `line.set_color(ln, color.blue)` | FunctionCall |
| 20 | `line.set_width(ln, w)` | `line.set_width(ln, 3)` | FunctionCall |
| 21 | `line.delete(ln)` | `line.delete(ln)` | FunctionCall |
| 22 | `linefill.new(l1, l2, c)` | `lf = linefill.new(l1, l2, color.new(color.red, 90))` | FunctionCall |
| 23 | `table.new(position, columns, rows, ...)` | `t = table.new(position.top_right, 2, 2, bgcolor=color.black)` | FunctionCall |
| 24 | `table.cell(t, col, row, text, ...)` | `table.cell(t, 0, 0, "hello", text_color=color.white)` | FunctionCall |
| 25 | `table.delete(t)` | `table.delete(t)` | FunctionCall |
| 26 | `color.new(c, transp)` | `c = color.new(color.red, 50)` | FunctionCall("color.new", [ColorRef, Int]) |
| 27 | `color.rgb(r, g, b, transp)` | `c = color.rgb(255, 0, 0, 50)` | FunctionCall("color.rgb", 4 args) |
| 28 | `barcolor(c)` | `barcolor(color.green)` | FunctionCall("barcolor", [ColorRef]) |
| 29 | `bgcolor(c)` | `bgcolor(color.new(color.red, 90))` | FunctionCall("bgcolor", ...) |
| 30 | `fill(h1, h2, c)` | `fill(plot(close), plot(open), color=transp)` | FunctionCall with transp |
| 31 | `hline(price, title, color, ...)` | `hline(0, "zero", color=color.gray)` | FunctionCall |
| 32 | `input(...)` | `x = input.int(14, "Length", minval=1)` | FunctionCall("input.int", named args) |
| 33 | `input.session(...)` | `s = input.session("0930-1600", "Session")` | FunctionCall("input.session") |

### A.2 Что нужно сделать

Для каждой функции:

1. Создать файл `tests/fixtures/tv_parity_syntax_corpus/functions/<name>.pine`:
   ```pine
   //@version=6
   strategy("test", overlay=true)
   // ... минимальный вызов функции
   ```

2. В `tests/test_tv_parity_corpus.py` (или аналогичном) добавить тест:
   ```python
   def test_<name>_parses():
       corpus = Path("tests/fixtures/tv_parity_syntax_corpus/functions/<name>.pine")
       source = corpus.read_text()
       result = parse(source)
       assert not result.errors, f"Parse errors: {result.errors}"
       # Опционально: проверить конкретную ноду AST
   ```

3. Обновить parity_matrix.json: `IMPLEMENTED_UNVERIFIED` → `DONE_VERIFIED` для parser_status.

### A.3 Особые случаи

**`box.set_border_style`, `box.set_bottom_right_point`, `box.set_top_left_point`, `box.set_extend`** — эти method-style вызовы парсятся как `box.set_border_style(b, style)` (function-style), НЕ как `b.set_border_style(style)`. Тесты должны проверять function-style.

**`chart.point.copy`** — это namespace method:
```pine
p1 = chart.point.now(bar_index, high)
p2 = chart.point.copy(p1)
```

**`linefill.new`** — принимает два line-объекта + color. Нужно предварительно создать line'ы.

---

## B. Drawing Methods — Method-Style Tests (15 entries)

Это entries в parity_matrix где `official_category = "methods"` и `id` совпадает с function entries.

### B.1 Проблема

Парсер поддерживает **function-style** вызовы (`box.set_border_color(b, c)`), но НЕ **method-style** (`b.set_border_color(c)`). Нужно **или**:
- Вариант 1: Добавить method-style в парсер (трансформация `obj.method(args)` → `method(obj, args)`)
- Вариант 2: Признать что method-style не поддерживается и зафиксировать в parity_matrix как `UNSUPPORTED_METHOD_STYLE`

### B.2 Список method entries

| # | Method | Function equivalent |
|---|--------|-------------------|
| 1 | `box.set_border_style` | `box.set_border_style(b, style)` |
| 2 | `box.set_bottom_right_point` | `box.set_bottom_right_point(b, point)` |
| 3 | `box.set_extend` | `box.set_extend(b, ext)` |
| 4 | `box.set_top_left_point` | `box.set_top_left_point(b, point)` |
| 5 | `chart.point.copy` | `chart.point.copy(p)` |
| 6 | `label.set_point` | `label.set_point(l, point)` |
| 7 | `label.set_style` | `label.set_style(l, style)` |
| 8 | `line.set_extend` | `line.set_extend(ln, ext)` |
| 9 | `line.set_first_point` | `line.set_first_point(ln, point)` |
| 10 | `line.set_second_point` | `line.set_second_point(ln, point)` |
| 11 | `line.set_style` | `line.set_style(ln, style)` |
| 12 | `linefill.delete` | `linefill.delete(lf)` |
| 13 | `linefill.get_line1` | `linefill.get_line1(lf)` |
| 14 | `linefill.get_line2` | `linefill.get_line2(lf)` |
| 15 | `linefill.set_color` | `linefill.set_color(lf, c)` |

### B.3 Что нужно сделать

**Вариант 1 (рекомендуемый)**: Если в парсере уже есть method resolution (проверить `expressions.py` на обработку `.` dotted calls), то method-style парсится уже сейчас. Написать тест:
```python
def test_method_style_box_set_border_style():
    source = '''
    //@version=6
    strategy("test", overlay=true)
    b = box.new(bar_index[10], high[10], bar_index, low)
    b.set_border_style(line.style_dotted)
    '''
    result = parse(source)
    assert not result.errors
```

**Вариант 2**: Если method-style НЕ парсится — реализовать в `expressions.py`:
- При парсинге `expr.method(args)`:
  1. Если `expr` — это VariableNode и `method` зарегистрирован в builtins как method для типа `expr` → трансформировать в FunctionCall("type.method", [expr, *args])
  2. Иначе — ошибка "Unknown method"

---

## C. Drawing Types — Type Tests (6 entries)

| # | Type | Тест-кейс |
|---|------|-----------|
| 1 | `box` | `b = box.new(...)` — проверить что `b` имеет тип `box` |
| 2 | `chart.point` | `p = chart.point.now(bar_index, high)` — проверить тип `chart.point` |
| 3 | `color` | `c = color.red` — проверить тип `color` |
| 4 | `label` | `l = label.new(...)` — проверить тип `label` |
| 5 | `line` | `ln = line.new(...)` — проверить тип `line` |
| 6 | `linefill` | `lf = linefill.new(...)` — проверить тип `linefill` |

### C.1 Что нужно сделать

Для каждого типа создать тест, проверяющий что:
1. Литерал типа парсится (`color.red`, `box.new(...)`)
2. Переменная получает правильный inferred type
3. Builtins_v6.json содержит type entry

```python
def test_type_box():
    source = '''
    //@version=6
    strategy("test", overlay=true)
    b = box.new(bar_index[10], high[10], bar_index, low)
    '''
    result = parse(source)
    assert not result.errors
    # Проверить что переменная b имеет inferred type "box"
```

---

## D. Map Functions — Function Tests (10 entries)

### D.1 Полный список

| # | Функция | Сигнатура | Тест-кейс |
|---|---------|-----------|-----------|
| 1 | `map.new<key, value>()` | `map.new<string, float>()` | `m = map.new<string, float>()` |
| 2 | `map.put(m, key, val)` | `map.put(m, "close", close)` | `map.put(m, "close", close)` |
| 3 | `map.get(m, key)` | `float val = map.get(m, "close")` | `v = map.get(m, "close")` |
| 4 | `map.remove(m, key)` | `map.remove(m, "close")` | `map.remove(m, "close")` |
| 5 | `map.contains(m, key)` | `bool has = map.contains(m, "close")` | `b = map.contains(m, "close")` |
| 6 | `map.keys(m)` | `keys = map.keys(m)` | `k = map.keys(m)` |
| 7 | `map.values(m)` | `vals = map.values(m)` | `v = map.values(m)` |
| 8 | `map.size(m)` | `int sz = map.size(m)` | `s = map.size(m)` |
| 9 | `map.clear(m)` | `map.clear(m)` | `map.clear(m)` |
| 10 | `map.copy(m)` | `m2 = map.copy(m)` | `m2 = map.copy(m)` |

### D.2 Полнотест-файл

```pine
//@version=6
strategy("map test", overlay=true)

// Создание
m = map.new<string, float>()

// Операции
map.put(m, "high", high)
map.put(m, "low", low)

v = map.get(m, "high")
has = map.contains(m, "close")
sz = map.size(m)
k = map.keys(m)
vals = map.values(m)

map.remove(m, "low")
map.clear(m)
m2 = map.copy(m)
```

### D.3 Что нужно сделать

1. Файл: `tests/fixtures/tv_parity_syntax_corpus/functions/map_functions.pine`
2. Тест: проверить что все 10 функций парсятся без ошибок
3. Проверить generic syntax `<string, float>` в `map.new`

---

## E. Matrix Functions — Function Tests (50 entries)

### E.1 Полный список (сгруппирован по подкатегориям)

**Создание (2):**
- `matrix.new<type>(rows, columns, initial_value)`
- `matrix.copy(m)`

**Доступ (6):**
- `matrix.get(m, row, column)`
- `matrix.set(m, row, column, value)`
- `matrix.row(m, row_index)`
- `matrix.col(m, column_index)`
- `matrix.rows(m)`
- `matrix.columns(m)`

**Модификация (8):**
- `matrix.add_row(m, row_id, array_values)`
- `matrix.add_col(m, col_id, array_values)`
- `matrix.remove_row(m, row_id)`
- `matrix.remove_col(m, col_id)`
- `matrix.fill(m, value, from_row, to_row, from_column, to_column)`
- `matrix.concat(m1, m2)`
- `matrix.sort(m, column, order)`
- `matrix.reverse(m)`

**Математические (12):**
- `matrix.mult(m1, m2)`
- `matrix.pow(m, power)`
- `matrix.det(m)`
- `matrix.inv(m)`
- `matrix.pinv(m)`
- `matrix.transpose(m)`
- `matrix.rank(m)`
- `matrix.trace(m)`
- `matrix.sum(m, dim)`
- `matrix.diff(m, dim)`
- `matrix.avg(m, dim)`
- `matrix.median(m, dim)`

**Статистические (4):**
- `matrix.min(m, dim)`
- `matrix.max(m, dim)`
- `matrix.mode(m, dim)`
- `matrix.kron(m1, m2)`

**Проверки (9):**
- `matrix.is_square(m)`
- `matrix.is_symmetric(m)`
- `matrix.is_antisymmetric(m)`
- `matrix.is_identity(m)`
- `matrix.is_diagonal(m)`
- `matrix.is_antidiagonal(m)`
- `matrix.is_triangular(m)`
- `matrix.is_stochastic(m)`
- `matrix.is_binary(m)`
- `matrix.is_zero(m)`

**Размерность (4):**
- `matrix.reshape(m, rows, columns)`
- `matrix.submatrix(m, from_row, to_row, from_column, to_column)`
- `matrix.swap_rows(m, row1, row2)`
- `matrix.swap_columns(m, col1, col2)`

**Прочее (5):**
- `matrix.eigenvalues(m)`
- `matrix.eigenvectors(m)`
- `matrix.elements_count(m)`
- `matrix.concat(m1, m2)` — уже в модификации
- `matrix.copy(m)` — уже в создании

### E.2 Full test file

```pine
//@version=6
strategy("matrix test", overlay=true)

// Создание
m = matrix.new<float>(3, 3, 0.0)
m2 = matrix.copy(m)

// Доступ
v = matrix.get(m, 0, 0)
matrix.set(m, 0, 0, 1.0)
r = matrix.row(m, 0)
c = matrix.col(m, 0)
nr = matrix.rows(m)
nc = matrix.columns(m)
ec = matrix.elements_count(m)

// Модификация
matrix.add_row(m, 0, array.new<float>(3, 0.0))
matrix.add_col(m, 0, array.new<float>(3, 0.0))
matrix.remove_row(m, 0)
matrix.remove_col(m, 0)
matrix.fill(m, 1.0)
m3 = matrix.concat(m, m2)
matrix.sort(m, 0, order.ascending)
matrix.reverse(m)

// Математические
d = matrix.det(m)
i = matrix.inv(m)
pi = matrix.pinv(m)
t = matrix.transpose(m)
rk = matrix.rank(m)
tr = matrix.trace(m)
s = matrix.sum(m)
diff = matrix.diff(m)
avg = matrix.avg(m)
md = matrix.median(m)

// Статистические
mn = matrix.min(m)
mx = matrix.max(m)
mo = matrix.mode(m)
kr = matrix.kron(m, m2)
mp = matrix.pow(m, 2)
ml = matrix.mult(m, m2)

// Проверки
sq = matrix.is_square(m)
sym = matrix.is_symmetric(m)
asym = matrix.is_antisymmetric(m)
id = matrix.is_identity(m)
diag = matrix.is_diagonal(m)
adiag = matrix.is_antidiagonal(m)
tri = matrix.is_triangular(m)
sto = matrix.is_stochastic(m)
bin = matrix.is_binary(m)
zero = matrix.is_zero(m)

// Размерность
matrix.reshape(m, 9, 1)
sm = matrix.submatrix(m, 0, 1, 0, 1)
matrix.swap_rows(m, 0, 1)
matrix.swap_columns(m, 0, 1)

// Спец
ev = matrix.eigenvalues(m)
evc = matrix.eigenvectors(m)
```

### E.3 Проблема: Generic syntax `matrix.new<float>(3, 3, 0.0)`

Парсер **может не поддерживать** generic syntax `<type>` в function calls. Если нет — нужно:
1. Проверить парсинг `array.new<float>(10, 0.0)` — если работает, то `matrix.new<float>` тоже будет
2. Если не работает — добавить generic parsing в `expressions.py`:
   - При парсинге `name<type>(args)` → парсить `<type>` как type argument
   - Сохранить в AST как `TypeArgs` field

---

## F. request.* Functions (3 entries)

| # | Функция | Сигнатура | Тест-кейс |
|---|---------|-----------|-----------|
| 1 | `request.dividends(...)` | `request.dividends(field, currency, ...)` | `d = request.dividends(dividends.gross, currency.NONE)` |
| 2 | `request.earnings(...)` | `request.earnings(field, ...)` | `e = request.earnings(earnings.actual)` |
| 3 | `request.splits(...)` | `request.splits(field, ...)` | `s = request.splits(splits.numerator)` |

### F.1 Проблема

`request.dividends`/`request.earnings`/`request.splits` — это **внешние data request** функции, которые:
- Возвращают tuple/struct с полем (например `dividends.gross`)
- Зависят от реального market data provider
- В TradingView работают как data feeds

### F.2 Что нужно сделать

1. Проверить что эти функции зарегистрированы в `builtins_v6.json` в секции functions
2. Напать тест, проверяющий что парсер **парсит** вызов (не проверяет runtime)
3. Если в builtins_v6.json нет — добавить entries

```python
def test_request_dividends():
    source = '''
    //@version=6
    strategy("test", overlay=true)
    d = request.dividends(dividends.gross, currency.NONE)
    '''
    result = parse(source)
    assert not result.errors
```

---

## G. volume_row Type (1 entry)

```pine
//@version=6
indicator("test")
// volume_row — footprint chart data type
// Используется в request.footprint()
```

### G.1 Что нужно сделать

1. Проверить что `volume_row` зарегистрирован в `builtins_v6.json` в секции types
2. Если нет — добавить:
   ```json
   "volume_row": {
     "kind": "type",
     "description": "Footprint chart volume row data type",
     "tv_versions": ["v6"]
   }
   ```
3. Напать тест на парсинг (type reference)

---

## H. Strategy Functions — Function Tests (19 entries)

### H.1 Closed Trades (11)

| # | Функция | Пример |
|---|---------|--------|
| 1 | `strategy.closedtrades.entry_price(trade_num)` | `p = strategy.closedtrades.entry_price(0)` |
| 2 | `strategy.closedtrades.entry_time(trade_num)` | `t = strategy.closedtrades.entry_time(0)` |
| 3 | `strategy.closedtrades.exit_price(trade_num)` | `p = strategy.closedtrades.exit_price(0)` |
| 4 | `strategy.closedtrades.exit_time(trade_num)` | `t = strategy.closedtrades.exit_time(0)` |
| 5 | `strategy.closedtrades.max_drawdown(trade_num)` | `d = strategy.closedtrades.max_drawdown(0)` |
| 6 | `strategy.closedtrades.max_runup(trade_num)` | `u = strategy.closedtrades.max_runup(0)` |
| 7 | `strategy.closedtrades.profit(trade_num)` | `p = strategy.closedtrades.profit(0)` |
| 8 | `strategy.closedtrades.profit_percent(trade_num)` | `p = strategy.closedtrades.profit_percent(0)` |
| 9 | `strategy.closedtrades.size(trade_num)` | `s = strategy.closedtrades.size(0)` |
| 10 | `strategy.closedtrades.max_drawdown_percent(trade_num)` | **NEW** (K.1) |
| 11 | `strategy.closedtrades.max_runup_percent(trade_num)` | **NEW** (K.2) |

### H.2 Open Trades (2)

| # | Функция | Пример |
|---|---------|--------|
| 1 | `strategy.opentrades.max_drawdown_percent(trade_num)` | **NEW** (K.3) |
| 2 | `strategy.opentrades.max_runup_percent(trade_num)` | **NEW** (K.4) |

### H.3 Risk (4)

| # | Функция | Пример |
|---|---------|--------|
| 1 | `strategy.risk.allow_entry_in(dir)` | `strategy.risk.allow_entry_in("long")` |
| 2 | `strategy.risk.max_drawdown(pct)` | `strategy.risk.max_drawdown(10)` |
| 3 | `strategy.risk.max_intraday_loss(pct)` | `strategy.risk.max_intraday_loss(5)` |
| 4 | `strategy.risk.max_position_size(dir, qty)` | **NEW** (K.5) |

### H.4 General Strategy (3)

| # | Функция | Пример |
|---|---------|--------|
| 1 | `strategy.entry(id, direction, ...)` | `strategy.entry("long", strategy.long)` |
| 2 | `strategy.order(id, direction, ...)` | `strategy.order("sell", strategy.short, qty=10)` |
| 3 | `strategy.close(id, ...)` | `strategy.close("long")` |

### H.5 Full test file

```pine
//@version=6
strategy("strategy test", overlay=true)

// Entry/Order
strategy.entry("long", strategy.long, qty=10)
strategy.order("sell", strategy.short, qty=5)
strategy.close("long")

// Risk
strategy.risk.allow_entry_in("long")
strategy.risk.max_drawdown(10)
strategy.risk.max_intraday_loss(5)
strategy.risk.max_position_size("long", 100)

// Closed trades
ep = strategy.closedtrades.entry_price(0)
et = strategy.closedtrades.entry_time(0)
xp = strategy.closedtrades.exit_price(0)
xt = strategy.closedtrades.exit_time(0)
md = strategy.closedtrades.max_drawdown(0)
mdp = strategy.closedtrades.max_drawdown_percent(0)
mr = strategy.closedtrades.max_runup(0)
mrp = strategy.closedtrades.max_runup_percent(0)
pr = strategy.closedtrades.profit(0)
pp = strategy.closedtrades.profit_percent(0)
sz = strategy.closedtrades.size(0)

// Open trades
omdp = strategy.opentrades.max_drawdown_percent(0)
omrp = strategy.opentrades.max_runup_percent(0)
```

---

## I. Strategy Variables — Variable Tests (19 entries)

### I.1 Полный список

| # | Переменная | Тип | Описание |
|---|-----------|-----|----------|
| 1 | `strategy.account_currency` | string | Валюта аккаунта |
| 2 | `strategy.avg_losing_trade` | float | Средний убыток |
| 3 | `strategy.avg_losing_trade_percent` | float | Средний убыток в % |
| 4 | `strategy.avg_trade` | float | Средняя сделка |
| 5 | `strategy.avg_trade_percent` | float | Средняя сделка в % |
| 6 | `strategy.avg_winning_trade` | float | Средний выигрыш |
| 7 | `strategy.avg_winning_trade_percent` | float | Средний выигрыш в % |
| 8 | `strategy.grossloss_percent` | float | Общий убыток в % |
| 9 | `strategy.grossprofit_percent` | float | Общая прибыль в % |
| 10 | `strategy.margin_liquidation_price` | float | Ликвидационная цена |
| 11 | `strategy.max_contracts_held_all` | float | Макс. контрактов (все) |
| 12 | `strategy.max_contracts_held_long` | float | Макс. контрактов (long) |
| 13 | `strategy.max_contracts_held_short` | float | Макс. контрактов (short) |
| 14 | `strategy.max_drawdown` | float | Макс. просадка |
| 15 | `strategy.max_drawdown_percent` | float | Макс. просадка в % |
| 16 | `strategy.max_runup` | float | Макс. рост |
| 17 | `strategy.max_runup_percent` | float | Макс. рост в % |
| 18 | `strategy.netprofit_percent` | float | Чистая прибыль в % |
| 19 | `strategy.openprofit_percent` | float | Нереализованный P&L в % |
| 20 | `strategy.position_entry_name` | string | Имя позиции |

### I.2 Тест-файл

```pine
//@version=6
strategy("vars test", overlay=true)

// Все стратегические переменные
a1 = strategy.account_currency
a2 = strategy.avg_losing_trade
a3 = strategy.avg_losing_trade_percent
a4 = strategy.avg_trade
a5 = strategy.avg_trade_percent
a6 = strategy.avg_winning_trade
a7 = strategy.avg_winning_trade_percent
a8 = strategy.grossloss_percent
a9 = strategy.grossprofit_percent
a10 = strategy.margin_liquidation_price
a11 = strategy.max_contracts_held_all
a12 = strategy.max_contracts_held_long
a13 = strategy.max_contracts_held_short
a14 = strategy.max_drawdown
a15 = strategy.max_drawdown_percent
a16 = strategy.max_runup
a17 = strategy.max_runup_percent
a18 = strategy.netprofit_percent
a19 = strategy.openprofit_percent
a20 = strategy.position_entry_name
```

### I.3 Что нужно сделать

1. Проверить что все 20 переменных зарегистрированы в `builtins_v6.json` в секции variables
2. Если нет — добавить с правильными типами
3. Написать тест парсинга:
   ```python
   def test_strategy_variables():
       source = Path("tests/fixtures/.../strategy_variables.pine").read_text()
       result = parse(source)
       assert not result.errors
   ```

---

## J. Plot Functions — Semantic Verification (10 entries)

Эти функции **уже парсятся** (parser DONE_VERIFIED). Нужно только **проверить semantic** (inferred types).

### J.1 Список

| # | Функция | Semantic что проверить |
|---|---------|----------------------|
| 1 | `plot(series, ...)` | series — float/series float |
| 2 | `plotarrow(series, ...)` | series — float/series float |
| 3 | `plotbar OHLCV(...)` | все 4+1 — float/series float |
| 4 | `plotcandle OHLC(...)` | все 4 — float/series float |
| 5 | `plotchar(series, ...)` | series — float/series float |
| 6 | `plotshape(series, ...)` | series — bool/series bool |
| 7 | `barcolor(color)` | color — color/series color |
| 8 | `bgcolor(color)` | color — color/series color |
| 9 | `fill(hline1, hline2, ...)` | оба — hline |
| 10 | `hline(price, ...)` | price — float |

### J.2 Что нужно сделать

Написать semantic тест для каждого:
```python
def test_plot_semantic():
    source = '''
    //@version=6
    strategy("test", overlay=false)
    plot(close, "Close", color=color.red)
    '''
    result = parse(source)
    assert not result.errors
    # Найти plot node, проверить что series имеет тип series<float>
```

---

## L. UNSUPPORTED — Ничего не делать (5 entries)

Эти функции **осознанно** не поддерживаются в pine2ast:

| # | Функция | Причина |
|---|---------|---------|
| 1 | `log.error(...)` | Runtime logging — не нужен для парсинга/бэктеста |
| 2 | `log.info(...)` | Runtime logging |
| 3 | `log.warning(...)` | Runtime logging |
| 4 | `request.economic(...)` | Economic data feed — зависит от внешнего API |
| 5 | `runtime.error(...)` | Runtime error throwing — не нужен для парсинга |

**Статус в parity_matrix**: `UNSUPPORTED_DIAGNOSTIC` — оставить как есть.

---

## Порядок реализации (приоритеты)

### Phase 1: Быстрые победы (1–2 дня)
1. **K.1–K.5**: 5 NOT_STARTED → реализовать в builtins_v6.json + тесты
2. **J.1–J.10**: 10 semantic verification → написать semantic тесты
3. **I.1–I.20**: 19 strategy variables → проверить builtins + тест парсинга

### Phase 2: Data structures (2–3 дня)
4. **D.1–D.10**: 10 map functions → тест парсинга
5. **E.1–E.50**: 50 matrix functions → тест парсинга (проверить generic syntax!)
6. **F.1–F.3**: 3 request.* → тест парсинга
7. **G.1**: 1 volume_row → проверить builtins

### Phase 3: Drawing (3–5 дней)
8. **A.1–A.33**: 33 drawing functions → тесты парсинга
9. **C.1–C.6**: 6 drawing types → тесты типов
10. **B.1–B.15**: 15 method-style → **реализовать method-style в парсере ИЛИ** пометить UNSUPPORTED_METHOD_STYLE

### Phase 4: Validation
11. Запустить полный test suite: `pytest tests/ -x -q`
12. Обновить parity_matrix.json: все IMPLEMENTED → DONE_VERIFIED
13. Проверить coverage: `pytest --cov=pine2ast --cov-report=term-missing`
14. Запушить в ветку `fix/runtime-contract-foundation-2026-04-28`

---

## Риски и подводные камни

### 1. Generic syntax `matrix.new<float>(3, 3, 0.0)`
Парсер может не поддерживать `<type>` в function calls. Проверить на `array.new<float>(10, 0.0)` — если работает, matrix тоже будет. Если нет — нужно добавить в `expressions.py` generic parsing.

### 2. Method-style `obj.method(args)`
Парсер **не поддерживает** method-style. Варианты:
- **Вариант A**: Добавить в парсер (3–5 дней) — **предпочтительно**
- **Вариант B**: Пометить method entries как `UNSUPPORTED_METHOD_STYLE` в parity_matrix — быстро, но теряем v6 completeness

### 3. `chart.point` namespace
`chart.point.now()`, `chart.point.copy()` — это namespace-qualified function calls. Парсер должен обрабатывать `namespace.func()` как FunctionCall с dotted name. Проверить.

### 4. `request.dividends` возвращает struct
`request.dividends(dividends.gross, ...)` — второй аргумент это **enum field** внутри struct. Парсер может не понимать `dividends.gross` как enum reference. Нужно проверить и, возможно, добавить enum resolution.

### 5. Количество тестов
161 entry × 1 тест = 161 тест. Некоторые можно сгруппировать (map, matrix, strategy variables → один файл на группу). Итого ~30–40 тест-файлов.

---

## Сводка

| Что | Сколько | Сложность | Время |
|-----|---------|-----------|-------|
| NOT_STARTED реализация | 5 | Средняя | 0.5 дня |
| Semantic verification тесты | 10 | Лёгкая | 0.5 дня |
| Strategy variables тесты | 19 | Лёгкая | 0.5 дня |
| Map function тесты | 10 | Лёгкая | 0.5 дня |
| Matrix function тесты | 50 | Средняя (generic!) | 1–2 дня |
| Drawing function тесты | 33 | Лёгкая | 1 день |
| Drawing type тесты | 6 | Лёгкая | 0.5 дня |
| Method-style тесты | 15 | **Высокая** (парсер!) | 3–5 дней |
| request.* тесты | 3 | Средняя | 0.5 дня |
| volume_row | 1 | Лёгкая | 0.5 часа |
| Validation + push | — | Лёгкая | 0.5 дня |
| **ИТОГО** | **161** | | **8–12 дней** |

**Критический путь**: Method-style (B) — это самая большая неизвестная. Если решить через `UNSUPPORTED_METHOD_STYLE` → 5–7 дней. Если реализовать method-style в парсере → 8–12 дней.
