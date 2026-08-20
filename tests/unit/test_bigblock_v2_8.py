from pine2ast import parse_code
from pine2ast.ast.nodes import ForInStructure, TupleDeclaration
from pine2ast.diagnostics import codes


def diag_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics]


def test_parser_recovers_malformed_for_in_destructuring_arity():
    result = parse_code("""//@version=6
indicator("bad-for-in")
values = array.from(1.0, 2.0)
for [i, v, extra] in values
    x = v
plot(close)
""")
    codes_seen = [d.code for d in result.diagnostics]
    assert codes.FOR_IN_TARGET_ARITY in codes_seen
    assert result.ast is not None
    loops = [node for node in result.ast.items if isinstance(node, ForInStructure)]
    assert len(loops) == 1
    assert loops[0].target.names == ["i", "v", "extra"]


def test_strategy_state_variables_require_strategy_but_constants_are_allowed_in_library():
    state_codes = diag_codes("""//@version=6
indicator("state")
x = strategy.equity
""")
    assert codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE in state_codes

    const_result = parse_code("""//@version=6
library("const-lib")
export dir() => strategy.long
""")
    assert codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE not in [d.code for d in const_result.diagnostics]
    assert const_result.ok, [d.to_dict() for d in const_result.diagnostics]


def test_strategy_closedtrades_readonly_functions_are_typed_and_script_checked():
    indicator_codes = diag_codes("""//@version=6
indicator("closed")
p = strategy.closedtrades.entry_price(0)
""")
    assert codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE in indicator_codes

    result = parse_code("""//@version=6
strategy("closed")
p = strategy.closedtrades.entry_price(0)
string id = strategy.closedtrades.entry_id(0)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert result.semantic_model.symbols["p"].type == "float"
    assert result.semantic_model.symbols["id"].type == "string"


def test_unknown_builtin_namespace_member_is_info_not_error():
    result = parse_code("""//@version=6
indicator("unknown-ns")
x = ta.future_unknown(close)
""")
    codes_seen = [d.code for d in result.diagnostics]
    assert codes.UNKNOWN_BUILTIN_MEMBER in codes_seen
    assert codes.UNDECLARED_VARIABLE not in codes_seen
    assert not any(
        d.severity.value == "ERROR" and d.code == codes.UNKNOWN_BUILTIN_MEMBER
        for d in result.diagnostics
    )


def test_forward_block_body_tuple_return_preserves_arity_for_destructuring():
    result = parse_code("""//@version=6
indicator("forward-tuple")
[a, b] = pair(close)
pair(float x) =>
    y = x + 1
    [x, y]
plot(a)
""")
    codes_seen = [d.code for d in result.diagnostics]
    assert codes.TYPE_MISMATCH not in codes_seen
    assert codes.ARGUMENT_COUNT not in codes_seen
    assert result.ast is not None
    assert isinstance(result.ast.items[0], TupleDeclaration)
