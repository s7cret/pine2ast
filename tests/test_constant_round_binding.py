"""Manual ties-up oracles; no compiler/runtime output supplies expectations."""

from dataclasses import replace

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.semantic.binder import SemanticFactBuilder

# Official v5/v6 reference: nearest value, ties up; precision overload returns float.
# These literal expectations are independently the neighboring integer/decimal.
ROUND_CASES = [
    ("2.5", None, 3),
    ("-2.5", None, -2),
    ("1.5", None, 2),
    ("-1.5", None, -1),
    ("0.5", None, 1),
    ("-0.5", None, 0),
    ("2.25", None, 2),
    ("-2.25", None, -2),
    ("2.75", None, 3),
    ("-2.75", None, -3),
    ("1.25", "1", 1.3),
    ("-1.25", "1", -1.2),
    ("125", "-1", 130.0),
    ("-125", "-1", -120.0),
]


def source(version, expression):
    return f'//@version={version}\nindicator("Constant rounding")\nx={expression}\nplot(x)\n'


def call_fact(bundle, symbol="pine:function:math.round"):
    return next(
        row
        for row in bundle["semantic_facts"]["facts"]
        if row["kind"] == "CallExpr" and row["symbol_id"] == symbol
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize("number,precision,expected", ROUND_CASES)
def test_round_const_fact_has_pine_ties_and_exact_overload_type(
    version, named, number, precision, expected
):
    if precision is None:
        arguments = f"number={number}" if named else number
    else:
        arguments = f"precision={precision},number={number}" if named else f"{number},{precision}"
    bundle = build_consumer_bundle(source(version, f"math.round({arguments})"))
    fact = call_fact(bundle)
    assert fact["resolved_type"]["qualifier"] == "const"
    assert fact["const_value"] == expected
    assert type(fact["const_value"]) is type(expected)
    assert fact["overload_id"] == (
        "pine:function:math.round#canonical"
        if precision is None
        else "pine:function:math.round#overload:0"
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("expression", ["close", "input.float(2.5)", "na"])
def test_unknown_or_nonconst_round_value_is_never_invented(version, expression):
    fact = call_fact(build_consumer_bundle(source(version, f"math.round({expression})")))
    assert fact["const_value"] is None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("arguments", ["2.5,na", "number=2.5,precision=na"])
def test_explicit_na_precision_is_not_the_omitted_precision(version, arguments):
    fact = call_fact(build_consumer_bundle(source(version, f"math.round({arguments})")))
    assert fact["resolved_type"]["base"] == "float"
    assert fact["const_value"] is None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "arguments,expected",
    [("1.25,1000000000", 1.25), ("1.25,-1000000000", 0.0), ("2,0", 2.0), ("-0.5,0", 0.0)],
)
def test_precision_extremes_and_explicit_zero_keep_float_result(version, arguments, expected):
    fact = call_fact(build_consumer_bundle(source(version, f"math.round({arguments})")))
    assert fact["const_value"] == expected
    assert type(fact["const_value"]) is float


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("change", ["ghost_name", "missing_argument", "duplicate_index"])
def test_round_requires_complete_exact_parameter_mapping(monkeypatch, version, change):
    original = SemanticFactBuilder._resolve_calls

    def alter_arguments(self, program):
        original(self, program)
        for key, binding in tuple(self._call_bindings.items()):
            if binding.symbol_id == "pine:function:math.round":
                arguments = binding.arguments
                if change == "ghost_name":
                    arguments = (replace(arguments[0], parameter_name="ghost"), arguments[1])
                elif change == "missing_argument":
                    arguments = arguments[:1]
                else:
                    arguments = (arguments[0], replace(arguments[1], parameter_index=0))
                self._call_bindings[key] = replace(binding, arguments=arguments)

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter_arguments)
    parsed = parse_code(source(version, "math.round(1.25,1)"))
    facts = parsed.semantic_model.semantic_facts.facts
    fact = next(row for row in facts if row.kind == "CallExpr" and row.span["start_line"] == 3)
    assert fact.const_value is None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "mutation",
    [
        {"symbol_id": "user:function:math.round:n00000001"},
        {"overload_id": "pine:function:math.round#overload:999"},
        {"resolution_status": "INVALID"},
        {"stateful": True},
        {"call_form": "USER_METHOD"},
    ],
)
def test_folding_requires_resolved_builtin_contract(monkeypatch, version, mutation):
    original = SemanticFactBuilder._resolve_calls

    def alter_binding(self, program):
        original(self, program)
        for key, binding in tuple(self._call_bindings.items()):
            if binding.symbol_id == "pine:function:math.round":
                self._call_bindings[key] = replace(binding, **mutation)

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter_binding)
    parsed = parse_code(source(version, "math.round(2.25)"))
    # Inspect producer facts directly: the deliberate invalid binding is not a bundle.
    rows = parsed.semantic_model.semantic_facts.facts
    fact = next(row for row in rows if row.kind == "CallExpr" and row.span["start_line"] == 3)
    assert fact.const_value is None


@pytest.mark.parametrize("version", [5, 6])
def test_binding_identity_controls_folding_not_display_callee(monkeypatch, version):
    original = SemanticFactBuilder._resolve_calls

    def alter_display(self, program):
        original(self, program)
        for key, binding in tuple(self._call_bindings.items()):
            if binding.symbol_id == "pine:function:math.round":
                self._call_bindings[key] = replace(binding, callee="display-label-only")

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter_display)
    parsed = parse_code(source(version, "math.round(2.5)"))
    rows = parsed.semantic_model.semantic_facts.facts
    fact = next(row for row in rows if row.kind == "CallExpr" and row.span["start_line"] == 3)
    assert fact.const_value == 3
    assert type(fact.const_value) is int


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_round_callable_does_not_gain_unreviewed_constant_folding(version):
    parsed = parse_code(f'//@version={version}\nstudy("Old")\nx=round(2.5)\nplot(x)\n')
    assert parsed.ok, parsed.diagnostics
    facts = parsed.semantic_model.semantic_facts.facts
    fact = next(row for row in facts if row.kind == "CallExpr" and row.span["start_line"] == 3)
    assert fact.const_value is None


@pytest.mark.parametrize("version,expected", [(1, 2), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2.5)])
def test_version_specific_constant_integer_division_control(version, expected):
    declaration = "study" if version < 5 else "indicator"
    parsed = parse_code(f'//@version={version}\n{declaration}("Division")\nx=5/2\nplot(x)\n')
    assert parsed.ok, parsed.diagnostics
    fact = next(
        row for row in parsed.semantic_model.semantic_facts.facts if row.kind == "BinaryExpr"
    )
    assert fact.const_value == expected
    assert type(fact.const_value) is type(expected)
