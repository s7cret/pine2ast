"""Stage 2.1: exact modern input catalog, version and qualifier boundaries.

Authorities:
- https://www.tradingview.com/pine-script-docs/v5/concepts/inputs/
- https://www.tradingview.com/pine-script-docs/concepts/inputs/
- https://www.tradingview.com/pine-script-reference/v6/

The tests lock the supported v5/v6 surface and prevent it from leaking into
historical packs. They do not claim that the in-tree catalog is an exhaustive
copy of every TradingView symbol.
"""

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import ast_payload, parse_source, semantic_facts_payload

V5_GENERIC = ["defval", "title", "tooltip", "inline", "group"]
V6_GENERIC = ["defval", "title", "tooltip", "inline", "group", "display", "active"]
V6_GENERIC_SOURCE = ["defval", "title", "inline", "group", "tooltip", "display", "active"]
V5_NUMERIC_BOUNDED = [
    "defval",
    "title",
    "minval",
    "maxval",
    "step",
    "tooltip",
    "inline",
    "group",
    "confirm",
]
V5_NUMERIC_OPTIONS = ["defval", "title", "options", "tooltip", "inline", "group", "confirm"]
V6_NUMERIC_BOUNDED = [*V5_NUMERIC_BOUNDED, "display", "active"]
V6_NUMERIC_OPTIONS = [*V5_NUMERIC_OPTIONS, "display", "active"]
MODERN_INPUTS = {
    "input",
    "input.bool",
    "input.color",
    "input.enum",
    "input.float",
    "input.int",
    "input.price",
    "input.session",
    "input.source",
    "input.string",
    "input.symbol",
    "input.text_area",
    "input.time",
    "input.timeframe",
}


def names(row):
    return [parameter["name"] for parameter in row["parameters"]]


def compile_ok(source: str):
    result = parse_code(source)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    bundle = build_consumer_bundle(source)
    return semantic_facts_payload(parse_source(source), ast_payload(parse_source(source))), bundle


def compile_bad(source: str, fragment: str | None = None):
    result = parse_code(source)
    assert not result.ok
    if fragment:
        assert any(fragment.lower() in d.message.lower() for d in result.diagnostics), [
            (d.code, d.message) for d in result.diagnostics
        ]
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


def test_exact_generic_input_overloads_and_qualifiers():
    repo = CatalogRepository.default()
    for version in (5, 6):
        row = repo.pack(version)["sections"]["functions"]["input"]
        assert row["allow_extra_positional"] is False
        assert len(row["overloads"]) == 6
        expected = V5_GENERIC if version == 5 else V6_GENERIC
        for overload in row["overloads"][:5]:
            assert names(overload) == expected
            assert overload["parameters"][0]["qualifier_max"] == "const"
            assert overload["return_qualifier"] == "input"
        source = row["overloads"][5]
        assert names(source) == (V5_GENERIC if version == 5 else V6_GENERIC_SOURCE)
        assert source["parameters"][0]["qualifier_max"] == "series"
        assert source["return_qualifier"] == "series"


@pytest.mark.parametrize("name", ["input.int", "input.float"])
def test_exact_numeric_overloads_are_disjoint(name):
    repo = CatalogRepository.default()
    for version, bounded, options in (
        (5, V5_NUMERIC_BOUNDED, V5_NUMERIC_OPTIONS),
        (6, V6_NUMERIC_BOUNDED, V6_NUMERIC_OPTIONS),
    ):
        row = repo.pack(version)["sections"]["functions"][name]
        assert row["allow_extra_positional"] is False
        assert names(row) == bounded
        assert names(row["overloads"][0]) == options
        assert "options" not in names(row)
        assert not {"minval", "maxval", "step"}.intersection(names(row["overloads"][0]))
        for candidate in (row, row["overloads"][0]):
            assert candidate["parameters"][0]["qualifier_max"] == "const"
            assert candidate["return_qualifier"] == "input"


def test_specialized_input_version_inventory_has_no_backport():
    repo = CatalogRepository.default()
    for version in range(1, 5):
        functions = repo.pack(version)["sections"]["functions"]
        assert not (MODERN_INPUTS - {"input"}).intersection(functions)
    for version in (5, 6):
        functions = repo.pack(version)["sections"]["functions"]
        assert MODERN_INPUTS <= set(functions)
        assert all(functions[name].get("allow_extra_positional") is False for name in MODERN_INPUTS)


def test_v6_active_is_input_bool_and_not_backported_to_v5():
    repo = CatalogRepository.default()
    for name in MODERN_INPUTS:
        v5 = repo.pack(5)["sections"]["functions"][name]
        v6 = repo.pack(6)["sections"]["functions"][name]
        assert "active" not in names(v5)
        active = next(p for p in v6["parameters"] if p["name"] == "active")
        assert active == {
            "name": "active",
            "required": False,
            "type": "bool",
            "qualifier_max": "input",
            "default": True,
        }


@pytest.mark.parametrize("version", [5, 6])
def test_enum_and_text_area_are_real_versioned_calls(version):
    source = f"""//@version={version}
indicator("inputs")
enum Mode
    fast
    slow
mode=input.enum(Mode.fast,"Mode",options=[Mode.fast,Mode.slow])
text=input.text_area("a\\nb","Text")
plot(mode==Mode.fast ? str.length(text) : 0)
"""
    facts, _ = compile_ok(source)
    calls = {row["callee"]: row for row in facts["calls"]}
    assert calls["input.enum"]["return_type"] == "Mode"
    assert calls["input.text_area"]["return_type"] == "string"
    catalog = CatalogRepository.default().pack(version)["sections"]["functions"]
    assert catalog["input.enum"]["return_qualifier"] == "input"
    assert catalog["input.text_area"]["return_qualifier"] == "input"


@pytest.mark.parametrize("version", range(1, 5))
@pytest.mark.parametrize("call", ['input.text_area("x")', "input.enum(E.a)"])
def test_modern_specialized_inputs_are_rejected_in_historical_versions(version, call):
    declaration = "study" if version < 4 else "study"
    prefix = "enum E\n    a\n" if "enum" in call else ""
    compile_bad(f'//@version={version}\n{declaration}("bad")\n{prefix}x={call}\n')


def test_enum_options_must_keep_one_nominal_type():
    compile_bad(
        """//@version=6
indicator("bad")
enum A
    x
enum B
    x
m=input.enum(A.x,options=[A.x,B.x])
""",
        "enum",
    )


def test_active_and_overload_negative_boundaries_are_explicit():
    compile_ok("""//@version=6
indicator("active")
enabled=input.bool(true)
length=input.int(10,active=enabled)
plot(length)
""")
    compile_bad(
        """//@version=5
indicator("active")
enabled=input.bool(true)
length=input.int(10,active=enabled)
""",
        "active",
    )
    compile_bad("""//@version=6
indicator("mixed")
length=input.int(10,options=[5,10],minval=1)
""")
    compile_bad("""//@version=6
indicator("tail")
x=input.int(1,"x",0,10,1,"tip","i","g",false,display.all,true,99)
""")


def test_generic_scalar_and_source_choose_distinct_overloads():
    source = """//@version=6
indicator("generic")
a=input(1.5)
b=input(close)
plot(a+b)
"""
    facts, _ = compile_ok(source)
    calls = [row for row in facts["calls"] if row["callee"] == "input"]
    assert [row["overload_id"] for row in calls] == [
        "pine:function:input#overload:1",
        "pine:function:input#overload:5",
    ]
    catalog = CatalogRepository.default().pack(6)["sections"]["functions"]["input"]
    by_id = {row["overload_id"]: row for row in catalog["overloads"]}
    assert [by_id[row["overload_id"]]["return_qualifier"] for row in calls] == ["input", "series"]


def test_mutated_input_variable_cannot_satisfy_input_qualified_active():
    compile_bad("""//@version=6
indicator("mutated")
enabled=input.bool(true)
enabled:=false
length=input.int(10,active=enabled)
plot(length)
""")


def test_ta_rma_has_exact_modern_contract_without_historical_backport():
    repo = CatalogRepository.default()
    expected = [
        {"name": "source", "qualifier_max": "series", "required": True, "type": "float"},
        {"name": "length", "qualifier_max": "simple", "required": True, "type": "int"},
    ]
    for version in (5, 6):
        row = repo.pack(version)["sections"]["functions"]["ta.rma"]
        assert row["parameters"] == expected
        assert row["returns"] == "series<float>"
    for version in range(1, 5):
        assert "ta.rma" not in repo.pack(version)["sections"]["functions"]
