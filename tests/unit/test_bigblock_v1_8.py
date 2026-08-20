from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes


def _codes(src: str):
    res = parse_code(src, ParseOptions(source_name="v18.pine"))
    return res, [d.code for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]


def test_builtin_duplicate_positional_and_named_parameter_is_diagnosed():
    res, errors = _codes("""//@version=6
indicator("Duplicate builtin param")
x = ta.linreg(close, 20, source = open)
plot(close)
""")
    assert codes.DUPLICATE_NAMED_ARGUMENT in errors


def test_user_function_duplicate_positional_and_named_parameter_is_diagnosed():
    res, errors = _codes("""//@version=6
indicator("Duplicate user param")
f(float source, int len) => source + len
x = f(close, source = open, len = 10)
plot(close)
""")
    assert codes.DUPLICATE_NAMED_ARGUMENT in errors


def test_array_from_and_get_infer_element_type():
    res, errors = _codes("""//@version=6
indicator("Array element inference")
values = array.from(1.0, 2.0, 3.0)
first = array.get(values, 0)
secondVal = values.get(1)
plot(first + secondVal)
""")
    assert codes.SYNTAX_ERROR not in errors
    assert res.semantic_model.symbols["values"].type == "array<float>"
    assert res.semantic_model.symbols["first"].type == "float"
    assert res.semantic_model.symbols["secondVal"].type == "float"


def test_for_in_array_tuple_target_infers_index_and_item_types():
    res, errors = _codes("""//@version=6
indicator("For in typed array")
values = array.from(1.0, 2.0, 3.0)
sum = 0.0
for [i, item] in values
    sum += item + i
plot(sum)
""")
    assert codes.SYNTAX_ERROR not in errors
    assert res.semantic_model.symbols["i"].type == "int"
    assert res.semantic_model.symbols["item"].type == "float"


def test_map_for_in_tuple_target_infers_key_value_types_from_annotation():
    res, errors = _codes("""//@version=6
indicator("For in typed map")
map<string, float> weights = map.new<string,float>()
for [key, value] in weights
    label.new(bar_index, value, key)
plot(close)
""")
    assert codes.SYNTAX_ERROR not in errors
    assert res.semantic_model.symbols["key"].type == "string"
    assert res.semantic_model.symbols["value"].type == "float"


def test_collection_method_result_type_can_validate_user_function_arg():
    res, errors = _codes("""//@version=6
indicator("Collection method contract")
f(float x) => x
values = array.from(1.0, 2.0)
ok = f(values.first())
bad = f("x")
plot(ok)
""")
    assert codes.ARGUMENT_TYPE in errors
    assert res.semantic_model.symbols["ok"].type == "float"
