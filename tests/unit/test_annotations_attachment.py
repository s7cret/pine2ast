"""Annotation attachment: //@function/param/returns/type/field/enum/variable → AST.documentation."""
from pine2ast import parse_code


def test_function_documentation_attachment():
    src = '''//@function Computes the average
//@param src the source series
//@returns the average value
avg(src) =>
    ta.sma(src, 14)
'''
    result = parse_code(src)
    assert result.ast is not None
    funcs = [d for d in result.ast.items if d.__class__.__name__ == "FunctionDeclaration"]
    assert len(funcs) == 1
    doc = funcs[0].documentation
    assert len(doc) >= 2
    kinds = {a.kind.value for a in doc}
    assert "FUNCTION" in kinds
    param_doc = [a for a in funcs[0].parameters[0].documentation]
    assert len(param_doc) >= 1
    assert param_doc[0].name == "src"


def test_param_documentation_attachment():
    src = '''//@function helper
//@param a the first
//@param b the second
helper(a, b) =>
    a + b
'''
    result = parse_code(src)
    funcs = [d for d in result.ast.items if d.__class__.__name__ == "FunctionDeclaration"]
    assert len(funcs) == 1
    f = funcs[0]
    assert len(f.parameters) == 2
    a_doc = list(f.parameters[0].documentation)
    b_doc = list(f.parameters[1].documentation)
    assert a_doc[0].name == "a"
    assert b_doc[0].name == "b"


def test_returns_documentation_attachment():
    src = '''//@function compute
//@returns the result
compute() =>
    42
'''
    result = parse_code(src)
    funcs = [d for d in result.ast.items if d.__class__.__name__ == "FunctionDeclaration"]
    doc = funcs[0].documentation
    kinds = {a.kind.value for a in doc}
    assert "RETURNS" in kinds


def test_type_documentation_attachment():
    src = '''//@version=6
//@type A point on the chart
//@field x the x coordinate
//@field y the y coordinate
type Point
    int x
    int y
'''
    result = parse_code(src)
    type_decls = [d for d in result.ast.items if d.__class__.__name__ == "TypeDeclaration"]
    assert len(type_decls) == 1
    doc = type_decls[0].documentation
    kinds = {a.kind.value for a in doc}
    assert "TYPE" in kinds
    field_docs = []
    for f in type_decls[0].fields:
        for a in f.documentation:
            if a.kind.value == "FIELD":
                field_docs.append(a)
    assert len(field_docs) >= 1
    names = {a.name for a in field_docs}
    assert "x" in names or "y" in names


def test_field_documentation_attachment():
    src = '''//@version=6
//@type a struct
//@field name the name
//@field value the value
type Bag
    string name
    int value
'''
    result = parse_code(src)
    type_decls = [d for d in result.ast.items if d.__class__.__name__ == "TypeDeclaration"]
    bag = type_decls[0]
    field_names = {f.name for f in bag.fields}
    assert field_names == {"name", "value"}
    # Each field should have its own documentation entry
    docs_per_field = [len(f.documentation) for f in bag.fields]
    assert all(d >= 1 for d in docs_per_field), f"Some fields missing docs: {docs_per_field}"


def test_variable_documentation_attachment():
    src = '''//@version=6
indicator("T")
//@variable global state
var float count = 0
'''
    result = parse_code(src)
    var_decls = [d for d in result.ast.items if d.__class__.__name__ == "VarDeclaration"]
    assert len(var_decls) >= 1
    docs = [v.documentation for v in var_decls if v.documentation]
    assert len(docs) >= 1
    kinds = {a.kind.value for sublist in docs for a in sublist}
    assert "VARIABLE" in kinds
