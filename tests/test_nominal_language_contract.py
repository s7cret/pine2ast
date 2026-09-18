"""Nominal receiver/enum identity and UDT defaults in the producer contract.

Independent language sources:
https://www.tradingview.com/pine-script-docs/language/type-system/
https://www.tradingview.com/pine-script-docs/language/enums/
https://www.tradingview.com/pine-script-docs/language/methods/
"""

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import FieldDeclaration, TypeDeclaration
from pine2ast.ast.walk import iter_nodes
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.hardening.introspection import ast_payload, parse_source, semantic_facts_payload


def _facts(source):
    parsed = parse_source(source, source_name="nominal.pine")
    payload = semantic_facts_payload(parsed, ast_payload(parsed))
    assert build_consumer_bundle(source)
    return payload


@pytest.mark.parametrize("version", [5, 6])
def test_same_named_methods_preserve_receiver_return_and_state_identity(version):
    source = f"""//@version={version}
indicator("receivers")
type A
    int number = 1
type B
    string text = "b"
method read(A self, int extra = 0) =>
    var count = 0
    count += 1
    self.number + extra + count
method read(B self, string extra = "!") => self.text + extra
a = A.new()
b = B.new()
int number = a.read(extra=2)
string text = b.read(extra="?")
"""
    result = parse_code(source)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    calls = [row for row in _facts(source)["calls"] if row["call_form"] == "USER_METHOD"]
    assert len(calls) == 2
    by_receiver = {row["receiver_type"]: row for row in calls}
    assert by_receiver["A"]["return_type"] == "int"
    assert by_receiver["B"]["return_type"] == "string"
    assert by_receiver["A"]["symbol_id"] != by_receiver["B"]["symbol_id"]
    assert by_receiver["A"]["stateful"] is True
    assert by_receiver["B"]["stateful"] is False


@pytest.mark.parametrize("version", [5, 6])
def test_generic_method_receiver_keeps_all_type_arguments(version):
    source = f"""//@version={version}
indicator("generic methods")
method firstValue(array<int> self) => array.get(self, 0)
method firstValue(array<string> self) => array.get(self, 0)
numbers = array.new<int>(1, 2)
texts = array.new<string>(1, "x")
int number = numbers.firstValue()
string text = texts.firstValue()
"""
    calls = [row for row in _facts(source)["calls"] if row["call_form"] == "USER_METHOD"]
    assert {(row["receiver_type"], row["return_type"]) for row in calls} == {
        ("array<int>", "int"),
        ("array<string>", "string"),
    }


@pytest.mark.parametrize("receiver", ["array.new<float>(1, 2.5)", 'array.new<string>(1, "x")'])
def test_method_cannot_match_only_the_generic_receiver_base(receiver):
    result = parse_code(f"""//@version=6
indicator("wrong receiver")
method read(array<int> self) => array.get(self, 0)
value = {receiver}
x = value.read()
""")
    assert not result.ok
    assert any("receiver" in d.message for d in result.diagnostics)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("operator", ["==", "!="])
@pytest.mark.parametrize("right", ["Other.up", '"Up"', "1"])
def test_enum_comparison_rejects_a_different_nominal_type(version, operator, right):
    source = f"""//@version={version}
indicator("enum types")
enum Side
    up = "Up"
enum Other
    up = "Up"
x = Side.up {operator} {right}
"""
    result = parse_code(source)
    assert not result.ok
    assert any("same enum type" in d.message for d in result.diagnostics)


@pytest.mark.parametrize("version", [5, 6])
def test_enum_titles_same_type_arguments_and_return_values(version):
    source = f"""//@version={version}
indicator("enum values")
enum Side
    up = "Up"
    down = "Down"
echo(Side direction) => direction
x = echo(Side.up) != Side.down
"""
    assert parse_code(source).ok
    assert build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
def test_udt_implicit_defaults_and_copy_have_complete_argument_facts(version):
    source = f"""//@version={version}
indicator("default objects")
type Point
    int time
    bool active
    float price = 1.5
p = Point.new()
a = p.copy()
b = Point.copy(object=p)
"""
    calls = _facts(source)["calls"]
    constructor = next(row for row in calls if row["call_form"] == "UDT_CONSTRUCTOR")
    assert {row["parameter_name"] for row in constructor["defaults_applied"]} == {
        "time",
        "active",
        "price",
    }
    assert all(row["max_qualifier"] == "series" for row in constructor["defaults_applied"])
    copies = [row for row in calls if row["call_form"] == "UDT_COPY"]
    assert len(copies) == 2
    assert {row["return_type"] for row in copies} == {"Point"}
    assert all(row["overload_id"].endswith("#copy") for row in copies)
    assert all(row["symbol_id"] == constructor["symbol_id"] for row in copies)


@pytest.mark.parametrize(
    "expression", ["a.copy(1)", "A.copy()", "A.copy(b)", 'A.new(n="wrong")', "A.new(unknown=1)"]
)
def test_udt_defaulting_does_not_weaken_constructor_or_copy_validation(expression):
    result = parse_code(f"""//@version=6
indicator("invalid objects")
type A
    int n
type B
    int n
a = A.new()
b = B.new()
x = {expression}
""")
    assert not result.ok


@pytest.mark.parametrize("version", [5, 6])
def test_varip_is_a_field_property_and_plain_fields_preserve_serialization(version):
    source = f"""//@version={version}
indicator("field persistence")
type State
    int normal
    varip int ticks
state = State.new()
"""
    result = parse_code(source)
    assert result.ok
    fields = [node for node in iter_nodes(result.ast) if isinstance(node, FieldDeclaration)]
    assert fields[0].mode is None
    assert "mode" not in fields[0].to_dict()
    assert fields[1].mode == "varip"
    assert fields[1].to_dict()["mode"] == "varip"
    assert build_consumer_bundle(source)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_nominal_declarations_are_unavailable_before_v5(version):
    result = parse_code(f"""//@version={version}
study("old")
type State
    varip int ticks
enum Side
    up = "Up"
""")
    assert not result.ok


def test_qualified_type_span_includes_member_for_library_projection():
    source = """//@version=6
indicator("span")
import owner/Shapes/1 as shapes
type Container
    shapes.Point point
"""
    result = parse_code(source)
    declaration = next(node for node in result.ast.items if isinstance(node, TypeDeclaration))
    type_ref = declaration.fields[0].type_ref
    assert type_ref.name == "shapes.Point"
    assert source[type_ref.span.start_offset : type_ref.span.end_offset] == "shapes.Point"


def test_enum_title_requires_a_string_after_equals():
    result = parse_code('//@version=6\nindicator("bad")\nenum Side\n    up = 42\n')
    assert not result.ok
