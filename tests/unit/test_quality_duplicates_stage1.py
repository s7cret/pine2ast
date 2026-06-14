from __future__ import annotations

import json
from pathlib import Path

from pine2ast.quality import duplicate_function_report, duplicates_json, main


def test_duplicate_function_report_detects_exact_large_duplicates(tmp_path: Path) -> None:
    source = """
def a(x):
    y = x + 1
    z = y + 2
    q = z + 3
    r = q + 4
    return r

def b(x):
    y = x + 1
    z = y + 2
    q = z + 3
    r = q + 4
    return r
"""
    path = tmp_path / "dups.py"
    path.write_text(source, encoding="utf-8")

    payload = duplicate_function_report(path)

    assert payload["duplicate_group_count"] == 1
    assert {row["name"] for row in payload["duplicates"][0]} == {"a", "b"}
    assert json.loads(duplicates_json(path))["duplicate_group_count"] == 1


def test_quality_duplicates_cli_writes_json(tmp_path: Path) -> None:
    source = "def tiny():\n    return 1\n"
    path = tmp_path / "single.py"
    out = tmp_path / "out.json"
    path.write_text(source, encoding="utf-8")

    assert main(["duplicates", str(path), "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["duplicate_group_count"] == 0
