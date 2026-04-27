from pathlib import Path

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import (
    CallExpr,
    IfStructure,
    MemberAccessExpr,
    TupleDeclaration,
    VarDeclaration,
)
from pine2ast.diagnostics import codes

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "valid" / "layout_stage4"


VALID_LAYOUT_FIXTURES = [
    "ambiguous_continuations.pine",
    "multiline_declaration_call.pine",
    "chained_member_calls.pine",
    "comments_only_wrapped_expression.pine",
    "multiline_strings_near_wrapping.pine",
    "switch_multiline_body.pine",
    "if_expression_assignment.pine",
    "tuple_wrapped_targets.pine",
]


def parse_without_semantics(src: str):
    return parse_code(src, ParseOptions(run_semantic=False))


def test_v2_18_real_pine_layout_fixtures_parse_cleanly():
    for fixture in VALID_LAYOUT_FIXTURES:
        result = parse_without_semantics((FIXTURE_DIR / fixture).read_text())
        assert result.ok, (fixture, [d.to_dict() for d in result.diagnostics])


def test_v2_18_ambiguous_continuation_shapes_are_preserved():
    chained = parse_without_semantics((FIXTURE_DIR / "chained_member_calls.pine").read_text())
    assert chained.ok, [d.to_dict() for d in chained.diagnostics]
    chained_decl = chained.ast.items[-1]
    assert isinstance(chained_decl, VarDeclaration)
    assert isinstance(chained_decl.initializer, CallExpr)
    assert isinstance(chained_decl.initializer.callee, MemberAccessExpr)
    assert chained_decl.initializer.callee.member == "set_width"

    if_result = parse_without_semantics((FIXTURE_DIR / "if_expression_assignment.pine").read_text())
    assert if_result.ok, [d.to_dict() for d in if_result.diagnostics]
    assert isinstance(if_result.ast.items[0], VarDeclaration)
    assert isinstance(if_result.ast.items[0].initializer, IfStructure)

    tuple_result = parse_without_semantics((FIXTURE_DIR / "tuple_wrapped_targets.pine").read_text())
    assert tuple_result.ok, [d.to_dict() for d in tuple_result.diagnostics]
    tuple_decl = tuple_result.ast.items[0]
    assert isinstance(tuple_decl, TupleDeclaration)
    assert [target.name for target in tuple_decl.targets] == ["basis", "upper", "lower"]


def test_v2_18_unclosed_call_recovers_at_next_statement():
    result = parse_without_semantics("""//@version=6
indicator("Recovery")
x = ta.sma(close, 20
y = open
""")
    assert result.ast is not None
    assert codes.SYNTAX_ERROR in {diag.code for diag in result.diagnostics}
    assert [getattr(item, "name", None) for item in result.ast.items] == ["x", "y"]


def test_v2_18_unclosed_history_ref_recovers_at_next_statement():
    result = parse_without_semantics("""//@version=6
indicator("Recovery")
x = close[1
y = open
""")
    assert result.ast is not None
    assert codes.SYNTAX_ERROR in {diag.code for diag in result.diagnostics}
    assert [getattr(item, "name", None) for item in result.ast.items] == ["x", "y"]


def test_v2_18_bad_block_indentation_does_not_eat_following_statement():
    result = parse_without_semantics("""//@version=6
indicator("Recovery")
if close > open
x = close
y = open
""")
    assert result.ast is not None
    assert codes.SYNTAX_ERROR in {diag.code for diag in result.diagnostics}
    assert [getattr(item, "name", None) for item in result.ast.items[1:]] == ["x", "y"]


def test_v2_18_unknown_token_reports_and_recovers():
    result = parse_without_semantics("""//@version=6
indicator("Recovery")
x = close @ open
y = open
""")
    assert result.ast is not None
    assert codes.UNKNOWN_TOKEN in {diag.code for diag in result.diagnostics}
    assert [getattr(item, "name", None) for item in result.ast.items if hasattr(item, "name")] == [
        "x",
        "y",
    ]


def test_v2_18_invalid_declaration_call_reports_without_schema_change():
    result = parse_without_semantics("""//@version=6
indicator("Recovery",
x = close
""")
    assert result.ast is not None
    assert result.ast.declaration is not None
    assert result.ast.declaration.script_type == "indicator"
    assert codes.SYNTAX_ERROR in {diag.code for diag in result.diagnostics}
