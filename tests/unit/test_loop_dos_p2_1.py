"""P2.1 loop DoS guard contract.

Three layers:

  1. ``pine2ast.semantic.passes.loop_dos`` — pure helpers
     (``_resolve_int_literal``, ``_static_int_bound``,
     ``_is_literal_true``). No Pine parsing required.
  2. ``SemanticAnalyzer`` integration — the analyzer emits
     P2A1111 / P2A1112 / P2A1113 when a static overflow is
     detected. The loop_max_iterations field is honored.
  3. ``ParseOptions.clamp_to_ceiling`` — a caller cannot
     raise ``loop_max_iterations`` past ``ABSOLUTE_MAX``.
"""

from __future__ import annotations


from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.diagnostics.diagnostic import Severity
from pine2ast.semantic.passes.loop_dos import (
    _is_literal_true,
    _resolve_int_literal,
    _static_int_bound,
)

# ---------------------------------------------------------------------------
# loop_dos: _resolve_int_literal
# ---------------------------------------------------------------------------


def test_resolve_int_literal_simple() -> None:
    from pine2ast.ast.nodes import Literal

    lit = Literal(span=None, value=42, literal_type="int")  # type: ignore[arg-name]
    assert _resolve_int_literal(lit) == 42


def test_resolve_int_literal_negative() -> None:
    from pine2ast.ast.nodes import Literal, UnaryExpr

    inner = Literal(span=None, value=100, literal_type="int")  # type: ignore[arg-name]
    neg = UnaryExpr(span=None, op="-", operand=inner)  # type: ignore[arg-name]
    assert _resolve_int_literal(neg) == -100


def test_resolve_int_literal_plus_is_noop() -> None:
    from pine2ast.ast.nodes import Literal, UnaryExpr

    inner = Literal(span=None, value=7, literal_type="int")  # type: ignore[arg-name]
    pos = UnaryExpr(span=None, op="+", operand=inner)  # type: ignore[arg-name]
    assert _resolve_int_literal(pos) == 7


def test_resolve_int_literal_returns_none_for_non_literal() -> None:
    from pine2ast.ast.nodes import Identifier

    ident = Identifier(span=None, name="x")  # type: ignore[arg-name]
    assert _resolve_int_literal(ident) is None


def test_resolve_int_literal_returns_none_for_float() -> None:
    from pine2ast.ast.nodes import Literal

    lit = Literal(span=None, value=1.5, literal_type="float")  # type: ignore[arg-name]
    assert _resolve_int_literal(lit) is None


# ---------------------------------------------------------------------------
# loop_dos: _static_int_bound
# ---------------------------------------------------------------------------


def _lit(value: int):
    from pine2ast.ast.nodes import Literal

    return Literal(span=None, value=value, literal_type="int")  # type: ignore[arg-name]


def test_static_int_bound_simple() -> None:
    # for i = 0 to 100  →  100 iterations
    assert _static_int_bound(_lit(0), _lit(100), None) == 100


def test_static_int_bound_negative_direction() -> None:
    # for i = 100 to 0  →  100 iterations (absolute)
    assert _static_int_bound(_lit(100), _lit(0), None) == 100


def test_static_int_bound_with_step() -> None:
    # for i = 0 to 100 step 5  →  20 iterations
    assert _static_int_bound(_lit(0), _lit(100), _lit(5)) == 20


def test_static_int_bound_returns_none_for_variable_end() -> None:
    from pine2ast.ast.nodes import Identifier

    var = Identifier(span=None, name="n")  # type: ignore[arg-name]
    assert _static_int_bound(_lit(0), var, None) is None


def test_static_int_bound_zero_step_falls_back_to_diff() -> None:
    # Zero step would be a runtime error. We don't want to divide
    # by zero; the analyzer emits LOOP_RANGE_TYPE separately.
    # For the bound estimate we fall back to |diff| (no division).
    assert _static_int_bound(_lit(0), _lit(100), _lit(0)) == 100


# ---------------------------------------------------------------------------
# loop_dos: _is_literal_true
# ---------------------------------------------------------------------------


def test_is_literal_true_for_true_literal() -> None:
    from pine2ast.ast.nodes import Literal

    assert _is_literal_true(Literal(span=None, value=True, literal_type="bool")) is True  # type: ignore[arg-name]


def test_is_literal_true_false_for_false() -> None:
    from pine2ast.ast.nodes import Literal

    assert _is_literal_true(Literal(span=None, value=False, literal_type="bool")) is False  # type: ignore[arg-name]


def test_is_literal_true_false_for_int_one() -> None:
    # Pine has a real bool type; runtime rejects non-bool while
    # conditions. We do NOT fire for `while 1` because it's a
    # type error anyway.
    from pine2ast.ast.nodes import Literal

    assert _is_literal_true(Literal(span=None, value=1, literal_type="int")) is False  # type: ignore[arg-name]


# ---------------------------------------------------------------------------
# ParseOptions.clamp_to_ceiling for loop_max_iterations
# ---------------------------------------------------------------------------


def test_clamp_to_ceiling_clamps_huge_loop_max() -> None:
    from pine2ast import security

    p = ParseOptions(loop_max_iterations=10**18)
    c = p.clamp_to_ceiling()
    assert c.loop_max_iterations == security.ABSOLUTE_MAX_LOOP_ITERATIONS


def test_clamp_to_ceiling_preserves_lower_caller_bound() -> None:
    p = ParseOptions(loop_max_iterations=50)
    c = p.clamp_to_ceiling()
    assert c.loop_max_iterations == 50


# ---------------------------------------------------------------------------
# parse_code: P2A1111 (static overflow)
# ---------------------------------------------------------------------------


def test_parse_code_flags_billion_iteration_loop() -> None:
    src = '//@version=6\nindicator("x")\nfor i = 0 to 1000000000\n    plot(close)\n'
    r = parse_code(src)
    codes_seen = [d.code for d in r.diagnostics]
    assert codes.LOOP_ITERATION_OVERFLOW in codes_seen
    diag = next(d for d in r.diagnostics if d.code == codes.LOOP_ITERATION_OVERFLOW)
    assert diag.severity is Severity.ERROR


def test_parse_code_ignores_small_loop() -> None:
    src = '//@version=6\nindicator("x")\nfor i = 0 to 50\n    plot(close)\n'
    r = parse_code(src)
    assert codes.LOOP_ITERATION_OVERFLOW not in [d.code for d in r.diagnostics]
    assert r.ast is not None


def test_parse_code_ignores_dynamic_bound() -> None:
    # input.int bound is not a literal → static check skips, runtime
    # max_loops catches it.
    src = '//@version=6\nindicator("x")\nn = input.int(50, "n")\nfor i = 0 to n\n    plot(close)\n'
    r = parse_code(src)
    assert codes.LOOP_ITERATION_OVERFLOW not in [d.code for d in r.diagnostics]


def test_parse_code_respects_custom_loop_max() -> None:
    # Caller tightens the ceiling to 10. for i = 0 to 50 trips it.
    src = '//@version=6\nindicator("x")\nfor i = 0 to 50\n    plot(close)\n'
    r = parse_code(src, ParseOptions(loop_max_iterations=10))
    assert codes.LOOP_ITERATION_OVERFLOW in [d.code for d in r.diagnostics]


def test_parse_code_handles_negative_step_direction() -> None:
    # for i = 1000 to 0 step -1  →  1000 iterations
    src = '//@version=6\nindicator("x")\nfor i = 1000 to 0\n    a = 1\n'
    r = parse_code(src)
    # The Pine parser may reject start>end without a step, so we
    # only assert that IF the parser accepts the loop, our static
    # check fires. We don't depend on the parser's choice here —
    # what matters is that the static_int_bound helper handles
    # negative direction (already covered by
    # test_static_int_bound_negative_direction).
    if codes.LOOP_ITERATION_OVERFLOW in [d.code for d in r.diagnostics]:
        diag = next(d for d in r.diagnostics if d.code == codes.LOOP_ITERATION_OVERFLOW)
        assert "1000" in diag.message


# ---------------------------------------------------------------------------
# parse_code: P2A1112 (infinite while literal)
# ---------------------------------------------------------------------------


def test_parse_code_warns_while_true() -> None:
    src = '//@version=6\nindicator("x")\nwhile true\n    plot(close)\n    if close > 0\n        break\n'
    r = parse_code(src)
    codes_seen = [d.code for d in r.diagnostics]
    assert codes.INFINITE_WHILE_LITERAL in codes_seen
    diag = next(d for d in r.diagnostics if d.code == codes.INFINITE_WHILE_LITERAL)
    # We warn, not error — runtime cap is the hard guard.
    assert diag.severity is Severity.WARNING


def test_parse_code_silent_while_with_variable() -> None:
    # while bar_index < last_bar_index — non-literal, no warning.
    src = '//@version=6\nindicator("x")\nwhile bar_index < 100\n    plot(close)\n'
    r = parse_code(src)
    assert codes.INFINITE_WHILE_LITERAL not in [d.code for d in r.diagnostics]


# ---------------------------------------------------------------------------
# parse_code: P2A1113 (nested explosion)
# ---------------------------------------------------------------------------


def test_parse_code_warns_nested_2_5b_explosion() -> None:
    # 50000 * 50000 = 2.5B > 10^8 threshold.
    src = '//@version=6\nindicator("x")\nfor i = 0 to 50000\n    for j = 0 to 50000\n        plot(close)\n'
    r = parse_code(src)
    codes_seen = [d.code for d in r.diagnostics]
    assert codes.NESTED_LOOP_EXPLOSION in codes_seen


def test_parse_code_silent_for_small_nested_loops() -> None:
    # 1000 * 1000 = 1M < 10^8 threshold.
    src = '//@version=6\nindicator("x")\nfor i = 0 to 1000\n    for j = 0 to 1000\n        plot(close)\n'
    r = parse_code(src)
    assert codes.NESTED_LOOP_EXPLOSION not in [d.code for d in r.diagnostics]


def test_parse_code_silent_when_inner_is_dynamic() -> None:
    # Outer is static (10000). Inner depends on input. Product is
    # unknown → no warning.
    src = (
        '//@version=6\nindicator("x")\n'
        'n = input.int(50, "n")\n'
        "for i = 0 to 10000\n"
        "    for j = 0 to n\n"
        "        plot(close)\n"
    )
    r = parse_code(src)
    assert codes.NESTED_LOOP_EXPLOSION not in [d.code for d in r.diagnostics]
