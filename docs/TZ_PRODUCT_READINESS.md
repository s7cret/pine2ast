# ТЗ на доведение `pine2ast` и `ast2python` до продуктового вида

**Дата аудита:** 2026-06-07  
**Объект:** две публичные библиотеки `s7cret/pine2ast` и `s7cret/ast2python`, релизная линия `v2.17.0`  
**Цель:** определить текущее состояние реализации, оптимальности, ошибок, документации и соответствия Pine Script/TradingView; сформировать подробное техническое задание на превращение библиотек в продуктовый стек.

> Важно: локально скачать репозитории через `git clone` в текущем окружении не удалось из-за DNS-ошибки доступа к GitHub, поэтому выводы основаны на статическом просмотре публичных страниц GitHub, README, структуры файлов, фрагментов кода и официальной документации TradingView. Для финального product-readiness аудита нужен локальный запуск тестов, сборка wheel/sdist, профилирование и прогон реальных Pine-корпусов.

---

## 1. Итоговый вердикт

Текущая архитектура выглядит правильно разделённой:

- `pine2ast` — frontend/parser: нормализует Pine Script v6-код, строит AST JSON, запускает семантические диагностики и отдаёт метаданные контракта.
- `ast2python` — backend/codegen: принимает Pine2AST JSON и генерирует детерминированные Python-модули под `PineLib`.

Это хороший фундамент для **компилятора/транслятора Pine subset → Python runtime**, но не полный аналог TradingView. Оба проекта в документации уже честно заявляют ограничения: `pine2ast` не исполняет Pine, не запускает backtest, не эмулирует ордера TradingView и не претендует на полный Pine v6/TradingView parity; `ast2python` также не парсит Pine source, не эмулирует бары/ордера, не получает market data и не выполняет backtest.

### Главный вывод

**Полного соответствия функционалу TradingView сейчас нет.** Для продуктового вида нужно не только расширять парсер и генератор, но и формализовать весь стек:

```text
Pine source
  -> pine2ast parser/frontend
  -> verified AST contract
  -> ast2python codegen
  -> PineLib/runtime engine
  -> data/request layer
  -> broker emulator/backtester
  -> visual/alert/report layer
  -> conformance/oracle test suite
```

Без полноценного runtime/backtester/data/request слоя нельзя корректно заявлять соответствие TradingView, потому что Pine Script исполняется bar-by-bar и tick-by-tick, имеет rollback на realtime-барах, внутренние time series, `var`/`varip`, `barstate.*`, `request.*`, визуальные лимиты и стратегический broker emulator.

---

## 2. Текущее состояние по библиотекам

## 2.1. `pine2ast`

### Назначение

`pine2ast` заявлен как Python parser/frontend для проверенного subset Pine Script v6. Pipeline:

```text
SourceNormalizer -> Lexer -> LayoutProcessor -> Parser -> AST -> SemanticAnalyzer
```

### Что уже выглядит сильным

- Есть явная frontend-архитектура: source normalization, lexer, layout, parser, AST, semantic analyzer.
- Есть стабильная AST JSON-модель и serialization.
- Есть диагностики и exit codes CLI.
- Есть CLI-команды для parse/tokens/validate/dump-symbols/inspect/schema-check/diagnostics-report/diff/quality-gate.
- Есть runtime-contract профиль `v1.4` для fail-closed интеграции с `ast2python`/`PineLib`.
- Есть ограничения размера файла, количества токенов, количества AST-нод и max diagnostics.
- Есть unit/integration test folders и fixture-корпусы.
- `pyproject.toml` использует `setuptools.packages.find` с `include = ["pine2ast*"]`, что снижает риск пропуска подпакетов при упаковке.

### Ограничения

- Документация прямо говорит, что поддерживается subset, а не весь Pine v6.
- Builtins registry — subset/confidence matrix, не полный официальный reference map.
- Compile-oracle snapshot в README содержит 35 fixtures. Для продукта этого недостаточно: нужен на порядки больший корпус.
- Нет online import resolver.
- Нет исполнения Pine, backtest, market data, broker emulator.

### Предполагаемые технические риски

1. **Полнота grammar/AST не доказана.** Нужна матрица покрытия всех синтаксических конструкций Pine v6.
2. **Полнота семантики не доказана.** Особенно сложны qualifiers (`const`, `input`, `simple`, `series`), перегрузки builtins, методы, UDT, collections, request semantics, strategy context.
3. **Возможный риск с перегрузками builtins.** В просмотренном фрагменте `SemanticAnalyzer` есть внутренняя карта параметров по short name. Для перегруженных методов/функций с одинаковым short name это требует отдельного тестирования, чтобы не было поведения “last wins”.
4. **Oracle corpus слишком мал.** 35 fixture-примеров не позволяют говорить о production-паритете.
5. **Нет доказанной устойчивости к реальным Pine-скриптам.** Нужен большой regression corpus: публичные индикаторы, стратегии, edge cases, официальные примеры TradingView.

---

## 2.2. `ast2python`

### Назначение

`ast2python` заявлен как code-generation layer между Pine2AST JSON и PineLib. Он отвечает за deterministic lowering, runtime checks, source maps, coverage metadata и diagnostics для unsupported features.

### Что уже выглядит сильным

- Чёткое разделение ответственности: генератор не притворяется runtime/backtester.
- Есть runtime contract `REQUIRED_RUNTIME_CONTRACT = "1.4"` и диагностика mismatch.
- Есть fail-closed поведение для unsupported nodes/builtins.
- Есть source maps и coverage metadata для generated modules.
- Есть production/diagnostic compile profiles и запрет unsafe overrides в production-профиле.
- Есть явные блокировки для небезопасных realtime-особенностей (`calc_on_every_tick`, `varip`) без соответствующего runtime support.
- Есть routing visual calls через runtime visual recorder.
- Есть tests/unit и tests/integration, включая CLI, pipeline parity, cross-project E2E, runtime contract, strategy APIs, time/input/alert emitters.

### Критичная найденная проблема упаковки

В `translator.py` есть импорты:

```python
from ast2python.translator_mixins.metadata import (...)
from ast2python.translator_mixins.type_inference import infer_type_info
```

В дереве проекта есть папка `ast2python/translator_mixins`, но в `pyproject.toml` пакеты перечислены вручную:

```toml
packages = [
  "ast2python",
  "ast2python.ast",
  "ast2python.cli",
  "ast2python.emitters",
  "ast2python.lowering_matrix",
  "ast2python.runtime_contract",
  "ast2python.templates"
]
```

`ast2python.translator_mixins` в списке отсутствует. Если wheel/sdist собирается именно по этому списку, установленный пакет может падать на `import ast2python.translator` с `ModuleNotFoundError`.

**Приоритет:** P0.  
**Исправление:** перейти на auto-discovery:

```toml
[tool.setuptools.packages.find]
include = ["ast2python*"]
```

или явно добавить:

```toml
"ast2python.translator_mixins"
```

**Acceptance test:**

```bash
python -m build
python -m venv /tmp/a2p-wheel-test
/tmp/a2p-wheel-test/bin/pip install dist/*.whl
/tmp/a2p-wheel-test/bin/python - <<'PY'
import ast2python
import ast2python.translator
from ast2python.translator import Translator
print("ok")
PY
```

### Ограничения

- `ast2python` не владеет broker fills, equity, execution authority.
- Strategy генерируется как intent, но не как полный TradingView strategy tester.
- Runtime parity зависит от `PineLib`, который не входил в запрос и отдельно не аудировался.
- Realtime rollback/commit semantics не могут быть полностью решены codegen-слоем без runtime engine.
- Поддержка request/security/data зависит от runtime/data layer.

---

# 3. Матрица соответствия TradingView/Pine v6

| Область | Что требуется для TradingView parity | Текущее состояние | Статус |
|---|---|---:|---:|
| Pine source parsing | Вся грамматика Pine v6, версии, annotations, line wrapping, declarations, imports, functions, methods, UDT, collections, loops, switch, tuples, history refs | `pine2ast` реализует subset и layout/parser/semantic pipeline | Partial |
| AST contract | Версионированный стабильный AST, schema, metadata, compatibility gates | Есть `pain.ast_contract.v1`, schema metadata, runtime profile | Good foundation |
| Semantic analysis | Scopes, symbols, type system, qualifiers, overloads, methods, bool v6, history refs, declarations | Есть selected diagnostics и subset builtin registry | Partial |
| Builtins | Полный официальный v6 Reference Manual: variables, functions, namespaces, overloads, defaults, qualifiers | Поддерживается subset/confidence matrix | Partial/P0 gap |
| Execution model | Bar-by-bar, tick-by-tick, internal time series, commits, rollback, `var`/`varip`, `barstate.*` | В этих двух библиотеках отсутствует; частично ожидается в PineLib | P0 runtime gap |
| Realtime behavior | Re-execution on ticks, rollback, confirmed/unconfirmed bar states, repainting semantics | `ast2python` fail-closes unsafe realtime cases | Good safety, incomplete parity |
| Strategies | Broker emulator, orders, fills, pyramiding, margin, commission, slippage, OCA, exits, Strategy Tester metrics | `ast2python` генерирует strategy intent без fills/equity | P0 gap |
| `request.*` data | `request.security`, lower TF, financial/economic/dividends/splits/earnings/seed, gaps/lookahead, dynamic requests | Есть request handlers/diagnostics, но нет полной data layer parity | P0/P1 gap |
| Visuals | plot/plotshape/plotbar/candle/fill/bgcolor/barcolor, labels, lines, boxes, tables, object limits, plot counts | Есть visual routing через runtime recorder | Partial |
| Alerts/logs | `alertcondition`, `alert`, `log.*`, realtime alert behavior | Есть alert emitter tests; full behavior не доказан | Partial |
| Limits | Compilation/execution limits, loop limits, plot/object/request limits | В `pine2ast` есть technical caps; TradingView limits не полностью эмулируются | Partial |
| Libraries/imports | Published libraries, versions, import resolver, exported symbols | Imports parsed/diagnosed locally, online resolver отсутствует | P1 gap |
| Product packaging | Wheels, PyPI/internal registry, lock files, SBOM, CI, release signing | Есть pyproject; `ast2python` имеет packaging risk | P0/P1 gap |
| Docs | User docs, API docs, support matrix, diagnostics catalog, migration guides | README есть, но мало для продукта | P1 gap |

---

# 4. Product vision

## 4.1. Целевой продукт

Целевой продукт — **OpenPine Compiler Runtime Suite**:

```text
openpine-core
├── pine2ast       # frontend/parser/semantic AST
├── ast2python     # code generator to Python/PineLib
├── pinelib        # Pine-compatible runtime primitives
├── openpine-cli   # unified CLI
├── openpine-oracle# conformance/oracle harness against TradingView evidence
├── openpine-data  # request.* adapters/data abstraction
└── openpine-backtest # strategy broker emulator/report layer
```

Пользовательские сценарии:

1. Проверить Pine Script v6 на поддерживаемость.
2. Получить AST JSON и diagnostics.
3. Сгенерировать Python-модуль.
4. Запустить индикатор на OHLCV/tick data.
5. Запустить стратегию и получить Strategy Tester-like отчёт.
6. Сравнить результат с TradingView oracle/golden outputs.
7. Интегрировать generated modules в backend-сервис.

## 4.2. Честное позиционирование

До достижения полной матрицы parity продукт должен позиционироваться так:

> “Pine Script v6 subset compiler/runtime with explicit unsupported diagnostics and verified conformance corpus.”

Нельзя писать:

> “100% TradingView compatible”

пока не выполнены acceptance criteria из раздела 12.

---

# 5. Архитектурное ТЗ

## 5.1. Общий pipeline

```text
Input .pine
  ↓
SourceNormalizer
  ↓
Lexer + Trivia
  ↓
LayoutProcessor
  ↓
Parser
  ↓
AST + Schema Validation
  ↓
SemanticAnalyzer
  ↓
Compatibility Analyzer
  ↓
AST Contract Envelope
  ↓
Code Generator
  ↓
Generated Python Module
  ↓
Pine Runtime Engine
  ↓
Outputs: visuals, alerts, strategy intents/fills, metrics
```

## 5.2. Contract envelope

Каждый AST envelope должен содержать:

```json
{
  "contract": "pain.ast_contract.v1",
  "producer": {"name": "pine2ast", "version": "x.y.z"},
  "schema_version": "...",
  "pine_language_version": 6,
  "runtime_contract": "1.4",
  "parser_gate": "pass|warn|fail",
  "semantic_gate": "pass|warn|fail",
  "compatibility_gate": "pass|warn|fail",
  "feature_matrix": {...},
  "unsupported_features": [...],
  "diagnostics": [...],
  "source_map": {...}
}
```

## 5.3. Compatibility modes

Обязательные режимы:

| Режим | Поведение |
|---|---|
| `diagnostic` | Парсит максимально возможно, возвращает AST+diagnostics, допускает unsupported nodes |
| `production` | Fail-closed: любой unsupported/runtime-unsafe feature блокирует codegen |
| `oracle` | Включает расширенные source spans, trace ids, сравнение с golden outputs |
| `unsafe-dev` | Разрешает stubs/approximations только явно и только вне release gate |

Production profile обязан запрещать:

- invalid AST;
- contract mismatch;
- unsupported builtins;
- unsupported request stubs;
- external library stubs;
- realtime local simulation без runtime parity;
- silent placeholders.

---

# 6. ТЗ по `pine2ast`

## 6.1. Grammar completeness

### Требование

Создать формальную матрицу синтаксиса Pine v6:

```text
feature_id | category | syntax | official_ref | parser_support | semantic_support | codegen_support | runtime_support | tests | status
```

Категории:

- version pragma;
- declarations: `indicator`, `strategy`, `library`;
- imports and exported symbols;
- variable declarations: typed/untyped, `var`, `varip`, tuples;
- assignment/reassignment;
- expressions: literals, calls, member access, history refs, ternary, binary/unary ops;
- functions and methods;
- UDT types and object fields;
- arrays, matrices, maps;
- loops: `for`, `while`, `for...in`;
- conditional blocks;
- switch;
- annotations/comments;
- line wrapping/layout;
- request expressions;
- strategy calls;
- visual object calls.

### Acceptance criteria

- Все syntax features имеют статус `supported`, `unsupported-diagnostic`, `deferred` или `not-applicable`.
- Для каждого `unsupported-diagnostic` есть стабильный diagnostic code.
- Для каждого supported feature есть минимум:
  - parser unit test;
  - AST golden snapshot;
  - semantic test;
  - integration test через `ast2python`, если feature lowerable.

## 6.2. Lexer/Layout

### Требования

- Подтвердить полное покрытие Pine v6 tokens.
- Добавить token golden tests для:
  - строк с escape sequences;
  - comments/annotations;
  - hex colors;
  - indentation + line wrapping;
  - nested multiline expressions;
  - operators and compound assignments;
  - unusual whitespace/BOM/CRLF;
  - invalid characters.

### Acceptance criteria

- Token stream стабилен и snapshot-тестирован.
- Для invalid token всегда возвращается diagnostic с точным span.
- Layout processor не ломает nested calls/arrays/tuples/switch/loops.

## 6.3. Parser

### Требования

- Зафиксировать Pratt precedence table и сверить со всеми операторами Pine v6.
- Ввести parser conformance suite:
  - official examples;
  - synthetic grammar cases;
  - real-world scripts;
  - invalid syntax cases.
- Ошибки парсера должны быть recoverable в diagnostic mode и blocking в production mode.

### Acceptance criteria

- AST JSON deterministic: одинаковый input → одинаковый JSON hash.
- Parser не падает uncaught exceptions на fuzz corpus.
- На invalid corpus нет silent success.

## 6.4. Semantic Analyzer

### Требования

Семантическая модель должна покрывать:

- symbol table;
- scope stack;
- declaration cardinality;
- function/method signatures;
- type inference;
- qualifier inference;
- overload resolution;
- namespace validation;
- history reference rules;
- local block restrictions;
- strategy-only namespace restrictions;
- indicator/strategy/library context;
- import/export symbol rules;
- `na` semantics;
- bool v6 rules;
- `var`/`varip` semantics tags;
- reference/value type policy.

### P0 задача: перегрузки builtins

Проверить и исправить модель хранения signatures так, чтобы overloads не затирались по short name.

**Acceptance test:** создать fixtures, где одинаковый method/function name имеет разные receiver types/signatures, и убедиться, что resolution выбирает корректную overload ветку.

## 6.5. Builtin registry

### Требование

Создать machine-readable registry полного Pine v6 Reference Manual:

```json
{
  "name": "ta.sma",
  "kind": "function",
  "namespace": "ta",
  "overloads": [
    {
      "params": [...],
      "returns": {...},
      "qualifiers": {...},
      "runtime_required": true,
      "codegen_status": "supported|unsupported|stub-forbidden",
      "tests": [...]
    }
  ],
  "source": "official-reference",
  "confidence": "verified"
}
```

### Acceptance criteria

- Registry отличает:
  - official-known;
  - implemented;
  - lowerable;
  - runtime-supported;
  - oracle-verified.
- Unknown builtin in production profile → ERROR.
- Registry diff tool показывает изменения при обновлении TradingView docs.

## 6.6. Imports/libraries

### Требования

- Локальный resolver для library imports.
- Кэш библиотек по name/version/hash.
- Support exported functions/types/methods/constants.
- Diagnostics для отсутствующих/неподдерживаемых библиотек.

### Acceptance criteria

- `import user/lib/version` не превращается в silent stub в production.
- Есть test fixtures для supported и unsupported imports.

---

# 7. ТЗ по `ast2python`

## 7.1. Packaging P0

### Требование

Исправить package discovery.

**Рекомендуемый `pyproject.toml`:**

```toml
[tool.setuptools.packages.find]
include = ["ast2python*"]
```

### Acceptance criteria

- Wheel install test проходит в чистом venv.
- `import ast2python.translator` проходит без локального source tree.
- CI публикует artifact wheel и тестирует его установку.

## 7.2. Codegen correctness

### Требования

- Все supported AST nodes должны иметь lowering rule.
- Все unsupported AST nodes должны иметь explicit diagnostic.
- Generated code deterministic.
- Generated code не должен делать `eval`, unsafe dynamic imports, path traversal, arbitrary file/network access.
- Module name/class name sanitization обязательны.

### Acceptance criteria

- Snapshot tests для generated code.
- Golden runtime output tests для каждого feature.
- Fail-closed tests: unsupported node/builtin/request/import блокирует production codegen.

## 7.3. Runtime contract enforcement

### Требования

- Contract versioning между `pine2ast`, `ast2python`, `pinelib`.
- Compatibility matrix:

```text
pine2ast version | AST contract | runtime contract | ast2python version | pinelib version | status
```

### Acceptance criteria

- Contract mismatch → deterministic error.
- Нет hidden fallback на несовместимый runtime.
- Release gate проверяет все совместимые пары.

## 7.4. Strategy lowering

### Текущее состояние

`ast2python` должен продолжать генерировать **strategy intent**, пока runtime/backtester не реализован полностью.

### Требования

- Strategy calls lower into typed intent events:

```json
{
  "event_type": "strategy.entry",
  "id": "Long",
  "direction": "long",
  "qty": 1.0,
  "limit": null,
  "stop": null,
  "source_span": {...},
  "bar_index": 123,
  "execution_id": "..."
}
```

- Runtime/backtester отвечает за fills, equity, metrics.
- Codegen не должен сам выполнять broker logic.

### Acceptance criteria

- Generated strategy module не мутирует equity/fills напрямую.
- Broker emulator tests находятся в runtime/backtest пакете.
- Strategy event schema stable and versioned.

## 7.5. Realtime safety

### Требования

- Сохранить fail-closed поведение для `calc_on_every_tick`, `calc_on_order_fills`, `varip`, object rollback, пока runtime не поддерживает их корректно.
- Добавить режим `tv-realtime` только после реализации rollback/commit engine.

### Acceptance criteria

- В production mode unsupported realtime features блокируют codegen.
- В diagnostic mode они помечаются как parity risk.
- Unsafe override невозможен в release build.

## 7.6. Request/security lowering

### Требования

- `request.*` должен lower-иться не в прямой data fetch, а в runtime data request abstraction.
- Поддержать dynamic requests Pine v6:
  - series symbol/timeframe args;
  - local scopes;
  - nested requests;
  - gaps/lookahead;
  - realtime/historical differences.

### Acceptance criteria

- Unsupported request form → blocking diagnostic.
- Supported request form → runtime request plan + deterministic cache key.
- Oracle tests сравнивают outputs с TradingView для representative cases.

## 7.7. Visual lowering

### Требования

- Все visual calls lower into recorder events.
- Recorder должен хранить enough metadata для сравнения с oracle:
  - function;
  - args;
  - resolved defaults;
  - series values;
  - object ids;
  - source span;
  - bar/execution id.

### Acceptance criteria

- Plot count/object limits проверяются runtime или compatibility analyzer.
- Visual object references не используются как обычные values, если runtime не поддерживает их semantics.

---

# 8. ТЗ по runtime/backtester/data layer

Хотя пользователь запросил две библиотеки, для продуктового соответствия TradingView нужен третий слой. Если `PineLib` уже существует, его нужно аудировать отдельно; если нет — создать.

## 8.1. Pine runtime engine

### Требования

- Bar-by-bar execution.
- Historical bars: one execution per bar by default.
- Realtime bars: tick executions, rollback, commit.
- `var` persistence.
- `varip` intrabar persistence.
- Internal time series storage.
- `[]` history references.
- `max_bars_back` handling.
- `barstate.*` values.
- `time`, `time_close`, sessions, timezones.
- `na` semantics.
- Reference object lifecycle.

### Acceptance criteria

- Official execution model examples produce matching outputs.
- Realtime reload/repaint scenarios covered.
- `var`/`varip` tests include rollback behavior.

## 8.2. Technical analysis builtins

### Требования

- Implement all supported `ta.*`, `math.*`, `str.*`, `array.*`, `matrix.*`, `map.*`, `color.*`, `timeframe.*`, `ticker.*`, `syminfo.*`, `barstate.*`, `strategy.*` read-only fields.
- Для stateful TA функций использовать per-call-state IDs.
- Numerical parity tolerance documented.

### Acceptance criteria

- Для каждой builtin function есть:
  - unit test;
  - edge-case test with `na`;
  - series/simple/input qualifier test;
  - oracle comparison where possible.

## 8.3. Data/request layer

### Требования

- Абстрактный provider interface:

```python
class DataProvider:
    def get_bars(self, symbol, timeframe, session, currency, from_, to_): ...
    def get_lower_tf(self, symbol, timeframe, parent_bar): ...
    def get_fundamental(self, kind, symbol, field, period): ...
```

- Deterministic local fixture provider для tests.
- Production adapters only with explicit licensing.
- Cache and request limit enforcement.

### Acceptance criteria

- `request.security` handles gaps/lookahead.
- Dynamic requests support series symbol/timeframe where product scope says supported.
- Realtime and historical data behavior documented.

## 8.4. Broker emulator/backtester

### Требования

Поддержать strategy semantics:

- `strategy.entry`;
- `strategy.order`;
- `strategy.exit`;
- `strategy.close`;
- `strategy.close_all`;
- `strategy.cancel`;
- `strategy.cancel_all`;
- position sizing;
- pyramiding;
- reversals;
- OCA groups;
- stop/limit/market orders;
- commission;
- slippage;
- margin;
- initial capital;
- currency;
- calc on order fills;
- calc on every tick;
- process orders on close;
- bar magnifier/intrabar prices;
- Strategy Tester metrics.

### Acceptance criteria

- Strategy examples from official docs match expected order/fill behavior.
- Reports include net profit, gross profit/loss, drawdown, win rate, trades, exposure, equity curve.
- Fill model differences from TradingView clearly documented if any.

---

# 9. Оптимизация и производительность

## 9.1. Metrics

Ввести обязательные benchmarks:

| Metric | Target |
|---|---:|
| Parse throughput | измеряется на corpus: LOC/sec, tokens/sec |
| AST memory | max RSS per 1k LOC |
| Codegen throughput | AST nodes/sec |
| Generated runtime speed | bars/sec for indicators |
| Backtest speed | bars/sec and orders/sec |
| Startup/import time | cold import ms |
| Wheel size | MB |

## 9.2. `pine2ast` optimization

- Профилировать lexer/parser на больших реальных scripts.
- Стабилизировать regex usage и избегать backtracking traps.
- Использовать lightweight AST nodes (`slots`) там, где уже не используется.
- Добавить incremental/fuzz stress tests.
- Кэшировать builtin registry load.
- Сделать diagnostics allocation cheap.
- Ввести `--benchmark` CLI output JSON.

## 9.3. `ast2python` optimization

- Минимизировать runtime dynamic dispatch в generated hot path.
- Hoist constants/defaults из `run()` в `__init__`/class-level where safe.
- Pre-bind runtime namespaces and TA state objects.
- Avoid repeated string/name resolution per bar.
- Generate compact code for repeated visual calls.
- Оптимизировать source-map/coverage emission так, чтобы production module не нес лишний overhead, если выключено.

## 9.4. Runtime optimization

- Series storage as ring buffers with configurable max history.
- Lazy `max_bars_back` growth with validation.
- Per-call-state caches for TA.
- Batch execution mode for historical bars, если не нарушает Pine semantics.
- Optional vectorized path only for proven pure/simple cases.

---

# 10. Тестирование и качество

## 10.1. Test pyramid

```text
Unit tests
  lexer/parser/semantic/codegen/runtime builtins
Golden tests
  token snapshots, AST snapshots, generated Python snapshots
Integration tests
  .pine -> AST -> Python -> runtime outputs
Oracle tests
  TradingView/Pine Editor compile evidence + output comparison
Fuzz tests
  invalid syntax, random whitespace/layout, expression stress
Mutation tests
  semantic/codegen critical paths
Packaging tests
  wheel/sdist install in clean venv
Security tests
  malicious input, path traversal, code injection
Performance tests
  benchmark regression budgets
```

## 10.2. Oracle corpus

Минимальный product corpus:

| Corpus | Minimum |
|---|---:|
| Official docs examples | all relevant v6 examples |
| Synthetic syntax fixtures | 500+ |
| Builtin fixtures | 1 per overload minimum |
| Invalid diagnostics fixtures | 300+ |
| Real-world public indicators | 500+ |
| Real-world public strategies | 200+ |
| Request/security scenarios | 100+ |
| Realtime/rollback scenarios | 50+ |
| Strategy broker scenarios | 100+ |

## 10.3. Coverage gates

Рекомендуемые thresholds:

| Package | Line coverage | Branch coverage | Notes |
|---|---:|---:|---|
| `pine2ast` | >= 90% | >= 85% | не исключать core layout/lexer без отдельного rationale |
| `ast2python` | >= 90% | >= 85% | обязательно тестировать installed wheel |
| runtime/backtester | >= 92% | >= 88% | critical financial logic |

## 10.4. CI gates

Обязательные проверки:

```bash
ruff check .
black --check .
mypy --strict-or-project-profile
pytest --cov --cov-report=xml
python -m build
pip install dist/*.whl in clean venv
import smoke tests
oracle regression subset
benchmark regression check
pip-audit / safety equivalent
SBOM generation
```

---

# 11. Документация

## 11.1. Документация пользователя

Создать `docs/` для обоих пакетов или единый docs site.

Структура:

```text
docs/
  index.md
  getting-started.md
  installation.md
  cli.md
  python-api.md
  architecture.md
  pine-compatibility.md
  feature-matrix.md
  diagnostics.md
  runtime-contract.md
  codegen.md
  backtesting.md
  request-data.md
  limitations.md
  migration.md
  contributing.md
  release-policy.md
  security.md
```

## 11.2. Compatibility docs

Обязательная публичная таблица:

| Feature | Parser | Semantic | Codegen | Runtime | Oracle verified | Notes |
|---|---:|---:|---:|---:|---:|---|
| `plot(close)` | yes | yes | yes | yes | yes | baseline |
| `request.security` dynamic | yes/partial | partial | partial | no/partial | no | exact scope |
| `strategy.entry` market | yes | yes | intent | broker required | partial | ... |

## 11.3. Diagnostics catalog

Каждая diagnostic code page должна включать:

- code;
- severity;
- message;
- example invalid code;
- explanation;
- fix suggestion;
- profile behavior;
- introduced version.

Пример:

```md
# P2A_CONTRACT_VERSION_MISMATCH

Severity: ERROR  
Profiles: production, oracle  
Meaning: AST producer metadata does not match required runtime contract.
Fix: regenerate AST with compatible pine2ast version or update ast2python/pinelib.
```

## 11.4. README

README каждого пакета должен содержать:

- clear scope;
- install from PyPI/internal registry;
- quickstart;
- CLI examples;
- Python API examples;
- support matrix link;
- limitations;
- release compatibility table;
- “not financial advice / not broker / backtest limitations” notice;
- badges for CI, coverage, package, license.

---

# 12. Acceptance criteria для заявления “production-ready”

## 12.1. Минимум для production subset

Продукт можно назвать production-ready для verified subset, если:

- wheel/sdist устанавливаются в чистом окружении;
- все P0 packaging/import ошибки исправлены;
- production profile fail-closed;
- нет silent unsupported lowering;
- AST/codegen deterministic;
- documented compatibility matrix опубликована;
- docs включают limitations и diagnostics catalog;
- oracle corpus >= минимального baseline;
- CI release gate обязателен;
- runtime contract matrix зафиксирован;
- security/codegen sandbox policy описана;
- performance benchmarks имеют budgets.

## 12.2. Минимум для “TradingView parity”

Заявлять полное соответствие TradingView можно только если:

- покрыт весь Pine v6 Reference Manual по builtins;
- покрыта вся grammar matrix;
- реализован Pine execution model: historical/realtime, rollback, commit, `var`/`varip`, series;
- реализован `request.*` data layer с dynamic requests;
- реализован strategy broker emulator и Strategy Tester metrics;
- реализованы TradingView limits или documented compatible diagnostics;
- oracle tests проходят на большом корпусе;
- все расхождения documented as known deviations;
- support matrix не содержит unknown areas.

---

# 13. Backlog задач

## P0 — блокеры продукта

### P0.1. Исправить упаковку `ast2python.translator_mixins`

**DoD:** wheel install smoke test проходит.

### P0.2. Ввести unified compatibility matrix

**DoD:** каждый feature имеет parser/semantic/codegen/runtime/oracle статус.

### P0.3. Сделать release gate на installed artifacts

**DoD:** CI собирает wheel/sdist, ставит в чистый venv, запускает smoke/integration tests.

### P0.4. Зафиксировать scope claims

**DoD:** README/docs не обещают full TradingView parity; формулировка — verified subset.

### P0.5. Расширить oracle corpus

**DoD:** corpus покрывает official examples + real-world baseline; отчёт сохраняется в CI artifact.

### P0.6. Builtin registry redesign

**DoD:** registry различает official/implemented/lowerable/runtime/oracle statuses.

### P0.7. Runtime/backtester ownership decision

**DoD:** документировано, где реализуются execution model, request layer, broker emulator: в `PineLib`, новом пакете или вне scope.

### P0.8. Production fail-closed audit

**DoD:** все unsafe flags запрещены в production; тесты подтверждают blocking errors.

## P1 — обязательные улучшения продукта

### P1.1. Full docs site

**DoD:** опубликован docs site с API, CLI, diagnostics, compatibility matrix.

### P1.2. Semantic overload correctness

**DoD:** overload fixtures проходят; нет short-name collision bugs.

### P1.3. Request/security plan

**DoD:** `request.*` lowering/runtime plan documented and tested.

### P1.4. Strategy intent schema

**DoD:** stable JSON schema for strategy events.

### P1.5. Performance benchmarks

**DoD:** benchmark suite запускается в CI и ловит regression.

### P1.6. Security hardening

**DoD:** no eval, sanitized module names, path traversal tests, SBOM.

### P1.7. Import/library resolver

**DoD:** local resolver and unsupported import diagnostics.

## P2 — зрелость и масштабирование

### P2.1. Public conformance dashboard

**DoD:** badge/report показывает coverage per feature category.

### P2.2. Fuzzing

**DoD:** nightly fuzz job сохраняет crashes/regressions.

### P2.3. Mutation testing

**DoD:** critical semantic/codegen modules имеют mutation score threshold.

### P2.4. Plugin architecture

**DoD:** data providers/backtest reports можно подключать без fork core.

### P2.5. IDE/LSP tooling

**DoD:** diagnostics/source maps можно использовать в editor integration.

---

# 14. Рекомендуемые изменения в репозиториях

## 14.1. `pine2ast`

```text
pine2ast/
  compatibility/
    feature_matrix.json
    builtins_v6_full.json
    official_refs.json
  oracle/
    fixtures/
    reports/
  docs/
  scripts/
    update_builtin_registry.py
    run_oracle_suite.py
  tests/
    grammar/
    semantic/
    oracle/
    fuzz/
```

Изменения:

- добавить compatibility analyzer;
- расширить builtin registry;
- добавить grammar feature IDs;
- добавить oracle report generator;
- добавить docs/diagnostics pages;
- увеличить coverage threshold;
- добавить packaging smoke.

## 14.2. `ast2python`

```text
ast2python/
  codegen/
  contracts/
  compatibility/
  docs/
  tests/
    wheel_install/
    golden_codegen/
    runtime_outputs/
    fail_closed/
```

Изменения:

- перейти на package auto-discovery;
- ввести generated module metadata block;
- сделать strategy intent schema отдельным контрактом;
- добавить codegen security tests;
- добавить performance benchmark;
- добавить docs for generated code contract.

---

# 15. API/CLI требования

## 15.1. Unified CLI

```bash
openpine check script.pine --profile production --format human,json,sarif
openpine parse script.pine --out script.ast.json
openpine translate script.pine --target python --out generated/
openpine run script.pine --bars bars.csv --out outputs.json
openpine backtest strategy.pine --bars bars.csv --report report.html --json report.json
openpine feature-matrix --format markdown
openpine diagnostics explain P2A_CONTRACT_VERSION_MISMATCH
openpine oracle run tests/oracle --report oracle.json
```

## 15.2. Python API

```python
from openpine import compile_pine, run_indicator, backtest_strategy

compiled = compile_pine(
    source,
    profile="production",
    target="python",
)

result = run_indicator(compiled, bars)
report = backtest_strategy(compiled, bars, settings={"initial_capital": 10000})
```

## 15.3. Error model

```python
class OpenPineDiagnostic:
    code: str
    severity: Literal["INFO", "WARNING", "ERROR", "FATAL"]
    message: str
    span: SourceSpan
    hint: str | None
    feature_id: str | None
    docs_url: str | None
```

---

# 16. Security requirements

## 16.1. Threat model

Input `.pine` and AST JSON are untrusted. Generated Python is potentially dangerous if executed without sandboxing.

## 16.2. Требования

- Запрет `eval`/`exec` на user-controlled fragments.
- AST schema validation before codegen.
- Module/class/function name sanitization.
- Output path normalization; no path traversal.
- Generated code imports only allowlisted runtime modules.
- Production service executes generated code in sandbox/container.
- Dependency pinning and SBOM.
- Secret scanning in CI.
- No arbitrary network/file access from generated module.

## 16.3. Acceptance criteria

- Malicious module names cannot write outside output dir.
- Malicious AST cannot inject Python syntax into generated code.
- Security tests run in CI.

---

# 17. Release/versioning policy

## 17.1. Semantic versioning

- `MAJOR`: breaking AST/runtime contract.
- `MINOR`: new supported Pine features/builtins.
- `PATCH`: bugfixes without contract break.

## 17.2. Compatibility table

```text
pine2ast 2.17.x -> AST contract pain.ast_contract.v1 -> ast2python 2.17.x -> runtime contract 1.4 -> pinelib 2.17.x
```

## 17.3. Release artifacts

- wheel;
- sdist;
- SBOM;
- coverage report;
- oracle report;
- benchmark report;
- changelog;
- feature matrix snapshot.

---

# 18. Definition of Done по проекту

Продуктовая версия считается готовой, когда:

1. Установка из wheel работает в чистом окружении.
2. CLI и Python API документированы и протестированы.
3. Все P0 задачи закрыты.
4. Feature matrix опубликована.
5. Все unsupported features дают diagnostics.
6. Нет silent approximations в production.
7. Oracle suite проходит с опубликованным отчётом.
8. Runtime/backtester scope либо реализован, либо явно вынесен за пределы claims.
9. Security tests проходят.
10. Benchmark regressions отслеживаются.
11. Changelog и release notes готовы.
12. Документация не обещает больше, чем реально подтверждено тестами.

---

# 19. Краткая дорожная карта без сроков

## Milestone A — Stabilization

- Исправить packaging `ast2python`.
- Добавить wheel install CI.
- Зафиксировать compatibility matrix skeleton.
- Обновить README claims.
- Добавить release compatibility table.

## Milestone B — Conformance foundation

- Собрать official examples corpus.
- Расширить real-world corpus.
- Ввести oracle report format.
- Покрыть parser/AST/semantic golden tests.

## Milestone C — Builtins/semantics

- Перепроектировать builtin registry.
- Добавить overload tests.
- Расширить qualifier/type inference.
- Добавить diagnostics catalog.

## Milestone D — Codegen productization

- Закрыть unsupported lowering gaps.
- Стабилизировать generated module schema.
- Добавить strategy intent schema.
- Добавить codegen security tests.

## Milestone E — Runtime parity foundation

- Реализовать/аудировать PineLib execution model.
- Добавить series/rollback/varip tests.
- Добавить visual recorder parity tests.
- Начать `request.*` data abstraction.

## Milestone F — Strategy/backtester

- Реализовать broker emulator.
- Добавить strategy reports.
- Сравнить с official strategy examples.
- Документировать known deviations.

## Milestone G — Product release

- Публичная docs site.
- Release artifacts.
- SBOM/security report.
- Conformance dashboard.

---

# 20. Источники для повторного аудита

Для повторной проверки использовать:

- README и `pyproject.toml` обоих репозиториев.
- Файлы `pine2ast/api.py`, `pine2ast/semantic/*`, `pine2ast/parser/*`, `pine2ast/lexer/*`.
- Файлы `ast2python/translator.py`, `ast2python/call_handlers_*`, `ast2python/binder.py`, `ast2python/profiles.py`, `ast2python/runtime_contract/*`.
- Official TradingView Pine Script docs:
  - Execution model;
  - Built-ins;
  - Strategies;
  - Other timeframes and data;
  - Limitations;
  - Migration to v6;
  - v6 Reference Manual.

---

# 21. Проверочный чеклист для следующего аудита

```bash
# 1. clone
 git clone <pine2ast>
 git clone <ast2python>
 git clone <pinelib>

# 2. clean env install
 python -m venv .venv
 . .venv/bin/activate
 pip install -U pip build

# 3. build packages
 cd pine2ast && python -m build
 cd ../ast2python && python -m build

# 4. install wheels into clean env
 python -m venv /tmp/openpine-wheel-test
 /tmp/openpine-wheel-test/bin/pip install pine2ast/dist/*.whl ast2python/dist/*.whl

# 5. import smoke
 /tmp/openpine-wheel-test/bin/python - <<'PY'
 import pine2ast
 import ast2python
 import ast2python.translator
 print('imports ok')
 PY

# 6. run tests
 pytest tests/unit tests/integration --cov

# 7. run cross project e2e
 pine2ast parse sample.pine --json sample.ast.json
 ast2python translate sample.ast.json -o generated/
 ast2python smoke generated/sample.py --bars sample_bars.csv

# 8. run oracle/conformance
 openpine oracle run oracle/fixtures --report oracle.json
```

---

# 22. Финальная рекомендация

Проекты стоит развивать не как “полный TradingView clone” на текущем этапе, а как **строго верифицируемый compiler/runtime subset**, где каждое поддерживаемое поведение доказано тестом и oracle evidence, а каждое неподдерживаемое поведение fail-closed диагностируется.

Путь к продуктовому виду:

1. Закрыть P0 packaging/release issues.
2. Ввести публичную compatibility matrix.
3. Расширить oracle corpus.
4. Достроить builtin registry и semantic model.
5. Отдельно реализовать/аудировать PineLib runtime, request layer и broker emulator.
6. Только после этого расширять claims до TradingView parity.
