import json
from pathlib import Path

from pine2ast import ParseOptions, parse_code

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "valid" / "layout_stage4"
SNAPSHOT_FIXTURES = [
    "ambiguous_continuations.pine",
    "comments_only_wrapped_expression.pine",
    "multiline_declaration_call.pine",
    "tuple_wrapped_targets.pine",
]


def layout_snapshot(src: str) -> list[dict[str, object]]:
    result = parse_code(src, ParseOptions(run_semantic=False, collect_tokens=True))
    assert result.ok, [diag.to_dict() for diag in result.diagnostics]
    assert result.tokens is not None
    interesting = {
        "NEWLINE",
        "INDENT",
        "DEDENT",
        "LPAREN",
        "RPAREN",
        "LBRACKET",
        "RBRACKET",
        "COMMA",
        "DOT",
        "EQ",
        "FAT_ARROW",
    }
    return [
        {"kind": token.kind.value, "line": token.span.start_line, "col": token.span.start_col}
        for token in result.tokens
        if token.kind.value in interesting
    ]


def test_v2_18_layout_token_snapshots_match_contract():
    actual = {
        fixture: layout_snapshot((FIXTURE_DIR / fixture).read_text())
        for fixture in SNAPSHOT_FIXTURES
    }
    expected = json.loads((FIXTURE_DIR / "layout_token_snapshots_v2_18.json").read_text())
    assert actual == expected
