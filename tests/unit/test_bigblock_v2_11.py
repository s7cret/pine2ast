from pine2ast import parse_code
from pine2ast.semantic.reports import semantic_report


def non_na_paths(src: str):
    result = parse_code(src)
    assert result.ast is not None
    assert result.semantic_model is not None
    return result.semantic_model.non_na_paths, result


def test_and_guard_narrows_symbol_in_then_scope():
    paths, result = non_na_paths("""//@version=6
indicator("and narrowing")
float x = na
if not na(x) and x > 0
    y = x + 1
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert any(values == {"x"} for values in paths.values())


def test_member_path_narrowing_is_reported_without_symbol_leak():
    paths, result = non_na_paths("""//@version=6
indicator("member narrowing")
type Pivot
    float y
p = Pivot.new(1.0)
if not na(p.y)
    y = p.y + 1
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert any("p.y" in values for values in paths.values())
    assert not any("p.y" in scope.non_na_symbols for scope in result.semantic_model.scopes)


def test_na_condition_narrows_else_branch_only():
    paths, result = non_na_paths("""//@version=6
indicator("else narrowing")
float x = na
if na(x)
    a = 0
else
    b = x + 1
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    narrowed_scopes = [scope_id for scope_id, values in paths.items() if "x" in values]
    assert len(narrowed_scopes) == 1
    narrowed_scope = next(
        scope for scope in result.semantic_model.scopes if scope.id == narrowed_scopes[0]
    )
    assert "x" in narrowed_scope.non_na_symbols


def test_semantic_report_includes_narrowing_metadata():
    result = parse_code("""//@version=6
indicator("report narrowing")
float x = na
if not na(x)
    y = x + 1
plot(close)
""")
    report = semantic_report(result.semantic_model).to_dict()
    assert report["schema_version"] == 2
    assert report["narrowing_count"] >= 1
    assert any("x" in scope["non_na_paths"] for scope in report["scopes"])
