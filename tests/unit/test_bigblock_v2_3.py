import json
from pathlib import Path

from pine2ast import ParseOptions, parse_code
from pine2ast.cli import main
from pine2ast.diagnostics import codes, diagnostics_to_sarif
from pine2ast.semantic.reports import semantic_report


def diag_codes(src: str):
    return [d.code for d in parse_code(src, ParseOptions(source_name="v23.pine")).diagnostics]


def test_ternary_branch_type_mismatch_is_reported():
    src = '''//@version=6
indicator("branch")
x = close > open ? close : "bad"
plot(close)
'''
    assert codes.BRANCH_TYPE_MISMATCH in diag_codes(src)


def test_ternary_branch_numeric_compatibility_is_allowed():
    src = '''//@version=6
indicator("branch ok")
x = close > open ? 1 : 2.5
plot(close)
'''
    assert codes.BRANCH_TYPE_MISMATCH not in diag_codes(src)


def test_sarif_converter_uses_diagnostic_locations():
    src = '''//@version=6
indicator("sarif")
if close
    plot(close)
'''
    result = parse_code(src, ParseOptions(source_name="sarif.pine"))
    sarif = diagnostics_to_sarif(result.diagnostics, source_name="sarif.pine", tool_version="0.2.3")
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["semanticVersion"] == "0.2.3"
    assert sarif["runs"][0]["results"]
    first = sarif["runs"][0]["results"][0]
    assert first["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "sarif.pine"


def test_cli_sarif_and_semantic_report(tmp_path: Path):
    src = tmp_path / "s.pine"
    sarif_path = tmp_path / "out.sarif"
    semantic_path = tmp_path / "semantic.json"
    src.write_text('''//@version=6
indicator("reports")
len = input.int(14, "Length")
ma = ta.sma(close, len)
plot(ma)
''', encoding="utf-8")
    assert main(["sarif", str(src), "--json", str(sarif_path)]) == 0
    assert main(["semantic-report", str(src), "--json", str(semantic_path)]) == 0
    sarif = json.loads(sarif_path.read_text(encoding="utf-8"))
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "pine2ast"
    assert semantic["semantic"]["symbol_count"] >= 3
    assert "VARIABLE" in semantic["semantic"]["by_kind"]


def test_semantic_report_groups_user_symbols_without_builtins():
    res = parse_code('''//@version=6
indicator("semantic")
f(float x) => x + 1
v = f(close)
plot(v)
''')
    report = semantic_report(res.semantic_model).to_dict()
    assert report["by_kind"]["FUNCTION"] >= 1
    assert report["by_kind"]["VARIABLE"] >= 1
    assert all(row["kind"] != "BUILTIN" for row in report["symbols"])
