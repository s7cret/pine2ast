from __future__ import annotations

from collections import Counter

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.walk import iter_nodes

FEATURE_LIBRARY = """//@version=6
library("feature matrix")
import alice/mathlib/1 as mathlib

//@description A two-dimensional point.
//@type Point
//@field x Horizontal coordinate.
//@field y Vertical coordinate.
export type Point
    float x = 0.0
    float y = 0.0

//@enum Direction
export enum Direction
    Up "Up"
    Down "Down"

//@function Adds two values.
//@param a First value.
//@param b Second value.
//@returns The sum.
export add(float a, float b = 1.0) =>
    total = a + b
    total

//@function Rescales a point.
//@param factor Scale factor.
export method rescale(Point this, float factor = 1.0) =>
    Point.new(this.x * factor, this.y * factor)

export const float exported_value = 1.0
p = Point.new(1.0, 2.0)
q = p.rescale(2.0)
dir = Direction.Up
var array<float> values = array.new<float>(0)
array.push(values, close)
values.push(open)
first = array.get(values, 0)
var matrix<float> grid = matrix.new<float>(2, 2, 0.0)
matrix.set(grid, 0, 0, 1.0)
cell = matrix.get(grid, 0, 0)
var map<string, float> prices = map.new<string, float>()
map.put(prices, "close", close)
price = map.get(prices, "close")
[macd_line, signal_line, histogram] = ta.macd(close, 12, 26, 9)
past = close[1]
sum = 0.0
for i = 0 to 3 by 1
    sum += i
for value in values
    sum += value
for [index, value] in values
    sum += index + value
while sum < 10
    sum += 1
    if sum == 5
        continue
    if sum > 8
        break
choice = switch dir
    Direction.Up => 1
    Direction.Down => -1
    => 0
flag = switch
    close > open => true
    => false
"""


INVALID_SOURCES = {
    "udt": """//@version=6
library("bad udt")
type Point
    float x
    bool ok = true
method move(Point this, float delta) =>
    Point.new(this.x + delta)
p0 = Point.new()
p1 = Point.new("bad", unknown = 1)
p2 = Point.new(1.0, x = 2.0)
a = p2.unknown()
b = p2.x()
c = p2.move("bad", extra = 1)
""",
    "function": """//@version=6
indicator("bad calls")
f(float x, bool flag = true) => x
a = f()
b = f(1.0, true, 3.0)
c = f("bad")
d = f(1.0, x = 2.0)
e = f(1.0, unknown = 2)
q = ta.sma(close)
r = ta.sma(close, 14, 9)
s = plot(close, unknown = 1)
""",
    "collections": """//@version=6
indicator("bad collections")
var array<float> a = array.new<float>(0)
x = array.get(a)
array.set(a, 0, "bad")
a.push("bad")
var matrix<int> m = matrix.new<int>(2, 2, 0)
matrix.set(m, 0, 0, true)
var map<float, float> bad = map.new<float, float>()
map.put(bad, 1.0, 2.0)
var map<string, int> good = map.new<string, int>()
map.put(good, "x", "bad")
y = good.get()
""",
    "control": """//@version=6
indicator("bad control")
break
continue
x = close[-1]
if 1
    x := 2
for [a, b, c] in array.new<float>(0)
    x := a
for [d, d] in array.new<float>(0)
    x := d
while true
    x += 1
bool flag = na
""",
}


def _codes(source: str) -> set[str]:
    result = parse_code(source, ParseOptions(max_diagnostics=500))
    assert result.ast is not None
    assert result.semantic_model is not None
    return {item.code for item in result.diagnostics}


def test_v6_library_exercises_declarations_collections_and_control_flow() -> None:
    result = parse_code(
        FEATURE_LIBRARY,
        ParseOptions(max_diagnostics=500, collect_tokens=True),
    )
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    assert result.ast is not None
    assert result.frontend_artifact is not None

    kinds = Counter(type(node).__name__ for node in iter_nodes(result.ast))
    for required in (
        "ImportDeclaration",
        "TypeDeclaration",
        "EnumDeclaration",
        "FunctionDeclaration",
        "MethodDeclaration",
        "TupleDeclaration",
        "ForRangeStructure",
        "ForInStructure",
        "WhileStructure",
        "SwitchStructure",
        "BreakStatement",
        "ContinueStatement",
    ):
        assert kinds[required] > 0

    frontend = result.frontend_artifact["frontend"]
    assert len(frontend["types"]["udts"]) == 1
    assert len(frontend["types"]["enums"]) == 1
    assert len(frontend["collections"]["declarations"]) == 3
    assert len(frontend["collections"]["constructors"]) == 3
    assert len(frontend["control_flow"]["loops"]) == 4


def test_qualifier_keywords_are_versioned_and_parseable() -> None:
    v5 = parse_code('//@version=5\nindicator("v5")\nsimple float value = 1.0\n')
    assert v5.ok, [(item.code, item.message) for item in v5.diagnostics]

    v6 = parse_code('//@version=6\nlibrary("v6")\nexport const float value = 1.0\n')
    assert v6.ok, [(item.code, item.message) for item in v6.diagnostics]

    v4_codes = _codes('//@version=4\nstudy("v4")\nconst float value = 1.0\n')
    assert "P2A0501" in v4_codes


def test_invalid_udt_and_method_calls_are_diagnosed() -> None:
    codes = _codes(INVALID_SOURCES["udt"])
    assert {"P2A1401", "P2A1403", "P2A1404", "P2A1406", "P2A1605", "P2A1801"} <= codes


def test_invalid_function_and_builtin_calls_are_diagnosed() -> None:
    codes = _codes(INVALID_SOURCES["function"])
    assert {"P2A1401", "P2A1403", "P2A1404", "P2A1406", "P2A2008"} <= codes


def test_invalid_collection_operations_are_diagnosed() -> None:
    codes = _codes(INVALID_SOURCES["collections"])
    assert {"P2A1404", "P2A1406", "P2A1805", "P2A2008"} <= codes


def test_invalid_loop_history_bool_and_condition_rules_are_diagnosed() -> None:
    codes = _codes(INVALID_SOURCES["control"])
    assert {
        "P2A1102",
        "P2A1112",
        "P2A1201",
        "P2A1203",
        "P2A1305",
        "P2A1701",
        "P2A1902",
    } <= codes
