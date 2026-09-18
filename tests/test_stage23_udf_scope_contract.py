"""Stage 2.3 UDF scope restrictions and lexical binding contracts."""

import pytest

from pine2ast import parse_code
from pine2ast.diagnostics import codes


def script(body: str, version: int = 6) -> str:
    decl = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{decl}("stage23")\n{body}\n'


def test_v1_user_defined_functions_remain_unavailable():
    parsed = parse_code(script("f(x)=>x\nplot(f(close))", 1))
    assert not parsed.ok
    assert any(d.code == codes.VERSION_FEATURE_UNAVAILABLE for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
def test_udf_cannot_reassign_global_value_binding(version):
    parsed = parse_code(script("g=0\nf()=>\n    g:=g+1\n    g\nplot(f())", version))
    assert not parsed.ok
    assert any(d.code == codes.CALLABLE_REASSIGNMENT_FORBIDDEN for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
def test_udf_cannot_reassign_parameter_binding(version):
    parameter = "int x" if version >= 4 else "x"
    parsed = parse_code(script(f"f({parameter})=>\n    x+=1\n    x\nplot(f(1))", version))
    assert not parsed.ok
    assert any(d.code == codes.CALLABLE_REASSIGNMENT_FORBIDDEN for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [4, 5, 6])
def test_udf_local_shadow_can_be_reassigned_without_touching_global(version):
    parsed = parse_code(
        script(
            "int x=7\nf(int step)=>\n    int x=step\n    x+=1\n    x\nplot(f(2))\nplot(x)",
            version,
        )
    )
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]


def test_global_reference_object_field_mutation_is_not_binding_reassignment():
    parsed = parse_code(
        script("type C\n    int n=0\nvar C c=C.new()\nf()=>\n    c.n+=1\n    c.n\nplot(f())")
    )
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
@pytest.mark.parametrize(
    "bad",
    [
        "f()=>f()\nplot(f())",
        "f()=>g()\ng()=>f()\nplot(f())",
    ],
)
def test_recursive_udf_cycles_remain_rejected_by_resolved_identity(version, bad):
    parsed = parse_code(script(bad, version))
    assert not parsed.ok
    assert any(d.code == codes.RECURSIVE_CALL for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
def test_nested_function_definition_is_rejected_in_udf_scope(version):
    parsed = parse_code(script("outer()=>\n    inner()=>1\n    inner()\nplot(outer())", version))
    assert not parsed.ok
    assert any(d.code == codes.NESTED_FUNCTION for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
def test_single_expression_udf_rejects_global_only_plot(version):
    parsed = parse_code(script("f()=>plot(close)\nplot(close)", version))
    assert not parsed.ok
    assert any(d.code == codes.BUILTIN_FORBIDDEN_LOCAL for d in parsed.diagnostics)


@pytest.mark.parametrize(
    "call",
    [
        "alertcondition()",
        "barcolor()",
        "bgcolor()",
        "fill()",
        "hline()",
        "plot()",
        "plotarrow()",
        "plotbar()",
        "plotcandle()",
        "plotchar()",
        "plotshape()",
    ],
)
def test_v6_single_expression_udf_rejects_every_catalog_global_only_callable(call):
    parsed = parse_code(script(f"f()=>{call}\nplot(close)", 6))
    assert not parsed.ok
    assert any(d.code == codes.BUILTIN_FORBIDDEN_LOCAL for d in parsed.diagnostics), (
        call,
        [d.to_dict() for d in parsed.diagnostics],
    )


def test_v6_single_expression_user_method_rejects_global_only_builtin():
    parsed = parse_code(script("method bad(int self)=>plot(close)\na=1\nplot(a.bad())", 6))
    assert not parsed.ok
    assert any(d.code == codes.BUILTIN_FORBIDDEN_LOCAL for d in parsed.diagnostics)


def test_v6_single_expression_user_method_rejects_script_declaration():
    parsed = parse_code(script('method bad(int self)=>indicator("inner")\na=1\nplot(a.bad())', 6))
    assert not parsed.ok
    assert any(d.code == codes.DECLARATION_NOT_GLOBAL for d in parsed.diagnostics)


def test_v6_udf_keeps_allowed_drawing_and_ta_calls_available():
    parsed = parse_code(
        script(
            "f(float x)=>\n"
            '    label.new(bar_index,x,"ok")\n'
            "    pts=array.new<chart.point>()\n"
            "    polyline.new(pts)\n"
            "    ta.sma(x,2)\n"
            "plot(f(close))",
            6,
        )
    )
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]


@pytest.mark.parametrize(
    "version,call",
    [
        (2, 'study("inner")'),
        (2, 'strategy("inner")'),
        (3, 'study("inner")'),
        (3, 'strategy("inner")'),
        (4, 'study("inner")'),
        (4, 'strategy("inner")'),
        (5, 'indicator("inner")'),
        (5, 'strategy("inner")'),
        (5, 'library("inner")'),
        (6, 'indicator("inner")'),
        (6, 'strategy("inner")'),
        (6, 'library("inner")'),
    ],
)
def test_single_expression_udf_rejects_script_declarations(version, call):
    parsed = parse_code(script(f"f()=>{call}\nplot(close)", version))
    assert not parsed.ok
    assert any(d.code == codes.DECLARATION_NOT_GLOBAL for d in parsed.diagnostics), (
        version,
        call,
        [d.to_dict() for d in parsed.diagnostics],
    )
