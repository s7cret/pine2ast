from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "optimizer_contract_v2_20"
FIXTURES = sorted(FIXTURE_DIR.glob("*.pine"))
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "contract",
    "producer",
    "tool",
    "source",
    "script",
    "ok",
    "unsupported_features",
    "diagnostics",
    "inputs",
    "strategy_calls",
    "request_calls",
    "plots",
    "alerts",
    "drawings",
    "dependencies",
}


def _inspect(path: Path) -> dict[str, object]:
    rel = path.relative_to(ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "pine2ast", "inspect", str(rel)],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return json.loads(completed.stdout)


def test_optimizer_contract_snapshots_v2_20() -> None:
    assert FIXTURES
    for fixture in FIXTURES:
        actual = _inspect(fixture)
        expected = json.loads(fixture.with_suffix(".inspect.json").read_text(encoding="utf-8"))
        assert actual == expected, fixture.name


def test_optimizer_contract_required_fields_v2_20() -> None:
    for fixture in FIXTURES:
        payload = _inspect(fixture)
        assert REQUIRED_TOP_LEVEL <= payload.keys(), fixture.name
        assert payload["schema_version"] == 1
        assert payload["contract"] == "pine2ast.inspect.optimizer.v1"
        assert payload["producer"] == {
            "name": "pine2ast",
            "version": payload["tool"]["version"],
            "contract": "pine2ast.inspect.optimizer.v1",
        }
        assert payload["source"]["name"] == fixture.name
        assert payload["ok"] is True
        assert payload["unsupported_features"] == []
        assert isinstance(payload["diagnostics"], list)
        assert isinstance(payload["dependencies"], dict)


def test_optimizer_contract_feature_coverage_v2_20() -> None:
    by_name = {fixture.name: _inspect(fixture) for fixture in FIXTURES}

    assert len(by_name["basic_strategy_inputs.pine"]["inputs"]) >= 3
    assert {c["name"] for c in by_name["tp_sl_trailing_strategy.pine"]["strategy_calls"]} == {
        "strategy.entry",
        "strategy.exit",
    }
    assert by_name["request_security_tuple.pine"]["request_calls"][0]["name"] == "request.security"
    assert [
        i["input_function"] for i in by_name["multiple_input_types_enum_options.pine"]["inputs"]
    ] == [
        "input.string",
        "input.bool",
        "input.source",
        "input.int",
    ]
    assert "array" in by_name["array_map_usage.pine"]["dependencies"]["namespaces"]
    assert "map" in by_name["array_map_usage.pine"]["dependencies"]["namespaces"]
    assert (
        "map.new<string,float>" in by_name["array_map_usage.pine"]["dependencies"]["builtin_calls"]
    )
    assert len(by_name["plot_alert_drawing_mix.pine"]["plots"]) == 2
    assert len(by_name["plot_alert_drawing_mix.pine"]["alerts"]) == 1
    assert len(by_name["plot_alert_drawing_mix.pine"]["drawings"]) == 2
    assert by_name["import_alias_external_call.pine"]["dependencies"]["external_calls"] == [
        "ext.score"
    ]
