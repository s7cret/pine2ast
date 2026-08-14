from __future__ import annotations

import json
import subprocess
import sys

from pine2ast import ParseOptions, parse_code
from pine2ast.semantic.snapshot import SEMANTIC_SNAPSHOT_CONTRACT, build_semantic_snapshot_payload


def test_semantic_snapshot_payload_is_json_safe_and_versioned(tmp_path):
    source = """//@version=6
indicator("Snapshot", overlay=true)
float basis = ta.sma(close, 10)
plot(basis)
"""
    result = parse_code(source, ParseOptions(version=6, source_name="snapshot.pine"))
    payload = build_semantic_snapshot_payload(result, source_path="snapshot.pine")

    assert payload["contract"] == SEMANTIC_SNAPSHOT_CONTRACT
    assert payload["producer"]["version"] == "4.0.2"
    assert payload["profile"]["version"] == 6
    assert payload["counts"]["symbols"] > 0
    assert payload["counts"]["node_facts"] > 0
    assert any(row["name"] == "basis" for row in payload["symbols"])
    assert [row["name"] for row in payload["passes"]][0] == "declaration_index"
    json.dumps(payload)


def test_inspect_can_embed_semantic_snapshot():
    source = '//@version=6\nindicator("x")\nplot(close)\n'
    result = parse_code(source, ParseOptions(version=6))
    from pine2ast.inspect_contract import build_inspect_payload

    payload = build_inspect_payload(
        result,
        source_path="x.pine",
        include_semantic_snapshot=True,
    )
    assert payload["semantic_snapshot"]["contract"] == SEMANTIC_SNAPSHOT_CONTRACT


def test_cli_semantic_snapshot_command(tmp_path):
    pine = tmp_path / "snapshot.pine"
    pine.write_text('//@version=6\nindicator("x")\nplot(close)\n', encoding="utf-8")
    output = tmp_path / "snapshot.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pine2ast.cli",
            "semantic-snapshot",
            str(pine),
            "--json",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["contract"] == SEMANTIC_SNAPSHOT_CONTRACT
    assert payload["counts"]["symbols"] > 0
