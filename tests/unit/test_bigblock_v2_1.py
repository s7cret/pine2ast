from pathlib import Path
import json

from pine2ast import parse_code, validate_ast_schema
from pine2ast.diagnostics import codes
from pine2ast.diagnostics.reports import summarize_diagnostics
from pine2ast.cli import main


def diag_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics]


def test_ast_schema_validator_reports_stable_contract():
    src = """//@version=6
indicator("schema")
plot(close)
"""
    result = parse_code(src)
    report = validate_ast_schema(result.ast)
    assert report.ok is True
    assert report.schema_version == "1.0"
    assert report.language == "pine"
    assert report.language_version == 6
    assert report.node_count >= 5
    assert report.kind_counts["Program"] == 1


def test_diagnostic_report_groups_codes_and_severity():
    src = """//@version=6
indicator("diag")
if close
    plot(close)
"""
    result = parse_code(src)
    summary = summarize_diagnostics(result.diagnostics).to_dict()
    assert summary["ok"] is False
    assert summary["by_code"][codes.NON_BOOL_CONDITION] >= 1
    assert summary["by_code"][codes.BUILTIN_FORBIDDEN_LOCAL] >= 1
    assert summary["by_severity"]["ERROR"] >= 2


def test_explicit_const_and_simple_qualifiers_reject_series_initializer():
    src = """//@version=6
indicator("qualifiers")
const float x = close
simple float y = close
"""
    got = diag_codes(src)
    assert got.count(codes.QUALIFIER_MISMATCH) >= 2


def test_explicit_const_accepts_literal_initializer():
    src = """//@version=6
indicator("const ok")
const float x = 1.0
plot(close)
"""
    assert codes.QUALIFIER_MISMATCH not in diag_codes(src)


def test_binary_operator_type_validation_catches_bad_operands():
    src = """//@version=6
indicator("bin")
x = "a" - "b"
y = true and 1
z = color.red + 1
"""
    got = diag_codes(src)
    assert got.count(codes.TYPE_MISMATCH) >= 3


def test_binary_operator_type_validation_allows_numeric_and_string_concat():
    src = """//@version=6
indicator("bin ok")
x = 1 + 2.5
y = "a" + "b"
plot(close)
"""
    assert codes.TYPE_MISMATCH not in diag_codes(src)


def test_cli_schema_check_and_diagnostics_report(tmp_path: Path):
    src = tmp_path / "s.pine"
    schema_json = tmp_path / "schema.json"
    diag_json = tmp_path / "diag.json"
    src.write_text(
        """//@version=6
indicator("cli")
plot(close)
""",
        encoding="utf-8",
    )
    assert main(["schema-check", str(src), "--json", str(schema_json)]) == 0
    assert main(["diagnostics-report", str(src), "--json", str(diag_json)]) == 0
    schema_payload = json.loads(schema_json.read_text(encoding="utf-8"))
    diag_payload = json.loads(diag_json.read_text(encoding="utf-8"))
    assert schema_payload["schema"]["ok"] is True
    assert diag_payload["summary"]["ok"] is True
