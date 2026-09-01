"""Behavioral coverage for parser, semantic analysis, and frontend extraction.

The cases deliberately combine valid Pine programs with fail-closed negative
programs.  Assertions cover AST shape, diagnostics, and the generated consumer
contract rather than merely executing code for coverage.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.walk import iter_nodes
from pine2ast.frontend.schema import validate_openpine_contract_payload

SOURCES: dict[str, str] = {
    "control": """//@version=6
indicator("all", overlay=true)
var float x = 1.0
x += 2.0
if x > 0
    x := x - 1
else if x < 0
    x := 0
else
    x := 1
for i = 0 to 3 by 1
    x += i
while x < 10
    x += 1
    break
switch x
    1 => x := 2
    => x := 3
plot(x)
""",
    "declarations": """//@version=6
indicator("decls")
type Point
    float x = 0.0
    float y = 1.0
enum Side
    left "Left"
    right
f(float a, int b = 1) => a + b
method plus(Point self, float amount = 1.0) => self.x + amount
p = Point.new(1.0, 2.0)
x = f(p.x)
y = p.plus(2.0)
plot(x + y)
""",
    "library": """//@version=6
library("lib")
export type Point
    float x = 0.0
    int y = 1
export enum Side
    left "Left"
    right
//@function adds one
//@param x source
//@returns value
export add(float x, int n = 1) => x + n
export method bump(Point self, float delta = 1.0) => self.x + delta
""",
    "collections": """//@version=6
indicator("collections")
var float[] a = array.new_float(0)
array.push(a, close)
first = array.get(a, 0)
var map<string, float> m = map.new<string, float>()
map.put(m, "x", first)
got = map.get(m, "x")
var matrix<float> mat = matrix.new<float>(2, 2, 0.0)
for [i, v] in a
    array.set(a, i, v + 1)
for v in a
    first += v
plot(first + got)
""",
    "expressions": """//@version=6
indicator("exprs")
a = 1 + 2 * 3 - 4 / 2 % 2
b = not false and true or false
c = a > 0 ? a : -a
d = [1, 2.0, "x", true, na]
e = close[1]
f = math.max(a, c)
g = (a + c) * 2
plot(a)
""",
    "switch_functions": """//@version=6
indicator("switches")
f(int x) => switch x
    1 => 1
    2 =>
        y = 2
        y
    => 0
g(bool c) => if c
    1
else
    2
x = f(1)
y = g(true)
plot(x + y)
""",
    "loops": """//@version=6
indicator("loops")
var float[] xs = array.from(1.0, 2.0, 3.0)
s = 0.0
for [i, v] in xs
    if i == 1
        continue
    s += v
for v in xs
    s += v
for i = 3 to 0 by -1
    s += i
while true
    s += 1
    break
plot(s)
""",
    "parse_and_semantic_errors": """//@version=6
indicator("errors", overlay=close)
float x = "bad"
y := 1
z += 2
break
continue
if close
x = 1
for [a, b, c] in array.from(1,2)
    x = a
switch
1 => 2
unknown_call(1, bad=2)
""",
    "duplicates": """//@version=6
indicator("dup")
type Point
    float x
    int x
enum E
    a
    a
x = 1
x = 2
""",
    "imports": """//@version=6
indicator("imports")
import user/lib/1 as lib
import owner/other/2
x = lib.foo(close)
y = other.bar(1)
plot(x)
""",
    "generic_errors": """//@version=6
indicator("generic")
var map<float, int> bad_key = map.new<float, int>()
var map<string> bad_arity = map.new<string>()
var matrix<float> mat = matrix.new<float>()
var array<int> values = array.new<int>()
array.push(values, "bad")
map.put(bad_key, 1.0, 2)
""",
    "members": """//@version=6
indicator("members")
type Point
    float x
p = Point.new(1.0)
p.x := 2.0
p.missing := 1
x = p.missing
plot(p.x)
""",
    "arguments": """//@version=6
indicator("args")
a = ta.sma(source=close, length=3)
b = ta.sma(close, 3, 4)
c = ta.sma(close, length=3, source=open)
d = ta.sma(close)
e = math.max(1, 2)
plot(a)
""",
    "strategy": """//@version=6
strategy("s", pyramiding=1, calc_on_every_tick=true)
strategy.entry("L", strategy.long, qty=1)
strategy.exit("X", "L", stop=close - 1, limit=close + 1)
strategy.order("O", strategy.short, qty=1)
strategy.close("L")
""",
    "requests": """//@version=6
indicator("req")
a = request.security(syminfo.tickerid, "D", close)
b = request.security_lower_tf(syminfo.tickerid, "1", close)
c = request.seed("repo", "symbol", close)
plot(a)
""",
}


EXPECTED_KINDS = {
    "control": {"IfStructure", "ForRangeStructure", "WhileStructure", "SwitchStructure"},
    "declarations": {
        "TypeDeclaration",
        "EnumDeclaration",
        "FunctionDeclaration",
        "MethodDeclaration",
    },
    "collections": {"GenericInstantiationExpr", "ForInStructure"},
    "expressions": {"ConditionalExpr", "TupleExpr", "HistoryRefExpr", "UnaryExpr"},
    "imports": {"ImportDeclaration"},
}


@pytest.mark.parametrize("name", SOURCES)
def test_parser_semantic_matrix_produces_auditable_artifacts(name: str) -> None:
    result = parse_code(SOURCES[name], ParseOptions(source_name=f"{name}.pine"))
    assert result.ast is not None
    assert result.ast.version_context.pine_version == 6
    assert result.frontend_artifact is not None
    frontend = result.frontend_artifact["frontend"]
    assert isinstance(frontend, Mapping)
    assert frontend["source"]["name"] == f"{name}.pine"
    assert validate_openpine_contract_payload(frontend) == ()

    kinds = {type(node).__name__ for node in iter_nodes(result.ast)}
    assert EXPECTED_KINDS.get(name, {"Program"}) <= kinds


@pytest.mark.parametrize(
    ("name", "required_codes"),
    [
        ("parse_and_semantic_errors", {"P2A0501", "P2A1701", "P2A1801", "P2A1902"}),
        ("duplicates", {"P2A1102"}),
        ("imports", {"P2A2001"}),
        ("generic_errors", {"P2A1404", "P2A1805"}),
        ("members", {"P2A1605"}),
        ("arguments", {"P2A1401", "P2A1404", "P2A2008"}),
        ("loops", {"P2A1112"}),
    ],
)
def test_negative_matrix_fails_closed_with_stable_diagnostics(
    name: str, required_codes: set[str]
) -> None:
    result = parse_code(SOURCES[name])
    actual = {item.code for item in result.diagnostics}
    assert required_codes <= actual
    if name != "loops":
        assert not result.ok


def test_collection_contract_records_declarations_constructors_mutations_and_accesses() -> None:
    result = parse_code(SOURCES["collections"])
    assert result.ok
    collections = result.frontend_artifact["frontend"]["collections"]
    assert len(collections["declarations"]) == 3
    assert len(collections["constructors"]) == 3
    assert len(collections["mutations"]) == 3
    assert len(collections["accesses"]) == 2
    operations = {row["operation"] for row in collections["mutations"]}
    assert {"push", "put", "set"} <= operations


def test_type_method_callable_and_control_flow_contracts_are_concrete() -> None:
    declarations = parse_code(SOURCES["declarations"]).frontend_artifact["frontend"]
    assert len(declarations["types"]["udts"]) == 1
    assert len(declarations["types"]["enums"]) == 1
    assert len(declarations["types"]["constructors"]) == 1
    assert len(declarations["methods"]["declarations"]) == 1
    assert len(declarations["methods"]["calls"]) == 1
    assert len(declarations["callables"]["functions"]) == 1
    assert len(declarations["callables"]["methods"]) == 1

    control = parse_code(SOURCES["control"]).frontend_artifact["frontend"]["control_flow"]
    assert len(control["loops"]) == 2
    assert len(control["conditions"]) == 4


def test_request_and_strategy_sections_classify_calls() -> None:
    request_section = parse_code(SOURCES["requests"]).frontend_artifact["frontend"]["requests"]
    assert {row["kind"] for row in request_section["requests"]} == {
        "request.security",
        "request.security_lower_tf",
        "request.seed",
    }

    strategy = parse_code(SOURCES["strategy"]).frontend_artifact["frontend"]["strategy"]
    assert len(strategy["orders"]) == 2
    assert len(strategy["exits"]) == 1
    assert len(strategy["management"]) == 1
