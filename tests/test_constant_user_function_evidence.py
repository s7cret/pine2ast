"""Manually derived scalar results; no compiler or runtime expected-value oracle."""

from dataclasses import replace

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries
from pine2ast.semantic import constant_functions
from pine2ast.semantic.binder import SemanticFactBuilder


def source(version, declarations, invocation="value()"):
    return f'//@version={version}\nindicator("Constant function")\n{declarations}\nx={invocation}\nplot(x)\n'


def result_fact(parsed):
    return next(
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.kind == "CallExpr" and f.call_form == "USER_FUNCTION" and f.scope_id == "scope:global"
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,invocation,expected",
    [
        ("value()=>3", "value()", 3),
        ("value()=>math.round(2.5)", "value()", 3),
        ("value()=>math.round(precision=-1,number=-25.0)", "value()", -20.0),
        ("value()=>2*3+1", "value()", 7),
        ("value()=>\n    a=2\n    b=a+3\n    b", "value()", 5),
        ("one()=>2\nvalue()=>one()+3", "value()", 5),
        ("value(int n=2)=>3", "value()", 3),
        ("value(int a,int b)=>3", "value(b=1,a=2)", 3),
        ("value()=>true?3:4", "value()", 3),
        ("value()=>math.round(math.min(1.25,2.5),1)", "value()", 1.3),
    ],
)
def test_pure_const_result_has_independent_value(version, declarations, invocation, expected):
    code = source(version, declarations, invocation)
    parsed = parse_code(code)
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]
    fact = result_fact(parsed)
    assert fact.resolved_type.qualifier == "const"
    assert fact.const_value == expected
    assert type(fact.const_value) is type(expected)
    build_consumer_bundle(code)


@pytest.mark.parametrize("version,expected", [(5, 2), (6, 2.5)])
def test_const_function_keeps_exact_integer_division_policy(version, expected):
    parsed = parse_code(source(version, "value()=>5/2"))
    assert parsed.ok
    actual = result_fact(parsed).const_value
    assert actual == expected and type(actual) is type(expected)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,invocation",
    [
        ("value()=>\n    var int a=0\n    3", "value()"),
        ("value()=>\n    a=2\n    a:=3\n    4", "value()"),
        ("value()=>\n    array.new_int(1)\n    3", "value()"),
        ("value()=>\n    a=array.new_int(1)\n    true?3:array.size(a)", "value()"),
        pytest.param(
            "globalValue=bar_index\nvalue()=>globalValue",
            "value()",
            id="globalValue=2\nvalue()=>globalValue-value()",
        ),
        ("value(simple int n)=>n", "value(2)"),
        ("value(series int n)=>n", "value(2)"),
        pytest.param("value(n)=>n+1", "value(bar_index)", id="value(n)=>n+1-value(2)"),
        ("value()=>\n    if true\n        3\n    else\n        4", "value()"),
        ("value()=>-5%2", "value()"),
        ("value()=>int(bool(1))", "value()"),
        ("value(int n=na)=>3", "value()"),
    ],
)
def test_unreviewed_or_impure_body_never_gets_const_value(version, declarations, invocation):
    parsed = parse_code(source(version, declarations, invocation))
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]
    assert result_fact(parsed).const_value is None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("mutation", ["symbol", "overload", "stateful", "form"])
def test_const_user_call_requires_exact_completed_identity(monkeypatch, version, mutation):
    original = SemanticFactBuilder._resolve_calls

    def alter(self, program):
        original(self, program)
        for key, binding in tuple(self._call_bindings.items()):
            if binding.call_form == "USER_FUNCTION":
                kwargs = (
                    {"symbol_id": "user:function:foreign:n99999999"}
                    if mutation == "symbol"
                    else (
                        {"overload_id": "foreign#signature"}
                        if mutation == "overload"
                        else (
                            {"stateful": True}
                            if mutation == "stateful"
                            else {"call_form": "USER_METHOD"}
                        )
                    )
                )
                self._call_bindings[key] = replace(binding, **kwargs)

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter)
    parsed = parse_code(source(version, "value()=>3"))
    calls = [
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.kind == "CallExpr" and f.scope_id == "scope:global" and f.span["start_line"] == 4
    ]
    assert len(calls) == 1 and calls[0].const_value is None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("origin", ["exported", "linked"])
def test_exported_simple_floor_never_receives_constant_value(version, origin):
    library = f'//@version={version}\nlibrary("V")\nexport value()=>3\n'
    if origin == "exported":
        parsed = parse_code(library + "x=value()\nplot(x)\n")
    else:
        caller = (
            f'//@version={version}\nindicator("C")\nimport qa/V/1 as lib\nx=lib.value()\nplot(x)\n'
        )
        linked = link_libraries(caller, LibraryStore.create({"qa/V/1": library}))
        parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
        build_consumer_bundle(linked.code, linked_source=linked)
    assert parsed.ok
    fact = result_fact(parsed)
    assert fact.resolved_type.qualifier == "simple" and fact.const_value is None


@pytest.mark.parametrize("version", [5, 6])
def test_lexical_locals_do_not_borrow_global_or_caller_values(version):
    code = source(version, "n=100\none()=>\n    n=2\n    n\nvalue()=>\n    n=7\n    one()+n")
    parsed = parse_code(code)
    assert parsed.ok
    assert result_fact(parsed).const_value == 9


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "limit,value",
    [
        ("MAX_ROOT_WORK", 8),
        ("MAX_BUILDER_WORK", 8),
        ("MAX_CACHE_ENTRIES", 0),
        ("MAX_FUNCTION_DEPTH", 1),
        ("MAX_EXPRESSION_DEPTH", 1),
    ],
)
def test_shared_resource_limits_produce_unknown_without_partial_value(
    monkeypatch, version, limit, value
):
    monkeypatch.setattr(constant_functions, limit, value)
    observed = []
    original = SemanticFactBuilder.build

    def capture(self, program):
        result = original(self, program)
        observed.append(self._constant_work)
        return result

    monkeypatch.setattr(SemanticFactBuilder, "build", capture)
    parsed = parse_code(source(version, "one()=>2\nvalue()=>one()+3"))
    assert parsed.ok
    assert result_fact(parsed).const_value is None
    assert observed and all(work.spent <= constant_functions.MAX_BUILDER_WORK for work in observed)
    assert all(
        len(work.results) + len(work.purity) <= constant_functions.MAX_CACHE_ENTRIES
        for work in observed
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("mutation", ["missing", "name", "index", "type", "known_value"])
def test_default_evidence_must_match_the_actual_parameter(monkeypatch, version, mutation):
    original = SemanticFactBuilder._resolve_calls

    def alter(self, program):
        original(self, program)
        for key, binding in tuple(self._call_bindings.items()):
            if binding.call_form == "USER_FUNCTION":
                default = binding.defaults_applied[0]
                if mutation == "missing":
                    defaults = ()
                else:
                    changes = {
                        "name": {"parameter_name": "foreign"},
                        "index": {"parameter_index": 1},
                        "type": {"expected_type": None},
                        "known_value": {"default_known": True, "default_value": 99},
                    }
                    defaults = (replace(default, **changes[mutation]),)
                self._call_bindings[key] = replace(binding, defaults_applied=defaults)

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter)
    parsed = parse_code(source(version, "value(int unused=2)=>3"))
    assert result_fact(parsed).const_value is None


@pytest.mark.parametrize("version", [5, 6])
def test_transitive_identity_cycle_cannot_reuse_an_unrelated_literal(monkeypatch, version):
    original = SemanticFactBuilder._resolve_calls

    def alter(self, program):
        original(self, program)
        outer = next(row for row in self._call_bindings.values() if row.callee == "value")
        for key, binding in tuple(self._call_bindings.items()):
            if binding.callee == "one":
                self._call_bindings[key] = replace(
                    binding, symbol_id=outer.symbol_id, overload_id=outer.overload_id
                )

    monkeypatch.setattr(SemanticFactBuilder, "_resolve_calls", alter)
    parsed = parse_code(source(version, "one()=>2\nvalue()=>one()"))
    assert result_fact(parsed).const_value is None


@pytest.mark.parametrize("version", [2, 3, 4])
def test_old_unqualified_function_value_folding_is_unchanged(version):
    parsed = parse_code(
        f'//@version={version}\nstudy("Old")\nvalue()=>3\nx=value()\ny=true?2:value()\nplot(x+y)\n'
    )
    assert parsed.ok
    facts = parsed.semantic_model.semantic_facts.facts
    assert result_fact(parsed).const_value is None
    ternary = next(f for f in facts if f.kind == "ConditionalExpr")
    assert ternary.const_value == 2


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("tail", ["true?3:(-5%2)", "true?3:int(bool(1))"])
def test_unselected_unsupported_expression_is_not_laundered(version, tail):
    parsed = parse_code(source(version, "value()=>" + tail))
    assert parsed.ok
    assert result_fact(parsed).const_value is None


@pytest.mark.parametrize("version", [5, 6])
def test_bool_result_uses_exact_boolean_operations(version):
    code = source(version, "value()=>not false and 3>2").replace("plot(x)", "plot(x?1:0)")
    parsed = parse_code(code)
    assert parsed.ok
    assert result_fact(parsed).const_value is True


@pytest.mark.parametrize("version", [5, 6])
def test_cached_identity_keeps_distinct_tagged_argument_values(monkeypatch, version):
    captured = []
    original = SemanticFactBuilder.build

    def capture(self, program):
        result = original(self, program)
        captured.append(self._constant_work)
        return result

    monkeypatch.setattr(SemanticFactBuilder, "build", capture)
    parsed = parse_code(source(version, "value(float unused)=>3", "value(1)+value(1.0)"))
    assert parsed.ok
    calls = [
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.kind == "CallExpr" and f.call_form == "USER_FUNCTION" and f.scope_id == "scope:global"
    ]
    assert len(calls) == 2 and all(f.const_value == 3 for f in calls)
    assert captured
    arguments = {key[1] for key in captured[-1].results}
    assert (("int", 1),) in arguments and (("float", 1.0),) in arguments


def test_many_nested_operations_share_the_default_root_work_budget():
    # Each earlier pure expression still consumes work; a final literal cannot
    # erase the cost or give each nested operation a fresh root allowance.
    declaration = "value()=>\n" + "    1+1\n" * 900 + "    3"
    parsed = parse_code(source(6, declaration))
    assert parsed.ok
    assert result_fact(parsed).resolved_type.qualifier == "const"
    assert result_fact(parsed).const_value is None
