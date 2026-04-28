from pathlib import Path

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import (
    Block,
    CallExpr,
    IfStructure,
    MemberAccessExpr,
    SwitchStructure,
    TupleDeclaration,
    VarDeclaration,
)

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "valid" / "layout_stage4"


def test_stage4_layout_parser_edge_fixtures_parse_without_syntax_errors():
    fixtures = [
        "ambiguous_continuations.pine",
        "multiline_declaration_call.pine",
        "chained_member_calls.pine",
        "comments_only_wrapped_expression.pine",
        "multiline_strings_near_wrapping.pine",
        "switch_multiline_body.pine",
        "if_expression_assignment.pine",
        "tuple_wrapped_targets.pine",
    ]
    for fixture in fixtures:
        src = (FIXTURE_DIR / fixture).read_text()
        result = parse_code(src, ParseOptions(run_semantic=False))
        assert result.ok, (fixture, [d.to_dict() for d in result.diagnostics])


def test_stage4_multiline_declaration_call_is_script_declaration():
    result = parse_code(
        (FIXTURE_DIR / "multiline_declaration_call.pine").read_text(),
        ParseOptions(run_semantic=False),
    )
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert result.ast.declaration is not None
    assert result.ast.declaration.script_type == "indicator"
    assert isinstance(result.ast.declaration.call, CallExpr)


def test_stage4_chained_member_calls_stay_in_one_initializer():
    result = parse_code(
        (FIXTURE_DIR / "chained_member_calls.pine").read_text(), ParseOptions(run_semantic=False)
    )
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    item = result.ast.items[-1]
    assert isinstance(item, VarDeclaration)
    assert isinstance(item.initializer, CallExpr)
    assert isinstance(item.initializer.callee, MemberAccessExpr)
    assert item.initializer.callee.member == "set_width"


def test_stage4_switch_if_and_tuple_shapes_survive_wrapping():
    switch_result = parse_code(
        (FIXTURE_DIR / "switch_multiline_body.pine").read_text(), ParseOptions(run_semantic=False)
    )
    if_result = parse_code(
        (FIXTURE_DIR / "if_expression_assignment.pine").read_text(),
        ParseOptions(run_semantic=False),
    )
    tuple_result = parse_code(
        (FIXTURE_DIR / "tuple_wrapped_targets.pine").read_text(), ParseOptions(run_semantic=False)
    )
    assert switch_result.ok, [d.to_dict() for d in switch_result.diagnostics]
    assert if_result.ok, [d.to_dict() for d in if_result.diagnostics]
    assert tuple_result.ok, [d.to_dict() for d in tuple_result.diagnostics]

    switch_decl = switch_result.ast.items[1]
    assert isinstance(switch_decl, VarDeclaration)
    assert isinstance(switch_decl.initializer, SwitchStructure)
    assert all(isinstance(case.body, Block) for case in switch_decl.initializer.cases)

    if_decl = if_result.ast.items[0]
    assert isinstance(if_decl, VarDeclaration)
    assert isinstance(if_decl.initializer, IfStructure)

    tuple_decl = tuple_result.ast.items[0]
    assert isinstance(tuple_decl, TupleDeclaration)
    assert [target.name for target in tuple_decl.targets] == ["basis", "upper", "lower"]
