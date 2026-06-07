# ДОПОЛНЕНИЕ К ТЗ: Критические находки

## Finding 1: Generic syntax работает ✅

```python
array.new<float>(10, 0.0)   # OK
map.new<string, float>()     # OK
matrix.new<float>(3, 3, 0.0) # OK
```
**Вывод**: matrix/map/array generic tests — просто написать тесты, парсер справляется.

---

## Finding 2: Method-style парсится, но НЕТ регистрации методов ❌

```
b.set_border_style(line.style_dotted)
→ ERROR P2A1605: Unknown method set_border_style for type box.
```

**Причина**: `builtins_v6.json` **НЕ имеет секции `methods`** вообще:
```python
Keys: ['functions', 'variables', 'constants', 'types', 'namespaces', ...]
# methods — отсутствует!
```

Методы типа `box.set_border_style`, `label.set_point`, `line.set_color` зарегистированы ТОЛЬКО как **functions** (function-style: `box.set_border_style(b, style)`), но НЕ как methods (method-style: `b.set_border_style(style)`).

### Что нужно сделать

**Добавить секцию `methods` в `builtins_v6.json`** с entries вида:
```json
{
  "methods": {
    "box.set_border_style": {
      "owner_type": "box",
      "name": "set_border_style",
      "parameters": [
        {"name": "style", "type": "string", "required": true}
      ],
      "returns": "void",
      "pine_version": ["v5", "v6"],
      "maps_to_function": "box.set_border_style"
    },
    "box.set_bg_color": {
      "owner_type": "box",
      "name": "set_bg_color",
      "parameters": [
        {"name": "color", "type": "color", "required": true}
      ],
      "returns": "void",
      "maps_to_function": "box.set_bg_color"
    }
    // ... все 15 method entries из parity_matrix
  }
}
```

### Список 15 методов для регистрации

| Method | owner_type | params | returns |
|--------|-----------|--------|---------|
| `box.set_border_style` | box | style: string | void |
| `box.set_bottom_right_point` | box | point: chart.point | void |
| `box.set_extend` | box | extend: string | void |
| `box.set_top_left_point` | box | point: chart.point | void |
| `chart.point.copy` | chart.point | (self) | chart.point |
| `label.set_point` | label | point: chart.point | void |
| `label.set_style` | label | style: string | void |
| `line.set_extend` | line | extend: string | void |
| `line.set_first_point` | line | point: chart.point | void |
| `line.set_second_point` | line | point: chart.point | void |
| `line.set_style` | line | style: string | void |
| `linefill.delete` | linefill | (self) | void |
| `linefill.get_line1` | linefill | (self) | line |
| `linefill.get_line2` | linefill | (self) | line |
| `linefill.set_color` | linefill | color: color | void |

### Плюс: проверить что парсер умеет method resolution

Парсер парсит `obj.method(args)` → `FunctionCall("type.method", [obj, *args])` только если:
1. Тип `obj` известен (inferred)
2. `type.method` зарегистирован в methods
3. Иначе — "Unknown method"

Это уже работает — нужна только регистрация в builtins.

---

## Finding 3: chart.point.now — тест-кейс в ТЗ НЕПРАВИЛЬНЫЙ ❌→✅

В основном ТЗ был тест:
```pine
p1 = chart.point.now(bar_index, high)  // WRONG — 2 аргумента
```

Правильный вызов:
```pine
p1 = chart.point.now(high)                   // OK — price only
p2 = chart.point.from_index(bar_index, high) // OK — index + price
p3 = chart.point.from_time(time, high)        // OK — time + price
```

`chart.point.now` принимает `(price: float, text?: string)` — НЕ `(index, price)`.

**Исправить в Section A тест-кейсе для `chart.point.copy`.**

---

## Finding 4: Enum constants — УЖЕ ЕСТЬ ✅

Все enum constants зарегистрированы в `variables` секции (322 entries, qualifier='const'):
- `line.style_*` — 6 entries (solid, dotted, dashed, arrow_left, arrow_right, arrow_both)
- `label.style_*` — 21 entries (label_up, label_down, circle, cross, diamond, etc.)
- `text.align_*` — 5 entries (left, center, right, top, bottom)
- `position.*` — 9 entries (top_right, bottom_left, etc.)
- `currency.*` — 56 entries (USD, EUR, RUB, BTC, USDT, etc.)
- `dividends.*` — 5 entries (gross, net, future_amount, etc.)
- `earnings.*` — 7 entries (actual, estimate, standardized, etc.)
- `splits.*` — 2 entries (numerator, denominator)

**Вывод**: constants НЕ нужно добавлять. Единственный gap — methods секция.

---

## Сводка: что нужно дополнительно к основному ТЗ

| # | Действие | Сложность | Время |
|---|----------|-----------|-------|
| 1 | Добавить `methods` секцию в builtins_v6.json (15 entries) | Низкая | 2 часа |
| 2 | Добавить method registration в semantic analyzer (method resolution) | Средняя | 1 день |
| 3 | Исправить chart.point.now тест-кейс в ТЗ | Trivial | 5 мин |
| 4 | Добавить enum constants (line.style_*, label.style_*, etc.) | Низкая | 1 час |
| 5 | Добавить request enum constants (dividends.*, earnings.*, etc.) | Низкая | 30 мин |

**Итого**: +1.5 дня к основному ТЗ (8–12 → 10–14 дней).

**Критический путь**: Finding 2 (methods registration) — это ключ к Section B (15 method entries). Без этого Section B = UNSUPPORTED_METHOD_STYLE и мы теряем 15 entries из 100%.
