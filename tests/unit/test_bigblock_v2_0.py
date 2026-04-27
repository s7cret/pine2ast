import json
from pathlib import Path

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.extractors import (
    extract_alertconditions,
    extract_dependencies,
    extract_drawing_calls,
    extract_inputs,
)
from pine2ast.semantic.type_infer import infer_type


def _errors(src: str):
    res = parse_code(src, ParseOptions(source_name="v20.pine"))
    return res, [d.code for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]


def test_udt_member_reassignment_checks_field_type_and_unknown_field():
    src = """//@version=6
indicator("UDT field checks")
type Pivot
    int x
    float y
p = Pivot.new(bar_index, close)
p.y := high
p.x := "bad"
p.missing := close
plot(p.y)
"""
    res, errors = _errors(src)
    assert codes.TYPE_MISMATCH in errors
    assert codes.UNKNOWN_FIELD in errors
    assert codes.REASSIGN_UNDECLARED not in errors
    assert res.ast is not None


def test_udt_member_access_unknown_field_is_diagnostic_but_known_field_infers_type():
    src = """//@version=6
indicator("UDT field read")
type Pivot
    int x
    float y
p = Pivot.new(bar_index, close)
y = p.y
z = p.bad
plot(y)
"""
    res, errors = _errors(src)
    assert codes.UNKNOWN_FIELD in errors
    y_decl = next(item for item in res.ast.items if getattr(item, "name", None) == "y")
    assert infer_type(y_decl.initializer, res.semantic_model.symbols) == "float"


def test_extract_dependencies_alerts_drawings_and_inputs():
    src = """//@version=6
indicator("Inspect", overlay = true)
import user/Lib/1 as lib
len = input.int(14, "Length")
ma = ta.sma(close, len)
alertcondition(ma > close, "Cross", "cross")
label.new(bar_index, high, str.tostring(ma))
ext = lib.score(ma)
plot(ma)
"""
    res, errors = _errors(src)
    assert codes.UNDECLARED_VARIABLE not in errors
    assert extract_inputs(res.ast, res.semantic_model)[0].name == "len"
    assert extract_alertconditions(res.ast)[0].name == "alertcondition"
    assert extract_drawing_calls(res.ast)[0].name == "label.new"
    deps = extract_dependencies(res.ast, res.semantic_model)
    assert deps.imports == ["user/Lib/1"]
    assert "ta" in deps.namespaces
    assert "ta.sma" in deps.builtin_calls
    assert "lib.score" in deps.external_calls


def test_cli_inspect_outputs_optimizer_payload(tmp_path: Path):
    src = tmp_path / "inspect.pine"
    out = tmp_path / "inspect.json"
    src.write_text(
        """//@version=6
strategy("Inspect strategy")
qty = input.float(1.0, "Qty")
strategy.entry("L", strategy.long, qty = qty)
""",
        encoding="utf-8",
    )
    from pine2ast.cli import main

    assert main(["inspect", str(src), "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["inputs"][0]["name"] == "qty"
    assert payload["strategy_calls"][0]["name"] == "strategy.entry"


def test_real_world_corpus_reached_v20_seed_size():
    from pine2ast.corpus import validate_corpus

    result = validate_corpus(
        Path(__file__).absolute().parents[1]
        / "fixtures"
        / "real_world"
        / "151_v21_schema_semantic_seed.pine"
    )
    assert result["file_count"] == 1
    assert result["ok_count"] == result["file_count"]
    assert result["error_count"] == 0
