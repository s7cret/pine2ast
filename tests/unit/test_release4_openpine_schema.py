from __future__ import annotations

import json

from pine2ast.api import ParseOptions, parse_code
from pine2ast.cli import main as cli_main
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.openpine_contract import (
    SECTION_CONTRACTS,
    build_openpine_contract_payload,
    openpine_contract_schema,
    validate_openpine_contract_payload,
    validate_openpine_contract_payload_dict,
)

SOURCE = """//@version=6
indicator("Schema Smoke")
plot(close)
"""


def test_openpine_contract_schema_lists_public_sections() -> None:
    schema = openpine_contract_schema()

    assert schema["schema_id"] == "openpine.frontend.v2"
    assert schema["frontend_contract"] == "openpine.frontend.v2"
    assert schema["section_contracts"] == SECTION_CONTRACTS
    assert "content_hash" in schema["top_level_required"]


def test_openpine_contract_payload_validates_against_schema() -> None:
    result = parse_code(SOURCE, ParseOptions(version=6, source_name="schema_smoke.pine"))
    payload = build_openpine_contract_payload(result)

    assert payload["contract"] == "openpine.frontend.v2"
    assert validate_openpine_contract_payload(payload) == ()
    assert validate_openpine_contract_payload_dict(payload)["ok"] is True


def test_inspect_payload_source_path_is_optional_and_embeds_openpine_contract() -> None:
    result = parse_code(SOURCE, ParseOptions(version=6))
    payload = build_inspect_payload(result, include_openpine_contract=True)

    assert payload["source"]["path"] == "<memory>"
    assert payload["openpine_contract"]["source"]["path"] == "<memory>"
    assert validate_openpine_contract_payload(payload["openpine_contract"]) == ()


def test_cli_contract_schema_outputs_json(tmp_path) -> None:
    out = tmp_path / "schema.json"
    exit_code = cli_main(["contract-schema", "--json", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_id"] == "openpine.frontend.v2"


def test_cli_semantic_snapshot_parser_command_exists(tmp_path) -> None:
    source = tmp_path / "snapshot.pine"
    out = tmp_path / "snapshot.json"
    source.write_text(SOURCE, encoding="utf-8")

    exit_code = cli_main(["semantic-snapshot", str(source), "--json", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["contract"] == "pine2ast.semantic_snapshot.v1"
