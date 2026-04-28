from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import (
    EnumDeclaration,
    FunctionDeclaration,
    ImportDeclaration,
    MethodDeclaration,
    TupleDeclaration,
    TypeDeclaration,
)


def parse_items(src):
    res = parse_code(src, ParseOptions(run_semantic=False))
    assert res.ast is not None, [d.to_dict() for d in res.diagnostics]
    assert not [d for d in res.diagnostics if d.severity.value in {"FATAL", "ERROR"}], [
        d.to_dict() for d in res.diagnostics
    ]
    return res.ast.items


def test_type_enum_tuple_function_method_import():
    src = """//@version=6
indicator("All")
import user/Lib/1 as lib
type Pivot
    int x
    float y = na
enum Trend
    UP
    DOWN
[basis, upper, lower] = ta.bb(close, 20, 2)
f(float price, int len = 14) => price + len
method isBullish(Pivot p) => p.y > close
"""
    items = parse_items(src)
    assert any(isinstance(x, ImportDeclaration) for x in items)
    assert any(isinstance(x, TypeDeclaration) for x in items)
    assert any(isinstance(x, EnumDeclaration) for x in items)
    assert any(isinstance(x, TupleDeclaration) for x in items)
    assert any(isinstance(x, FunctionDeclaration) for x in items)
    assert any(isinstance(x, MethodDeclaration) for x in items)


def test_method_body_export_and_receiver_shape_regression():
    src = """//@version=6
library("Lib")
type Pivot
    float y
export method isBullish(Pivot p, int len = 14) => p.y > close and len > 0
"""
    items = parse_items(src)
    method = next(x for x in items if isinstance(x, MethodDeclaration))
    assert not isinstance(method.body, bool)
    assert method.is_exported is True
    assert method.receiver_type is not None
    assert method.receiver_type.name == "Pivot"
    assert method.receiver_name == "p"
    assert [param.name for param in method.parameters] == ["len"]
    assert method.parameters[0].type_ref is not None
    assert method.parameters[0].type_ref.name == "int"
