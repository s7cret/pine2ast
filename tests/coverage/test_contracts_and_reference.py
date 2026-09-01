from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from pine2ast import parse_code
from pine2ast.ast.serialize import ast_to_dict
from pine2ast.contracts import validation as contracts
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.reference_catalog import official_reference as official
from pine2ast.reference_catalog.export_markdown import catalog_markdown, export_catalog_markdown
from pine2ast.reference_catalog.loader import load_catalog, load_entries, load_parity_matrix
from pine2ast.reference_catalog.schema import CatalogEntry, REQUIRED_ENTRY_FIELDS, STATUS_FIELDS
from pine2ast.reference_catalog.validate import (
    ReferenceCatalogError,
    official_matrix_coverage_payload,
    validate_catalog,
    validate_catalog_payload,
    validate_matrix,
    validate_matrix_payload,
)

VALID_SOURCE = """//@version=6
indicator("contracts")
length = input.int(14, "Length", minval=1, maxval=100, step=1)
value = request.security("AAPL", "D", close)
plot(value)
alertcondition(value > 0, "positive")
"""


def _valid_entry(item_id: str = "plot") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": item_id,
        "kind": "function",
        "namespace": None,
        "name": item_id,
        "pine_version": 6,
        "priority": "P0",
        "signatures": [{"parameters": []}],
        "stateful": False,
        "requires_history": False,
        "side_effect": False,
        "method_receiver": None,
        "function_equivalent": None,
        "runtime_owner": None,
        "known_edge_cases": [],
    }
    for field in STATUS_FIELDS:
        entry[field] = "DONE_VERIFIED"
    assert REQUIRED_ENTRY_FIELDS <= entry.keys()
    return entry


def _official_index(*names: str) -> dict[str, Any]:
    return {
        "schema_version": "pine.official_pine_reference_index.v1",
        "pine_version": 6,
        "categories": {
            "functions": list(names),
            "variables": [],
            "methods": [],
            "constants": [],
            "types": [],
        },
    }


def _matrix_item(item_id: str = "plot") -> dict[str, Any]:
    item = {
        "id": item_id,
        "official_category": "functions",
        "priority": "P0",
        "runtime_owner": None,
    }
    for field in STATUS_FIELDS:
        item[field] = "DONE_VERIFIED"
    return item


def test_generated_public_contracts_validate_and_round_trip(tmp_path: Path) -> None:
    result = parse_code(VALID_SOURCE)
    assert result.ast is not None
    payload = build_inspect_payload(
        result,
        source_path="contracts.pine",
        include_openpine_contract=True,
        include_semantic_snapshot=True,
    )
    report = contracts.validate_contract_payload(payload)
    assert report.ok, report.to_dict()
    assert report.to_dict()["issue_count"] == 0

    openpine = payload["openpine_contract"]
    snapshot = payload["semantic_snapshot"]
    assert isinstance(openpine, dict)
    assert isinstance(snapshot, dict)
    assert contracts.validate_contract_payload(openpine).ok
    assert contracts.validate_contract_payload(snapshot).ok

    ast_payload = ast_to_dict(result.ast)
    ast_report = contracts.validate_contract_payload(
        ast_payload, expected_contract=contracts.AST_CONTRACT
    )
    assert ast_report.ok, ast_report.to_dict()

    source_path = tmp_path / "contracts.pine"
    source_path.write_text(VALID_SOURCE, encoding="utf-8")
    checked = contracts.contract_check_file_payload(source_path)
    assert checked["ok"] and checked["parse_ok"] and checked["contract_ok"]
    decoded = json.loads(contracts.contract_check_json(source_path, indent=0))
    assert decoded["contract_report"]["contract"] == contracts.INSPECT_CONTRACT

    output_path = tmp_path / "contract-check.json"
    assert contracts.main([str(source_path), "--json", str(output_path)]) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["ok"] is True
    assert contracts.main([str(source_path), "--no-openpine-contract"]) == 0


def test_contract_validator_reports_structural_errors() -> None:
    unknown = contracts.validate_contract_payload({})
    assert not unknown.ok
    assert unknown.issues[0].code == "unknown_contract"

    malformed: dict[str, Any] = {
        "contract": contracts.INSPECT_CONTRACT,
        "schema_version": True,
        "producer": {"name": 1},
        "source": "bad",
        "script": [],
        "ok": 1,
        "diagnostics": ["bad", {"code": 1}],
        "unsupported_features": {},
        "inputs": None,
        "strategy_calls": "bad",
        "request_calls": {},
        "plots": {},
        "alerts": {},
        "drawings": {},
        "dependencies": [],
        "openpine_contract": [],
        "semantic_snapshot": [],
    }
    report = contracts.validate_contract_payload(malformed)
    codes = {issue.code for issue in report.issues}
    assert {"wrong_type", "missing_key"} <= codes
    assert report.to_dict()["issue_count"] == len(report.issues)

    wrong_literal = {
        "kind": "Other",
        "schema_version": "2.0",
        "language": "pine",
        "version_context": {},
        "producer_metadata": {},
    }
    ast_report = contracts.validate_contract_payload(
        wrong_literal, expected_contract=contracts.AST_CONTRACT
    )
    assert not ast_report.ok
    assert any(issue.code == "wrong_literal" for issue in ast_report.issues)

    issue = contracts.ContractIssue("$.x", "code", "message")
    assert issue.to_dict() == {"path": "$.x", "code": "code", "message": "message"}


def test_reference_catalog_loaders_markdown_and_entry_conversion(tmp_path: Path) -> None:
    catalog = load_catalog()
    matrix = load_parity_matrix()
    entries = load_entries()
    assert catalog["pine_version"] == 6
    assert matrix["pine_version"] == 6
    assert entries and isinstance(entries[0], CatalogEntry)

    custom = _valid_entry("custom.fn")
    converted = CatalogEntry.from_dict(custom)
    assert converted.id == "custom.fn"
    assert converted.namespace is None
    assert converted.runtime_owner is None

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "pine.pine_reference_catalog.v1",
                "pine_version": 6,
                "entries": [custom],
            }
        ),
        encoding="utf-8",
    )
    assert load_entries(catalog_path)[0] == converted

    broken_path = tmp_path / "broken.json"
    broken_path.write_text('{"entries": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="array"):
        load_entries(broken_path)

    markdown = catalog_markdown()
    assert "# Pine v6 Reference Catalog" in markdown
    output = export_catalog_markdown(tmp_path / "nested" / "catalog.md")
    assert output.read_text(encoding="utf-8") == markdown


def test_reference_validation_accepts_valid_payloads_and_rejects_mutants() -> None:
    entry = _valid_entry()
    catalog = {
        "schema_version": "pine.pine_reference_catalog.v1",
        "pine_version": 6,
        "entries": [entry],
    }
    matrix = {
        "schema_version": "pine.parity_matrix.v1",
        "pine_version": 6,
        "items": [_matrix_item()],
    }
    index = _official_index("plot")
    validate_catalog_payload(catalog)
    validate_matrix_payload(matrix, catalog, index)

    coverage = official_matrix_coverage_payload(matrix, index)
    assert coverage["summary"]["coverage_ratio"] == 1.0
    matrix_with_extra = deepcopy(matrix)
    matrix_with_extra["items"].append(_matrix_item("unknown"))
    coverage = official_matrix_coverage_payload(matrix_with_extra, index)
    assert coverage["extra_matrix_by_category"]["functions"] == ["unknown"]

    bad_catalogs = [
        {},
        {"schema_version": "bad", "pine_version": 5, "entries": []},
        {
            "schema_version": "pine.pine_reference_catalog.v1",
            "pine_version": 6,
            "entries": ["bad", {}],
        },
    ]
    for payload in bad_catalogs:
        with pytest.raises(ReferenceCatalogError):
            validate_catalog_payload(payload)

    mutant = deepcopy(catalog)
    mutant["entries"].append(deepcopy(entry))
    mutant["entries"][0]["kind"] = "bad"
    mutant["entries"][0]["priority"] = "PX"
    mutant["entries"][0]["pine_version"] = 5
    mutant["entries"][0]["stateful"] = "false"
    mutant["entries"][0]["signatures"] = {}
    mutant["entries"][0]["known_edge_cases"] = {}
    mutant["entries"][0][STATUS_FIELDS[0]] = "bad"
    with pytest.raises(ReferenceCatalogError) as exc:
        validate_catalog_payload(mutant)
    message = str(exc.value)
    assert "duplicate catalog ids" in message
    assert "invalid status" in message

    bad_matrices = [
        {},
        {"schema_version": "bad", "pine_version": 5, "items": []},
        {
            "schema_version": "pine.parity_matrix.v1",
            "pine_version": 6,
            "items": ["bad", {}],
        },
    ]
    for payload in bad_matrices:
        with pytest.raises(ReferenceCatalogError):
            validate_matrix_payload(payload, catalog, index)

    wrong = deepcopy(matrix)
    wrong["items"][0]["official_category"] = "variables"
    wrong["items"][0]["priority"] = "PX"
    wrong["items"][0]["runtime_owner"] = 3
    wrong["items"][0][STATUS_FIELDS[0]] = "bad"
    with pytest.raises(ReferenceCatalogError) as exc:
        validate_matrix_payload(wrong, catalog, index)
    assert "differs from catalog" in str(exc.value) or "invalid" in str(exc.value)

    with pytest.raises(ReferenceCatalogError, match="schema mismatch"):
        official_matrix_coverage_payload(matrix, {"schema_version": "bad"})


def test_installed_reference_catalog_validation_entry_points() -> None:
    validate_catalog()
    # The checked-in parity matrix and official index are intended to agree.
    validate_matrix()


def test_official_reference_parser_and_fetch_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = [
        "https://static.tradingview.com/static/bundles/runtime.hash.js",
        "https://static.tradingview.com/static/bundles/reference.hash.js",
    ]
    html = " ".join([urls[0], urls[0].replace("&", "&amp;"), urls[1]])
    assert official._script_urls(html) == urls
    assert official._select_script(urls, "runtime.") == urls[0]
    with pytest.raises(official.OfficialReferenceError, match="bundle URLs"):
        official._script_urls("none")
    with pytest.raises(official.OfficialReferenceError, match="could not find"):
        official._select_script(urls, "missing")

    runtime = 'if(42===e)return"__LANG__."+e+".abc123.js";43:"beef"'
    assert official._chunk_url(runtime, 42).endswith("en.42.abc123.js")
    assert official._chunk_url(runtime, 43).endswith("43.beef.js")
    with pytest.raises(official.OfficialReferenceError, match="resolve"):
        official._chunk_url(runtime, 44)

    loader = "case x.PineLanguage.V6:Promise.all([n.e(1),n.e(42)]);break"
    assert official._reference_payload_chunk_id(loader, 6) == 42
    with pytest.raises(official.OfficialReferenceError, match="discover"):
        official._reference_payload_chunk_id("no cases", 6)

    array = '[{name:"one"},{name:"two",nested:{x:1}},{originalName:"method"}]'
    assert official._balanced_slice("x=" + array, 2, "[", "]") == array
    assert len(official._top_level_objects(array)) == 3
    assert official._first_string_prop('{name:"a\\"b"}', "name") == 'a"b'
    assert official._first_string_prop("{}", "name") is None
    with pytest.raises(official.OfficialReferenceError, match="unterminated"):
        official._balanced_slice("[", 0, "[", "]")
    with pytest.raises(official.OfficialReferenceError, match="could not find"):
        official._array_source("none", "functions")

    bundle = "".join(
        f'{key}:[{{name:"{key}.one"}},{{originalName:"{key}.method"}}],'
        for key in (
            "functions",
            "variables",
            "methods",
            "constants",
            "types",
            "keywords",
            "operators",
            "annotations",
        )
    )
    categories = official._extract_reference_categories(bundle)
    assert categories["functions"] == ["functions.one"]
    assert categories["methods"] == ["methods.method", "methods.one"]

    responses = {
        "https://www.tradingview.com/pine-script-reference/v6/": " ".join(urls),
        urls[0]: runtime,
        urls[1]: loader + " getReference PineLanguage.V6",
        "https://static.tradingview.com/static/bundles/en.42.abc123.js": bundle,
    }
    monkeypatch.setattr(official, "_fetch_text", lambda url, timeout: responses[url])
    index = official.fetch_official_reference_index(6, timeout=1)
    payload = index.to_dict()
    assert payload["pine_version"] == 6
    assert payload["counts"]["functions"] == 1
    assert index.bundle_url.endswith("en.42.abc123.js")
    with pytest.raises(official.OfficialReferenceError, match="only Pine"):
        official.fetch_official_reference_index(4)


def test_official_reference_diff_load_and_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = official.OfficialReferenceIndex(
        pine_version=6,
        source_url="https://www.tradingview.com/pine-script-reference/v6/",
        bundle_url="https://static.tradingview.com/static/bundles/reference.js",
        categories={
            "functions": ["plot", "missing.fn"],
            "variables": ["close"],
            "methods": [],
            "constants": [],
            "types": [],
            "operators": [],
            "keywords": [],
            "annotations": [],
        },
    )
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index.to_dict()), encoding="utf-8")
    loaded = official.load_official_reference_index(str(index_path))
    assert loaded.pine_version == index.pine_version
    assert loaded.source_url == index.source_url
    assert loaded.bundle_url == index.bundle_url
    assert loaded.categories["functions"] == ["missing.fn", "plot"]

    local = {
        "functions": {"plot": {"signatures": [{"parameters": []}]}},
        "variables": {"close": {}},
        "methods": {},
        "constants": {},
        "types": {},
        "operators": {},
        "keywords": {},
        "annotations": {},
    }
    monkeypatch.setattr(official, "load_catalog_view", lambda **kwargs: local)
    diff = official.official_reference_diff_payload(index)
    assert diff["summary"]["missing_official_count"] == 1
    assert diff["missing_by_category"]["functions"] == ["missing.fn"]
    assert diff["signature_coverage"]["summary"]["machine_signature_count"] == 1

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "schema_version": "pine.official_pine_reference_gap_baseline.v1",
                "pine_version": 6,
                "max_missing_official_count": 1,
                "min_coverage_ratio": 0.6,
                "missing_by_category": {"functions": ["missing.fn"]},
            }
        ),
        encoding="utf-8",
    )
    gate = official.official_reference_gate_payload(index, str(baseline_path))
    assert gate["status"] == "pass"

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["max_missing_official_count"] = 0
    baseline["min_coverage_ratio"] = 1.0
    baseline["missing_by_category"] = {}
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    failed = official.official_reference_gate_payload(index, str(baseline_path))
    assert failed["status"] == "fail"
    assert failed["failures"]

    baseline["schema_version"] = "bad"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(official.OfficialReferenceError, match="schema mismatch"):
        official.official_reference_gate_payload(index, str(baseline_path))

    bad_index = index.to_dict()
    bad_index["schema_version"] = "bad"
    index_path.write_text(json.dumps(bad_index), encoding="utf-8")
    with pytest.raises(official.OfficialReferenceError, match="schema mismatch"):
        official.load_official_reference_index(str(index_path))
