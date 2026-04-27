# Pine2AST — ТЗ 1.4 на остаток доработок после v2.6.0

**Версия документа:** 1.4  
**Дата:** 2026-04-26  
**База кода:** `pine2ast_interpipe_v2_6_0`  
**Предыдущая база:** `pine2ast_interpipe_v2_4_0` + частичный semantic-hardening port.

## 1. Статус v2.6.0

В v2.6.0 активный stdlib-runner проходит `132 passed`, real-world corpus восстановлен до 300 fixtures, quality gate зелёный.

Compatibility harness v1.18 добавлен в `tests/unit_legacy_v1_18/`, но остаётся non-blocking. Porting matrix: `ported=66`, `obsolete=29`, `blocked=10`.

## 2. Что закрыто в v2.6.0

1. Duplicate enum members.
2. Unknown enum member access.
3. Duplicate UDT fields.
4. Unknown scalar/UDT/collection method calls.
5. UDT field call as non-callable.
6. Tuple destructuring non-tuple initializer.
7. Tuple destructuring arity mismatch.
8. `_` target in `for-in` no longer leaks to symbol table.
9. Unary `not` requires bool.
10. `map.get()` key type validation in function and method forms.
11. `array.from()` mixed non-numeric arrays reject typed assignment.
12. `ta.macd` tuple return metadata.
13. `ArrayLiteralExpr = TupleExpr` compatibility alias.

## 3. Остаток P0/P1

### P0 — scope and shadowing

- Add active tests for local scope leakage.
- Add active tests for local shadowing not destroying global symbol.
- Confirm whether tuple/function local declarations need stricter symbol lifetime diagnostics.

### P0 — for-in target policy

- Decide Pine-v6-compatible behavior for duplicate for-in targets.
- Add diagnostic for duplicate targets while ignoring `_`.
- Verify whether for-in destructuring with more than two targets is valid or must be rejected.

### P1 — export/library policy

- Implement `export` allowed only for `library()` scripts.
- Keep current library-positive behavior clean.

### P1 — history-reference hardening

- Add static negative-offset diagnostics for `close[-1]`.
- Keep non-constant/unknown offset behavior as warning or info only after doc verification.

### P1 — namespace strictness

- Unknown builtin namespace member diagnostics are still risky because the builtin registry is incomplete.
- Before enabling strict namespace member errors, expand registry coverage or maintain an allowlist/unknown namespace policy.

### P1 — strategy script-type aware validation

- `strategy.*` namespace calls should be policy-checked against `strategy()` scripts.
- Avoid false positives in libraries or indicator helper functions until script-type context is stable.

## 4. DoD for next release

1. `python -S tools/run_tests_no_pytest.py` stays green.
2. `validate-corpus` and `quality-gate` stay green on 300 real-world fixtures.
3. Porting matrix blocked count decreases by at least 5.
4. No public AST schema break without docs/schema version bump.
5. New semantic behavior has active tests under `tests/unit/`.
