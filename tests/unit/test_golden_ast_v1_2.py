import json
from pathlib import Path

from pine2ast import ParseOptions, ast_to_dict, parse_code
from pine2ast.testing.ast_compare import strip_spans


def test_basic_indicator_golden_ast_ignore_spans():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "valid" / "basic_indicator.pine"
    golden = Path(__file__).resolve().parents[1] / "fixtures" / "golden_ast" / "basic_indicator.ast.json"
    result = parse_code(fixture.read_text(encoding="utf-8"), ParseOptions(run_semantic=False))
    assert result.ast is not None
    assert strip_spans(ast_to_dict(result.ast)) == strip_spans(json.loads(golden.read_text(encoding="utf-8")))
