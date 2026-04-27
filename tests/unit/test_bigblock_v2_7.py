from pine2ast import parse_code
from pine2ast.diagnostics import codes


def error_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_local_block_declaration_does_not_resolve_after_scope_exit():
    src = """//@version=6
indicator("local leak")
if close > open
    localOnly = 1
x = localOnly
"""
    assert codes.UNDECLARED_VARIABLE in error_codes(src)


def test_local_shadowing_restores_global_symbol_after_scope_exit():
    src = """//@version=6
indicator("shadow")
float x = 1.0
if close > open
    int x = 2
int y = x
"""
    res = parse_code(src)
    errors = [d.code for d in res.diagnostics if d.severity.value in {"ERROR", "FATAL"}]
    assert res.semantic_model.symbols["x"].type == "float"
    assert codes.TYPE_MISMATCH in errors


def test_duplicate_for_in_targets_are_diagnosed_while_blank_is_ignored():
    dup = """//@version=6
indicator("duplicate for-in")
values = array.from(1.0, 2.0)
for [i, i] in values
    x = i
"""
    ok_blank = """//@version=6
indicator("blank for-in")
values = array.from(1.0, 2.0)
for [_, item] in values
    x = item
"""
    assert codes.REDECLARATION in error_codes(dup)
    assert codes.REDECLARATION not in error_codes(ok_blank)


def test_export_is_allowed_only_in_library_scripts():
    indicator_src = """//@version=6
indicator("bad export")
export f() => close
"""
    library_src = """//@version=6
library("ok export")
export f(float x) => x
"""
    assert codes.EXPORT_NOT_LIBRARY in error_codes(indicator_src)
    assert codes.EXPORT_NOT_LIBRARY not in error_codes(library_src)


def test_static_negative_history_offset_is_diagnosed():
    src = """//@version=6
indicator("negative history")
x = close[-1]
"""
    assert codes.HISTORY_NEGATIVE_OFFSET in error_codes(src)


def test_strategy_order_calls_require_strategy_script_type():
    indicator_src = """//@version=6
indicator("bad strategy call")
strategy.entry("L", strategy.long)
"""
    strategy_src = """//@version=6
strategy("ok strategy call")
strategy.entry("L", strategy.long)
"""
    assert codes.STRATEGY_CALL_WRONG_SCRIPT_TYPE in error_codes(indicator_src)
    assert codes.STRATEGY_CALL_WRONG_SCRIPT_TYPE not in error_codes(strategy_src)
