from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code


def _diagnostics(source: str, *, strict_builtin_namespaces: bool = False):
    return parse_code(
        source,
        ParseOptions(run_semantic=True, strict_builtin_namespaces=strict_builtin_namespaces),
    ).diagnostics


def _codes(source: str, *, strict_builtin_namespaces: bool = False) -> list[str]:
    return [
        d.code for d in _diagnostics(source, strict_builtin_namespaces=strict_builtin_namespaces)
    ]


def _error_codes(source: str, *, strict_builtin_namespaces: bool = False) -> list[str]:
    return [
        d.code
        for d in _diagnostics(source, strict_builtin_namespaces=strict_builtin_namespaces)
        if d.severity.value in {"ERROR", "FATAL"}
    ]


def test_equal_declares_and_coloneq_reassigns_existing_symbol():
    assert _error_codes("""//@version=6
indicator("T")
x = 1
x := 2
""") == []
    assert "P2A1102" in _error_codes("""//@version=6
indicator("T")
x = 1
x = 2
""")
    assert "P2A1103" in _error_codes("""//@version=6
indicator("T")
x := 1
""")


def test_const_reassignment_and_compound_target_type():
    assert "P2A1104" in _error_codes("""//@version=6
indicator("T")
const float x = 1.0
x := 2.0
""")
    assert "P2A1801" in _error_codes("""//@version=6
indicator("T")
string s = "a"
s += "b"
""")


def test_bool_context_v6_and_na_bool_rules():
    codes = _error_codes("""//@version=6
indicator("T")
if close
    x = 1
if na
    y = 2
bool b = na
""")
    assert "P2A1201" in codes
    assert "P2A1202" in codes
    assert "P2A1203" in codes


def test_history_literal_repeated_integer_offset_and_local_warning():
    diagnostics = _diagnostics("""//@version=6
indicator("T")
x = 1[2]
y = close[1][2]
z = close[1.5]
if true
    local = close
    w = local[1]
""")
    codes = [d.code for d in diagnostics]
    assert "P2A1301" in codes
    assert "P2A1302" in codes
    assert "P2A1303" in codes
    assert any(d.code == "P2A1304" and d.severity.value == "WARNING" for d in diagnostics)


def test_break_continue_and_nested_function_method_rejected_outside_allowed_scope():
    codes = _error_codes("""//@version=6
indicator("T")
type Foo
    int x
break
continue
if true
    f() => 1
    method get(Foo this) => this.x
""")
    assert codes.count("P2A1701") == 2
    assert codes.count("P2A1601") == 2


def test_import_alias_conflict_and_unknown_builtin_strict_mode():
    assert "P2A1102" in _error_codes("""//@version=6
indicator("T")
import user/lib/1 as math
x = math.foo()
""")
    strict_codes = _error_codes(
        """//@version=6
indicator("T")
x = ta.definitely_missing(close)
""",
        strict_builtin_namespaces=True,
    )
    assert "P2A1506" in strict_codes
