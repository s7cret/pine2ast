# P2.1 — Static loop DoS guards

## Scope

Pine Script runtime caps loops at 100,000 iterations per script run
(`max_loops`). P2.1 catches the obvious static cases at *parse* time
so the gateway can reject the script before even attempting to run
it. This complements the runtime guard, it does not replace it — the
runtime remains the source of truth for loops whose bound is dynamic
(input.*, series-typed, etc.).

## Threat model

A malicious or careless Pine author writes:

```pine
// 10^9 iterations
for i = 0 to 1000000000
    plot(close)
```

```pine
// Infinite loop
while true
    strategy.entry(...)
```

```pine
// Multiplicative explosion
for i = 0 to 50000
    for j = 0 to 50000
        compute(close, i, j)
```

The first runs O(N) for N=10⁹ before the runtime caps. The second
runs forever. The third explodes 2.5 × 10⁹ iterations before the
runtime cap. In all three cases the script "compiles clean" today —
no static check fires.

## Contract

| Detection | Code | Severity | Configurable via |
|---|---|---|---|
| Static for-range with `\|end - start\| > ceiling` | **P2A1111** LOOP_ITERATION_OVERFLOW | ERROR | `ParseOptions.loop_max_iterations` |
| Literal `true` while condition | **P2A1112** INFINITE_WHILE_LITERAL | WARNING | always on |
| Nested static-bounded loops with product > 10⁸ | **P2A1113** NESTED_LOOP_EXPLOSION | WARNING | always on |

**Defaults:**
- `ParseOptions.loop_max_iterations = 100_000` (matches Pine runtime)
- `security.ABSOLUTE_MAX_LOOP_ITERATIONS = 10_000_000` (caller cannot raise past this)
- `security.ABSOLUTE_NESTED_LOOP_BOUND = 100_000_000` (10⁸)

A caller that wants a stricter bound (e.g. "this endpoint accepts
scripts with no loop over 1,000 iterations") can lower
`loop_max_iterations` per request. The clamp is a ceiling, not a
floor.

## What we *do not* catch

These are out of scope — runtime concerns:

- Loops whose bound is an `input.int(...)`. By the time the script
  runs the input has a value; the runtime enforces.
- Loops whose bound is a series-typed expression like `bar_index`.
  Bounded by chart history; runtime enforces.
- Side-effect DoS like `strategy.entry` in a hot loop. Not a loop
  count issue, it's an order-count issue. P2.x candidate.
- Loops hidden inside a library function. The library is imported
  whole; the static check would have to run on the resolved
  program. Future work.

## Architecture

```
pine2ast/semantic/passes/loop_dos.py   ← pure helpers (no analyzer dep)
pine2ast/semantic/analyzer.py          ← wires helpers into ForRange + While
pine2ast/api.py                        ← ParseOptions.loop_max_iterations + clamp
pine2ast/security.py                   ← ABSOLUTE_MAX_LOOP_ITERATIONS ceiling
pine2ast/diagnostics/codes.py          ← 3 new codes (P2A1111, 1112, 1113)
```

### `loop_dos.py` helpers

```python
def _resolve_int_literal(expr: Expression) -> Optional[int]:
    # Literal(value, "int") → int(value)
    # UnaryExpr(op="-", operand=Literal) → -int(operand)
    # UnaryExpr(op="+", operand=Literal) → +int(operand)
    # anything else → None

def _static_int_bound(start, end, step) -> Optional[int]:
    # if all three are int literals → abs(end - start) / max(1, abs(step))
    # else → None (skip the check, runtime catches it)

def _is_literal_true(expr: Expression) -> bool:
    # Literal(value=True, "bool") → True
    # everything else (including Literal(1, "int")) → False
```

The first function is intentionally conservative: a `BinaryExpr(0,
+, 1)` is not "a literal", it's a binary expression. The static
check skips it. The runtime catches the dynamic case. No false
negatives (any literal that produces an infinite loop is caught),
no false positives on dynamic loops.

### Analyzer wiring

In `ForRangeStructure` handling, after the existing type checks
(`start`/`end`/`step` must be int-like), we call `_static_int_bound`.
If the bound is non-None and > `self.loop_max_iterations`, we emit
P2A1111 ERROR. We also push the bound onto a parallel stack
(`self._static_loop_bounds`) and pop it on scope exit, so a nested
for-range can cheaply compute `parent_bound * my_bound` and warn
P2A1113 if > 10⁸.

In `WhileStructure` handling, we call `_is_literal_true(condition)`.
If True, we emit P2A1112 WARNING.

## Why WARNING, not ERROR, for while and nested

The runtime enforces both:
- A literal-true `while` loop is capped at 100,000 iterations by
  the runtime. The static check is a "you probably have a bug"
  hint, not a hard reject.
- A nested 50000 × 50000 loop is capped at 100,000 iterations
  by the runtime. We warn so a CI gate can flag it, but a
  legitimate long simulation can still pass.

P2A1111 (single-loop overflow) is ERROR because the runtime caps
at 100k — the script's *intent* is clearly to iterate more than
that, and the runtime will silently truncate. Better to fail
loudly at compile time.

## Files added / changed

| File | Status | Lines |
|---|---|---|
| `pine2ast/semantic/passes/loop_dos.py` | **new** | 84 |
| `pine2ast/semantic/analyzer.py` | edited (ForRange + While) | +75/-5 |
| `pine2ast/api.py` | edited (clamp + thread loop_max_iterations) | +8 |
| `pine2ast/security.py` | edited (2 new ceilings) | +12 |
| `pine2ast/diagnostics/codes.py` | +3 codes | +6 |
| `tests/unit/test_loop_dos_p2_1.py` | **new** | 25 tests, 3 layers |
| `docs/P2_1_LOOP_DOS.md` | **new** | this doc |

## Verification

| Check | Status |
|---|---|
| 25/25 new tests pass | ✅ |
| Full suite: 483 → 508 passed (+25, 0 regressions) | ✅ |
| ruff + black + mypy | ✅ |
| `for i = 0 to 1000000000` → P2A1111 ERROR | ✅ |
| `while true` → P2A1112 WARNING | ✅ |
| nested 50000 × 50000 → P2A1113 WARNING | ✅ |
| nested 1000 × 1000 (1M) → silent | ✅ |
| `for i = 0 to n` (input bound) → silent (runtime handles) | ✅ |
| custom `loop_max_iterations=10` + `for i = 0 to 50` → P2A1111 | ✅ |
| clamp: `loop_max_iterations=10**18` → 10M ceiling | ✅ |

## What is intentionally left for follow-up

- **Loop hidden inside imported library.** Would require
  cross-file resolution. P2.x.
- **`strategy.entry` in a hot loop.** Order-count DoS is a
  different surface. P2.x.
- **Stuck `for-in` over a huge array.** The for-in iterable
  size can also be statically inferred (`array.new<float>(N)` with
  literal N) but it's a P2.x enhancement.
- **Time-bomb: `bar_index + 1` as loop bound.** Effectively
  the entire chart history. The runtime caps; static check would
  need to recognize the bar_index series type which we don't
  yet do.
