from __future__ import annotations

import json
from pathlib import Path

from pine2ast.api import parse_code
from pine2ast.diagnostics.reports import diff_diagnostic_reports, summarize_diagnostics
from pine2ast.quality import quality_gate


def _codes(code: str) -> list[str]:
    return [d.code for d in parse_code(code).diagnostics]


def test_array_literal_generic_assignment_rejects_wrong_element_type():
    codes = _codes('''//@version=6
indicator("x")
array<float> values = array.from("bad")
''')
    assert "P2A1801" in codes


def test_array_push_validates_element_type_function_and_method_forms():
    function_codes = _codes('''//@version=6
indicator("x")
array<float> values = array.from(1.0)
array.push(values, "bad")
''')
    method_codes = _codes('''//@version=6
indicator("x")
array<float> values = array.from(1.0)
values.push("bad")
''')
    assert "P2A1805" in function_codes
    assert "P2A1805" in method_codes


def test_map_put_validates_key_and_value_types():
    codes = _codes('''//@version=6
indicator("x")
map<string,float> values = map.new<string,float>()
map.put(values, 1, "bad")
''')
    assert codes.count("P2A1805") == 2


def test_generic_collection_constructor_validates_initial_value():
    codes = _codes('''//@version=6
indicator("x")
array<float> values = array.new<float>(1, "bad")
''')
    assert "P2A1805" in codes


def test_diagnostic_report_diff_by_code():
    current = {"total": 3, "by_code": {"P2A1": 2, "P2A2": 1}}
    baseline = {"total": 1, "by_code": {"P2A1": 1}}
    diff = diff_diagnostic_reports(current, baseline)
    assert not diff.ok
    assert diff.added_by_code == {"P2A1": 1, "P2A2": 1}


def test_quality_gate_accepts_clean_fixture(tmp_path: Path):
    fixture = tmp_path / "ok.pine"
    fixture.write_text('''//@version=6
indicator("x")
plot(close)
''', encoding="utf-8")
    report = quality_gate(tmp_path)
    assert report.ok
    assert report.file_count == 1
    assert report.files[0].schema_ok


def test_quality_gate_cli_json(tmp_path: Path):
    fixture = tmp_path / "ok.pine"
    out = tmp_path / "quality.json"
    fixture.write_text('''//@version=6
indicator("x")
plot(close)
''', encoding="utf-8")
    from pine2ast.cli import main
    assert main(["quality-gate", str(tmp_path), "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["file_count"] == 1


def test_diagnostics_diff_cli(tmp_path: Path):
    cur = tmp_path / "cur.json"
    base = tmp_path / "base.json"
    cur.write_text(json.dumps({"summary": {"total": 1, "by_code": {"P2A1": 1}}}), encoding="utf-8")
    base.write_text(json.dumps({"summary": {"total": 1, "by_code": {"P2A1": 1}}}), encoding="utf-8")
    from pine2ast.cli import main
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert main(["diagnostics-diff", str(cur), str(base)]) == 0
    assert json.loads(buf.getvalue())["ok"] is True
