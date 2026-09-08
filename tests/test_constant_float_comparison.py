"""Manual decimal relations, independent of PineLib and producer numeric kernels."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

OPERATORS = ("==", "!=", "<", "<=", ">", ">=")
RELATIONS = {
    "equal": (True, False, False, True, False, True),
    "less": (False, True, True, True, False, False),
    "greater": (False, True, False, False, True, True),
}


def evidence(expression, udf, version=6):
    declaration = f"value()=>{expression}\n" if udf else ""
    selected = "value()" if udf else expression
    code = (
        f'//@version={version}\nindicator("Comparison")\n{declaration}x={selected}\nplot(x?1:0)\n'
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    if udf:
        fact = next(
            f
            for f in parsed.semantic_model.semantic_facts.facts
            if f.kind == "CallExpr"
            and f.call_form == "USER_FUNCTION"
            and f.scope_id == "scope:global"
        )
    else:
        fact = next(f for f in parsed.semantic_model.semantic_facts.facts if f.kind == "BinaryExpr")
    return fact, code


@pytest.mark.parametrize("udf", [False, True], ids=["ordinary", "udf"])
@pytest.mark.parametrize(
    "left,right,relation",
    [
        ("1.0000000001", "1.0", "equal"),
        ("1.0000000004", "1.0", "equal"),
        ("1.0000000006", "1.0", "greater"),
        ("1.0000000009", "1.0", "greater"),
        ("0.9999999999", "1.0", "equal"),
        ("0.9999999996", "1.0", "equal"),
        ("0.9999999994", "1.0", "less"),
        ("0.9999999991", "1.0", "less"),
        ("-1.0000000001", "-1.0", "equal"),
        ("-1.0000000004", "-1.0", "equal"),
        ("-1.0000000006", "-1.0", "less"),
        ("-0.9999999999", "-1.0", "equal"),
        ("-0.9999999996", "-1.0", "equal"),
        ("-0.9999999994", "-1.0", "greater"),
        ("0.0000000004", "0.0", "equal"),
        ("-0.0000000004", "0.0", "equal"),
        ("0.0000000006", "0.0", "greater"),
        ("-0.0000000006", "0.0", "less"),
    ],
)
def test_v6_all_operators_use_nine_fractional_digits(left, right, relation, udf):
    for operation, expected in zip(OPERATORS, RELATIONS[relation]):
        fact, code = evidence(f"{left}{operation}{right}", udf)
        assert fact.const_value is expected, (operation, fact.const_value)
        build_consumer_bundle(code)


@pytest.mark.parametrize("udf", [False, True], ids=["ordinary", "udf"])
@pytest.mark.parametrize(
    "number", ["1.0000000005", "-1.0000000005", "0.0000000005", "-0.0000000005"]
)
def test_unspecified_comparison_midpoint_ties_remain_without_value_evidence(number, udf):
    for operation in OPERATORS:
        fact, _ = evidence(f"{number}{operation}1.0", udf)
        assert fact.const_value is None


@pytest.mark.parametrize("udf", [False, True], ids=["ordinary", "udf"])
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("1.0000000001==1", True),
        ("1==1.0000000001", True),
        ("1000000001>1000000000", True),
        ("9007199254740993>9007199254740992", True),
        ("9007199254740993==9007199254740992.0", True),
        ("9007199254740992.0==9007199254740993", True),
        ("-9007199254740993==-9007199254740992.0", True),
        ("-9007199254740992.0==-9007199254740993", True),
        ("true==false", False),
        ("true!=false", True),
        ("-0.0==0.0", True),
        ("(true?1:1.5)==1.0000000001", True),
    ],
)
def test_mixed_numeric_promotion_and_exact_integer_boolean_controls(expression, expected, udf):
    fact, _ = evidence(expression, udf)
    assert fact.const_value is expected


@pytest.mark.parametrize("udf", [False, True], ids=["ordinary", "udf"])
@pytest.mark.parametrize("operation,expected", tuple(zip(OPERATORS, RELATIONS["greater"])))
def test_v5_comparison_facts_are_not_backported_without_historical_authority(
    operation, expected, udf
):
    # Preservation boundary, not a claim of independently established v5 parity.
    fact, _ = evidence(f"1.0000000001{operation}1.0", udf, version=5)
    assert fact.const_value is expected


@pytest.mark.parametrize("operation", OPERATORS)
@pytest.mark.parametrize(
    "left,right",
    [("(true?na:1.0)", "1.0"), ("1.0", "(true?na:1.0)"), ("(true?na:1.0)", "(true?na:1.0)")],
)
def test_v6_known_na_comparisons_are_false(left, right, operation):
    fact, _ = evidence(f"{left}{operation}{right}", False)
    assert fact.const_value is False


@pytest.mark.parametrize("udf", [False, True], ids=["ordinary", "udf"])
@pytest.mark.parametrize("operation", OPERATORS)
def test_unknown_cast_na_and_unreviewed_udf_na_are_not_mistaken_for_known_values(udf, operation):
    fact, _ = evidence(f"float(na){operation}1.0", udf)
    assert fact.const_value is None
