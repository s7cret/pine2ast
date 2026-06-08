"""P2.1: static DoS guards for Pine loops.

Pine runtime caps loops at 100,000 iterations per script run. The
P2.1 work catches the obvious static cases at parse time so the
gateway can reject the script *before* even trying to run it:

  - ``for i = 0 to 999_999_999`` — both bounds are int literals,
    the absolute iteration count is statically known.
  - ``for i = 0 to -999_999_999`` — same, in reverse.
  - ``while true`` / ``while 1`` — the condition is a literal
    bool/int. Almost always a typo.
  - Nested for-ranges with both legs statically bounded — the
    product can exceed 10^8 even when each leg is well under
    the per-loop ceiling.

What we *do not* catch (out of scope, runtime concerns):

  - Loops whose bound is an input.* parameter. By the time the
    script runs, the input has a value; the runtime enforces.
  - Loops whose bound is a series-typed expression like
    ``bar_index``. Bounded by chart history; runtime enforces.
  - Side-effect DoS like ``strategy.entry`` in a hot loop. Not
    a loop count issue, it's an order-count issue.
"""

from __future__ import annotations

from typing import Optional

from pine2ast.ast.nodes import Expression, Literal, UnaryExpr


def _resolve_int_literal(expr: Expression) -> Optional[int]:
    """Return the int value of ``expr`` if it is statically a single
    int literal, possibly with a leading ``-`` or ``+``. Returns
    ``None`` for anything else (variable, binary expr, float)."""
    if isinstance(expr, Literal) and expr.literal_type == "int":
        try:
            return int(expr.value)  # type: ignore[arg-type, call-overload]
        except (TypeError, ValueError):
            return None
    if isinstance(expr, UnaryExpr) and expr.op in {"-", "+"}:
        inner = _resolve_int_literal(expr.operand)
        if inner is None:
            return None
        return -inner if expr.op == "-" else inner
    return None


def _static_int_bound(
    start: Expression,
    end: Expression,
    step: Expression | None,
) -> Optional[int]:
    """Return ``abs(end - start) / max(1, abs(step))`` if all three
    are static int literals, else ``None``.

    The function is intentionally conservative: any non-literal in
    any of the three positions returns ``None``, and the analyzer
    skips the static check (the runtime's max_loops catches it).
    """
    s = _resolve_int_literal(start)
    e = _resolve_int_literal(end)
    if s is None or e is None:
        return None
    diff = abs(e - s)
    if step is None:
        return diff
    st = _resolve_int_literal(step)
    if st is None or st == 0:
        # Step is non-literal or zero. Zero would be a runtime
        # error; let the type checker handle it. For our static
        # count, fall back to |diff| (no division).
        return diff
    # Step may be negative; what we care about is the absolute
    # count of iterations.
    abs_step = abs(st)
    return diff // abs_step


def _is_literal_true(expr: Expression) -> bool:
    """True if the expression is the literal ``true`` or a non-zero
    int literal. We do *not* treat ``1`` (a generic int) as
    ``true``-equivalent in Pine — Pine has a real bool type, and
    the runtime will reject a non-bool while condition with a
    type error. We only fire for the actual ``true`` literal."""
    if isinstance(expr, Literal):
        if expr.literal_type == "bool":
            return bool(expr.value) is True
    return False
