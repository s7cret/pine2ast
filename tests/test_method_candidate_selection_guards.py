"""Independent collection, identity, ambiguity and bounded-work controls."""

import pytest

from pine2ast import parse_code
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.semantic import method_candidates


def source(version, body):
    return f'//@version={version}\nindicator("Method controls")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body,expected",
    [
        (
            'method sort(array<int> self,int order,string sort_field)=>order\na=array.new<int>(1,2)\nplot(a.sort(7,"custom"))',
            "int",
        ),
        (
            'method sort(array<int> self,int order,string sort_field)=>order\na=array.new<int>(1,2)\nplot(a.sort(sort_field="custom",order=7))',
            "int",
        ),
        (
            'method set(array<int> self,string text)=>str.length(text)\na=array.new<int>(1,2)\nplot(a.set("abcd"))',
            "int",
        ),
        (
            "method choose(int self,simple int n)=>n\nmethod choose(int self,series int n)=>n\na=1\nplot(a.choose(bar_index))",
            "int",
        ),
        (
            'method choose(int self,int n)=>n\nmethod choose(int self,string n)=>str.length(n)\na=1\nplot(a.choose("abcd"))',
            "int",
        ),
        (
            "method choose(int self,int n,float extra=0.5)=>n+extra\nmethod choose(int self,string text)=>str.length(text)\na=1\nplot(a.choose(n=4))",
            "float",
        ),
    ],
    ids=[
        "user_sort",
        "named_user_sort",
        "user_set",
        "series_qualified_selection",
        "string_overload",
        "selected_optional",
    ],
)
def test_method_selection_routes_existing_collection_validation(version, body, expected):
    code = source(version, body)
    result = parse_code(code)
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    calls = [
        c
        for c in build_consumer_bundle(code)["semantic_facts"]["calls"]
        if c["call_form"] == "USER_METHOD"
    ]
    assert len(calls) == 1
    assert calls[0]["return_type"] == expected
    assert calls[0]["resolution_status"] == "RESOLVED"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body,diagnostic",
    [
        (
            "method get(array<int> self,int index)=>index\na=array.new<int>(1,2)\nplot(a.get(0))",
            codes.AMBIGUOUS_OVERLOAD,
        ),
        (
            "method choose(int self,simple int n)=>n\nmethod choose(int self,series int n)=>n\na=1\nplot(a.choose(2))",
            codes.AMBIGUOUS_OVERLOAD,
        ),
        (
            "method choose(int self,int n)=>n\nmethod choose(int self,int other)=>other\na=1\nplot(a.choose(2))",
            codes.REDECLARATION,
        ),
        (
            'method choose(int self,int n,float extra=0.5)=>n+extra\nmethod choose(int self,int n,string text="x")=>n\na=1\nplot(a.choose(2))',
            codes.REDECLARATION,
        ),
        (
            "method choose(int self,int n)=>n\nmethod choose(int self,float n)=>n\na=1\nplot(a.choose(n=2,n=3))",
            codes.INVALID_OVERLOAD_BINDING,
        ),
    ],
    ids=[
        "builtin_user_tie",
        "qualifier_tie_unknown_priority",
        "parameter_names_not_signature",
        "optional_only_not_signature",
        "duplicate_named",
    ],
)
def test_distinct_candidates_reject_ambiguity_and_invalid_declarations(version, body, diagnostic):
    result = parse_code(source(version, body))
    assert not result.ok
    assert diagnostic in {d.code for d in result.diagnostics}


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("reverse", [False, True])
def test_selection_is_not_declaration_order(version, reverse):
    declarations = ["method choose(int self,int n)=>n+1", "method choose(int self,float n)=>n+0.5"]
    if reverse:
        declarations.reverse()
    code = source(version, "\n".join(declarations) + "\na=1\nplot(a.choose(2))")
    parsed = parse_code(code)
    assert parsed.ok
    owner = parsed.semantic_model.method_candidates
    assert len(owner.by_node) == 2
    assert len(owner.by_symbol) == 2
    assert {c.declaration_id for c in owner.candidates} == {
        owner.index.id_for(c.declaration) for c in owner.candidates
    }
    with pytest.raises(TypeError):
        owner.by_symbol["forged"] = owner.candidates[0]
    call = next(
        c
        for c in build_consumer_bundle(code)["semantic_facts"]["calls"]
        if c["call_form"] == "USER_METHOD"
    )
    assert call["return_type"] == "int"
    assert call["arguments"][0]["expected_type"] == "int"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("limit", ["MAX_METHOD_WORK", "MAX_METHOD_CACHE"])
def test_method_candidate_limits_fail_with_controlled_diagnostics(version, limit, monkeypatch):
    monkeypatch.setattr(method_candidates, limit, 0)
    parsed = parse_code(source(version, "method choose(int self,int n)=>n\na=1\nplot(a.choose(2))"))
    assert not parsed.ok
    assert any(
        d.code == codes.UNSUPPORTED_FEATURE and "Method candidate inference work limit" in d.message
        for d in parsed.diagnostics
    )


@pytest.mark.parametrize("version", [5, 6])
def test_failed_candidates_are_charged_before_selection(version, monkeypatch):
    # Every one of these distinct required types fails a bool source argument.
    monkeypatch.setattr(method_candidates, "MAX_METHOD_WORK", 5)
    parsed = parse_code(
        source(
            version,
            "method choose(int self,int n)=>n\nmethod choose(int self,float n)=>n\nmethod choose(int self,string n)=>str.length(n)\na=1\nplot(a.choose(true))",
        )
    )
    assert not parsed.ok
    owner = parsed.semantic_model.method_candidates
    assert owner.spent > 5
    assert any(
        d.code == codes.UNSUPPORTED_FEATURE and "Method candidate inference work limit" in d.message
        for d in parsed.diagnostics
    )
