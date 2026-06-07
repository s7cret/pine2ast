from __future__ import annotations

import json
from importlib.resources import files

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.reference_catalog import load_catalog, load_parity_matrix
from pine2ast.reference_catalog.official_reference import (
    OfficialReferenceIndex,
    _extract_reference_categories,
    official_reference_gate_payload,
    official_reference_diff_payload,
)
from pine2ast.semantic.builtin_registry import load_builtin_registry


def test_extract_reference_categories_uses_top_level_doc_names_only() -> None:
    bundle = r"""
    const s={
      keywords:[{name:"if",syntax:["if condition"]}],
      types:[{name:"series"}],
      functions:[
        {name:"request.security",args:[{name:"symbol"},{name:"timeframe"}]},
        {name:"strategy.entry",args:[{name:"id"},{name:"direction"}]}
      ],
      variables:[{name:"bar_index"},{name:"close"}],
      methods:[{name:"copy",originalName:"box.copy",args:[{name:"id"}]}],
      constants:[{name:"strategy.long"}],
      annotations:[{name:"@version="}],
      operators:[{name:"+"}]
    };
    """

    categories = _extract_reference_categories(bundle)

    assert categories["functions"] == ["request.security", "strategy.entry"]
    assert "symbol" not in categories["functions"]
    assert categories["methods"] == ["box.copy"]
    assert categories["variables"] == ["bar_index", "close"]


def test_official_reference_diff_reports_missing_items(monkeypatch) -> None:
    index = OfficialReferenceIndex(
        pine_version=6,
        source_url="https://example.test/reference",
        bundle_url="https://example.test/bundle.js",
        categories={
            "functions": ["ta.ema", "request.security"],
            "variables": ["close", "bar_index"],
            "types": ["int", "chart.point"],
        },
    )

    def fake_registry():
        return {
            "functions": {"ta.ema": {}},
            "variables": {"close": {}},
            "types": {"int": {}},
            "namespaces": {},
        }

    monkeypatch.setattr(
        "pine2ast.reference_catalog.official_reference.load_builtin_registry",
        fake_registry,
    )

    payload = official_reference_diff_payload(index)

    assert payload["summary"]["official_comparable_count"] == 6
    assert payload["summary"]["missing_official_count"] == 3
    assert payload["missing_by_category"]["functions"] == ["request.security"]
    assert payload["missing_by_category"]["variables"] == ["bar_index"]
    assert payload["missing_by_category"]["types"] == ["chart.point"]


def test_official_reference_gate_fails_on_new_missing(monkeypatch, tmp_path) -> None:
    index = OfficialReferenceIndex(
        pine_version=6,
        source_url="https://example.test/reference",
        bundle_url="https://example.test/bundle.js",
        categories={
            "functions": ["ta.ema", "request.security"],
            "variables": ["close"],
            "types": ["int"],
        },
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        """{
          "schema_version": "pain.official_pine_reference_gap_baseline.v1",
          "pine_version": 6,
          "max_missing_official_count": 0,
          "min_coverage_ratio": 1.0,
          "missing_by_category": {"functions": [], "variables": [], "types": []}
        }""",
        encoding="utf-8",
    )

    def fake_registry():
        return {
            "functions": {"ta.ema": {}},
            "variables": {"close": {}},
            "types": {"int": {}},
            "namespaces": {},
        }

    monkeypatch.setattr(
        "pine2ast.reference_catalog.official_reference.load_builtin_registry",
        fake_registry,
    )

    payload = official_reference_gate_payload(index, str(baseline))

    assert payload["status"] == "fail"
    assert payload["new_missing_by_category"]["functions"] == ["request.security"]


def test_official_collection_functions_are_registered_with_valid_schema() -> None:
    index_path = files("pine2ast.reference_catalog").joinpath(
        "official_pine_v6_reference_index.json"
    )
    official_index = json.loads(index_path.read_text(encoding="utf-8"))
    official_collection_functions = {
        name
        for name in official_index["categories"]["functions"]
        if name.startswith(("array.", "map.", "matrix."))
    }

    registry = load_builtin_registry()
    missing = sorted(official_collection_functions - set(registry["functions"]))

    assert missing == []
    assert registry["functions"]["array.new_linefill"]["returns"] == "array<linefill>"
    assert registry["functions"]["map.new<type,type>"]["returns"] == "map<any,any>"
    assert registry["functions"]["matrix.eigenvalues"]["returns"] == "array<float>"


OFFICIAL_CALLABLE_TAIL = {
    "input",
    "max_bars_back",
    "syminfo.prefix",
    "syminfo.ticker",
    "table",
    "ticker.heikinashi",
    "ticker.inherit",
    "ticker.kagi",
    "ticker.linebreak",
    "ticker.modify",
    "ticker.new",
    "ticker.pointfigure",
    "ticker.renko",
    "ticker.standard",
    "timeframe.from_seconds",
    "timeframe.in_seconds",
    "weekofyear",
}

OFFICIAL_TABLE_TAIL = {
    "table.cell_set_text_font_family",
    "table.cell_set_text_formatting",
    "table.cell_set_text_halign",
    "table.cell_set_text_valign",
    "table.cell_set_tooltip",
    "table.set_bgcolor",
    "table.set_border_color",
    "table.set_border_width",
    "table.set_frame_color",
    "table.set_frame_width",
}

OFFICIAL_STRATEGY_TAIL_FUNCTIONS = {
    "strategy.convert_to_account",
    "strategy.convert_to_symbol",
    "strategy.default_entry_qty",
}

OFFICIAL_STRATEGY_TAIL_VARIABLES = {
    "strategy.account_currency": ("string", "simple"),
    "strategy.avg_losing_trade": ("float", "series"),
    "strategy.avg_losing_trade_percent": ("float", "series"),
    "strategy.avg_trade": ("float", "series"),
    "strategy.avg_trade_percent": ("float", "series"),
    "strategy.avg_winning_trade": ("float", "series"),
    "strategy.avg_winning_trade_percent": ("float", "series"),
    "strategy.grossloss_percent": ("float", "series"),
    "strategy.grossprofit_percent": ("float", "series"),
    "strategy.margin_liquidation_price": ("float", "series"),
    "strategy.max_contracts_held_all": ("float", "series"),
    "strategy.max_contracts_held_long": ("float", "series"),
    "strategy.max_contracts_held_short": ("float", "series"),
    "strategy.max_drawdown": ("float", "series"),
    "strategy.max_drawdown_percent": ("float", "series"),
    "strategy.max_runup": ("float", "series"),
    "strategy.max_runup_percent": ("float", "series"),
    "strategy.netprofit_percent": ("float", "series"),
    "strategy.openprofit_percent": ("float", "series"),
    "strategy.position_entry_name": ("string", "series"),
}


def test_official_tail_callables_are_registered_and_tracked_conservatively() -> None:
    registry = load_builtin_registry()
    catalog = {entry["id"]: entry for entry in load_catalog()["entries"]}
    matrix = {
        (item["official_category"], item["id"]): item for item in load_parity_matrix()["items"]
    }

    assert OFFICIAL_CALLABLE_TAIL <= set(registry["functions"])
    for name in OFFICIAL_CALLABLE_TAIL:
        assert ("functions", name) in matrix
        assert registry["functions"][name]["scope"] == "any"

    for name in OFFICIAL_CALLABLE_TAIL - {
        "input",
        "syminfo.prefix",
        "syminfo.ticker",
        "weekofyear",
    }:
        assert catalog[name]["kind"] == "function"
        assert catalog[name]["semantic_status"] in {"IMPLEMENTED_UNVERIFIED", "DONE_VERIFIED"}
        assert catalog[name]["runtime_status"] == "NOT_STARTED"

    assert matrix[("variables", "syminfo.prefix")]["semantic_status"] in {
        "IMPLEMENTED_UNVERIFIED",
        "DONE_VERIFIED",
    }
    for name in OFFICIAL_CALLABLE_TAIL - {"input"}:
        assert matrix[("functions", name)]["runtime_status"] == "NOT_STARTED"


def test_official_tail_callables_do_not_trip_strict_builtin_checks() -> None:
    source = """//@version=6
indicator("official tail callables")
base = input(close, "Base")
max_bars_back(close, 500)
prefix = syminfo.prefix()
symbol = syminfo.ticker()
tb = table(position.top_right, 1, 1)
ha = ticker.heikinashi(syminfo.tickerid)
renko = ticker.renko(symbol, "ATR", 14)
kagi = ticker.kagi(prefix, 3)
lb = ticker.linebreak(symbol, 3)
pf = ticker.pointfigure(symbol, "hl", "ATR", 14, 3)
std = ticker.standard(syminfo.tickerid)
mod = ticker.modify(std, session = session.extended)
inherit = ticker.inherit(mod, symbol)
secs = timeframe.in_seconds()
tf = timeframe.from_seconds(secs)
w = weekofyear(time, syminfo.timezone)
plot(w + secs)
"""

    result = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    errors = [
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity in {Severity.ERROR, Severity.FATAL}
    ]

    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
    assert codes.UNKNOWN_PARAMETER not in errors


def test_official_table_tail_is_registered_and_tracked_conservatively() -> None:
    registry = load_builtin_registry()
    catalog = {entry["id"]: entry for entry in load_catalog()["entries"]}
    matrix = {
        (item["official_category"], item["id"]): item for item in load_parity_matrix()["items"]
    }

    assert OFFICIAL_TABLE_TAIL <= set(registry["functions"])
    for name in OFFICIAL_TABLE_TAIL:
        entry = registry["functions"][name]
        assert entry["scope"] == "any"
        assert entry["returns"] == "void"
        assert catalog[name]["kind"] == "function"
        assert catalog[name]["semantic_status"] in {"IMPLEMENTED_UNVERIFIED", "DONE_VERIFIED"}
        assert catalog[name]["runtime_status"] == "NOT_STARTED"
        assert matrix[("functions", name)]["runtime_status"] == "NOT_STARTED"
        assert matrix[("methods", name)]["runtime_status"] == "NOT_STARTED"

    for baseline_name in (
        "official_pine_v5_gap_baseline.json",
        "official_pine_v6_gap_baseline.json",
    ):
        baseline = json.loads(
            files("pine2ast.reference_catalog").joinpath(baseline_name).read_text(encoding="utf-8")
        )
        assert not (OFFICIAL_TABLE_TAIL & set(baseline["missing_by_category"]["functions"]))


def test_official_strategy_tail_is_registered_and_tracked_conservatively() -> None:
    registry = load_builtin_registry()
    catalog = {entry["id"]: entry for entry in load_catalog()["entries"]}
    matrix = {
        (item["official_category"], item["id"]): item for item in load_parity_matrix()["items"]
    }

    assert OFFICIAL_STRATEGY_TAIL_FUNCTIONS <= set(registry["functions"])
    for name in OFFICIAL_STRATEGY_TAIL_FUNCTIONS:
        entry = registry["functions"][name]
        assert entry["scope"] == "any"
        assert entry["returns"] == "float"
        assert catalog[name]["kind"] == "function"
        assert catalog[name]["semantic_status"] in {"IMPLEMENTED_UNVERIFIED", "DONE_VERIFIED"}
        assert catalog[name]["runtime_status"] == "NOT_STARTED"
        assert matrix[("functions", name)]["runtime_status"] == "NOT_STARTED"

    for name, (typ, qualifier) in OFFICIAL_STRATEGY_TAIL_VARIABLES.items():
        assert registry["variables"][name] == {"type": typ, "qualifier": qualifier}
        assert catalog[name]["kind"] == "variable"
        assert catalog[name]["semantic_status"] in {"IMPLEMENTED_UNVERIFIED", "DONE_VERIFIED"}
        assert catalog[name]["runtime_status"] == "NOT_STARTED"
        assert matrix[("variables", name)]["runtime_status"] == "NOT_STARTED"

    for baseline_name in (
        "official_pine_v5_gap_baseline.json",
        "official_pine_v6_gap_baseline.json",
    ):
        baseline = json.loads(
            files("pine2ast.reference_catalog").joinpath(baseline_name).read_text(encoding="utf-8")
        )
        assert not (
            OFFICIAL_STRATEGY_TAIL_FUNCTIONS & set(baseline["missing_by_category"]["functions"])
        )
        assert not (
            set(OFFICIAL_STRATEGY_TAIL_VARIABLES)
            & set(baseline["missing_by_category"]["variables"])
        )


def test_official_table_tail_do_not_trip_strict_builtin_checks() -> None:
    source = """//@version=6
indicator("official table tail")
t = table.new(position.top_right, 2, 2, bgcolor = color.black, frame_color = color.gray, frame_width = 1, border_color = color.silver, border_width = 1)
table.cell(t, 0, 0, text = "a", text_halign = text.align_center, text_valign = text.align_top, text_size = size.small)
table.cell_set_text_font_family(t, 0, 0, text_font_family = font.family_monospace)
table.cell_set_text_formatting(t, 0, 0, text_formatting = text.format_bold)
table.cell_set_text_halign(t, 0, 0, text_halign = text.align_right)
table.cell_set_text_valign(t, 0, 0, text_valign = text.align_bottom)
table.cell_set_tooltip(t, 0, 0, tooltip = "tip")
table.set_bgcolor(t, bgcolor = color.new(color.blue, 80))
table.set_border_color(t, border_color = color.red)
table.set_border_width(t, border_width = 2)
table.set_frame_color(t, frame_color = color.green)
table.set_frame_width(t, frame_width = 3)
plot(close)
"""

    result = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    errors = [
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity in {Severity.ERROR, Severity.FATAL}
    ]

    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
    assert codes.ARGUMENT_TYPE not in errors


def test_official_strategy_tail_do_not_trip_strict_builtin_checks() -> None:
    source = """//@version=6
strategy("official strategy tail")
accountValue = strategy.convert_to_account(close)
symbolValue = strategy.convert_to_symbol(accountValue)
qty = strategy.default_entry_qty(close)
string account = strategy.account_currency
string entryName = strategy.position_entry_name
float totals = strategy.avg_losing_trade + strategy.avg_trade + strategy.avg_winning_trade
float pct = strategy.avg_losing_trade_percent + strategy.avg_trade_percent + strategy.avg_winning_trade_percent
float profitPct = strategy.grossloss_percent + strategy.grossprofit_percent + strategy.netprofit_percent + strategy.openprofit_percent
float risk = strategy.margin_liquidation_price + strategy.max_drawdown + strategy.max_drawdown_percent + strategy.max_runup + strategy.max_runup_percent
float held = strategy.max_contracts_held_all + strategy.max_contracts_held_long + strategy.max_contracts_held_short
plot(symbolValue + qty + totals + pct + profitPct + risk + held)
"""

    result = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    errors = [
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity in {Severity.ERROR, Severity.FATAL}
    ]

    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
