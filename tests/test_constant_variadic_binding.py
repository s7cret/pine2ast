"""Independent min/max values plus complete producer variadic evidence."""

from dataclasses import replace

import pytest

from pine2ast import parse_code
from pine2ast.catalog import load_catalog_readonly_view
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.semantic.binder import SemanticFactBuilder


def code(version, expression):
    return f'//@version={version}\nindicator("Variadic constants")\nx={expression}\nplot(x)\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("math.min(2,1)", 1),
        ("math.min(2,1,3)", 1),
        ("math.max(2,1,3)", 3),
        ("math.max(-2.5,-1.25,-3.0)", -1.25),
        ("math.round(math.min(1.25,2.5),1)", 1.3),
        ("math.round(math.max(-1.25,-2.5),1)", -1.2),
    ],
)
def test_positional_variadic_values_and_complete_bundle_facts(version, expression, expected):
    bundle = build_consumer_bundle(code(version, expression))
    facts = bundle["semantic_facts"]["facts"]
    result = next(
        row for row in facts if row["kind"] == "CallExpr" and row["span"]["start_line"] == 3
    )
    assert result["const_value"] == expected
    assert type(result["const_value"]) is type(expected)
    for call in bundle["semantic_facts"]["calls"]:
        if call["symbol_id"] not in {"pine:function:math.min", "pine:function:math.max"}:
            continue
        assert call["resolution_status"] == "RESOLVED"
        assert call["overload_id"] == call["symbol_id"] + "#canonical"
        assert len(call["arguments"]) >= 2
        assert all(
            arg["parameter_name"] == "values"
            and arg["parameter_index"] == 0
            and arg["binding"] == "vararg"
            and arg["expected_type"] == "float"
            for arg in call["arguments"]
        )
        assert len({arg["argument_node_id"] for arg in call["arguments"]}) == len(call["arguments"])


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name", ["min", "max"])
@pytest.mark.parametrize("bad", ['"bad"', "true"])
def test_every_extra_argument_receives_numeric_type_validation(version, name, bad):
    source = code(version, f"math.{name}(2,{bad},3)")
    parsed = parse_code(source)
    assert not parsed.ok
    assert any(d.code == "P2A1406" for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "mutation",
    [
        "null_parameter",
        "scalar_binding",
        "first_scalar_binding",
        "missing_expected_type",
        "forged_named",
        "duplicate_source",
        "source_order",
        "ghost_parameter",
    ],
)
def test_variadic_folding_still_rejects_incomplete_or_forged_mappings(
    monkeypatch, version, mutation
):
    original = SemanticFactBuilder._resolve_calls

    def alter(self, program):
        original(self, program)
        for key, binding in tuple(self._call_bindings.items()):
            if binding.symbol_id != "pine:function:math.min":
                continue
            args = list(binding.arguments)
            if mutation == "null_parameter":
                args[1] = replace(args[1], parameter_name=None, parameter_index=None)
            elif mutation == "scalar_binding":
                args[1] = replace(args[1], binding="positional")
            elif mutation == "first_scalar_binding":
                args[0] = replace(args[0], binding="positional")
            elif mutation == "missing_expected_type":
                args[1] = replace(args[1], expected_type=None)
            elif mutation == "forged_named":
                args[0] = replace(args[0], binding="named")
            elif mutation == "duplicate_source":
                args[1] = replace(args[1], argument_node_id=args[0].argument_node_id)
            elif mutation == "source_order":
                args.reverse()
            else:
                args[1] = replace(args[1], parameter_name="ghost")
            self._call_bindings[key] = replace(binding, arguments=tuple(args))

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter)
    parsed = parse_code(code(version, "math.min(2,1,3)"))
    result = next(
        row
        for row in parsed.semantic_model.semantic_facts.facts
        if row.kind == "CallExpr" and row.span["start_line"] == 3
    )
    assert result.const_value is None


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_catalog_variadic_metadata_is_not_backported(version):
    catalog = load_catalog_readonly_view(version)
    for name in ("min", "max"):
        entry = catalog["functions"][name]
        assert entry["symbol_id"] == f"pine:function:math.{name}"
        assert not any(p.get("variadic") for p in entry["parameters"])


@pytest.mark.parametrize("version", [5, 6])
def test_numbered_named_argument_support_is_not_invented(version):
    parsed = parse_code(code(version, "math.min(number0=2,number1=1)"))
    assert not parsed.ok
    assert any(d.code == "P2A1403" for d in parsed.diagnostics)
