# Pine2AST — ТЗ 1.5 на остаток доработок после v2.7.0

**Версия документа:** 1.5  
**Дата:** 2026-04-26  
**База кода:** `pine2ast_interpipe_v2_7_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_6_0`

## 1. Статус v2.7.0

В v2.7.0 активный stdlib-runner проходит `138 passed`, real-world corpus на 300 fixtures остаётся зелёным, quality gate зелёный с одним ожидаемым warning `P2A1304`.

Закрыт следующий P0/P1-блок из ТЗ 1.4:

1. Local scope leakage: out-of-scope local declarations больше не резолвятся.
2. Local shadowing: локальный symbol больше не уничтожает глобальный symbol после выхода из scope.
3. Duplicate for-in targets: диагностируются, `_` игнорируется.
4. `export` policy: export разрешён только в `library()` scripts.
5. History hardening: статический отрицательный offset `close[-1]` диагностируется.
6. Strategy script-type validation: основные `strategy.*` order/risk calls требуют `strategy()` script.

## 2. Что закрыто до v2.7.0 включительно

1. Duplicate enum members.
2. Unknown enum member access.
3. Duplicate UDT fields.
4. Unknown scalar/UDT/collection method calls.
5. UDT field call as non-callable.
6. Tuple destructuring non-tuple initializer.
7. Tuple destructuring arity mismatch.
8. `_` target in `for-in` no longer resolves as a variable.
9. Unary `not` requires bool.
10. `map.get()` key type validation in function and method forms.
11. `array.from()` mixed non-numeric arrays reject typed assignment.
12. `ta.macd` tuple return metadata.
13. `ArrayLiteralExpr = TupleExpr` compatibility alias.
14. Scope leakage/shadowing hardening.
15. Export-only-library semantic policy.
16. Negative static history offset diagnostics.
17. Strategy call script-type diagnostics.

## 3. Остаток P0/P1

### P0 — parser-level for-in arity

Сейчас parser принимает только `for name in ...` и `for [a, b] in ...`. Semantic diagnostic `P2A1902 FOR_IN_TARGET_ARITY` уже добавлен, но parser-level recovery для `for [a, b, c] in ...` ещё нужно сделать явно:
- принять конструкцию recovery-образом;
- выдать `P2A1902`;
- не зациклиться и восстановиться до block body.

### P1 — namespace strictness

Unknown builtin namespace member diagnostics остаются рискованными из-за неполного registry. Перед включением strict mode нужно:
- расширить `builtins_v6.json`;
- добавить allowlist policy для `namespace.member` unknown;
- отделить `ERROR` для точно известных namespaces от `INFO/WARNING` для неполной registry.

### P1 — strategy validation expansion

В v2.7.0 проверяются order/risk calls. Нужно расширить script-type-aware validation:
- отделить strategy state variables/constants от order functions;
- проверить `strategy.closedtrades.*` / `strategy.opentrades.*` как read-only namespaces;
- не ломать libraries, которые только возвращают strategy constants.

### P1 — import resolution v2 backlog

Остаётся неизменным:
- optional external library resolver;
- offline cache;
- import lockfile;
- analysis of exported symbols from imported libraries.

### P1 — richer type flow

Нужны дополнительные проверки:
- flow-sensitive narrowing для `na`;
- уточнение `series<T>` vs scalar `T`;
- operator result type inference для mixed int/float;
- richer tuple return inference for user functions with block bodies.

## 4. DoD for next release

1. `python -S tools/run_tests_no_pytest.py` stays green.
2. `validate-corpus` and `quality-gate` stay green on 300 real-world fixtures.
3. Add active tests for parser-level malformed `for-in` destructuring recovery.
4. No public AST schema break without docs/schema version bump.
5. New semantic behavior has active tests under `tests/unit/`.
