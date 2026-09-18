"""Request return types and exact source-expression binding."""
import pytest
from pine2ast import parse_code

@pytest.mark.parametrize(
    "arguments", ['"EX:S","1",[close,open]', 'expression=[close,open],symbol="EX:S",timeframe="1"']
)
def test_lower_tuple_provides_independent_array_element_types(arguments):
    result = parse_code(
        f'//@version=6\nindicator("tuple")\n[a,b]=request.security_lower_tf({arguments})\nx=array.get(a,0)\n'
    )
    assert result.ok, result.diagnostics
    assert any(
        f.kind == "CallExpr" and f.resolved_type.base == "float"
        for f in result.semantic_model.semantic_facts.facts
    )


def test_named_order_cannot_bypass_mutable_expression_rule():
    result = parse_code(
        '//@version=6\nindicator("mutable")\nx=close\nx:=close+1\ny=request.security(expression=x,timeframe="5",symbol="EX:S")\n'
    )
    assert not result.ok
