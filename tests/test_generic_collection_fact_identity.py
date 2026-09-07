"""Exact generic call identity also describes its syntactic callee base."""

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle, ConsumerBundleError
from pine2ast.hardening.introspection import parse_source, semantic_facts_payload
from pine2ast.semantic.type_helpers import for_in_target_types

CONSTRUCTORS = ("array.new<int>(1,0)", "map.new<string,int>()", "matrix.new<float>(1,1,0.0)")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("constructor", CONSTRUCTORS)
def test_generic_call_and_base_have_the_same_resolved_identity(version, constructor):
    source = f'//@version={version}\nindicator("generic")\nx={constructor}\n'
    bundle = build_consumer_bundle(source)
    facts = semantic_facts_payload(parse_source(source))
    call = next(
        row for row in facts["calls"] if row["callee"].startswith(constructor.split("<")[0])
    )
    matching = [row for row in facts["facts"] if row["symbol_id"] == call["symbol_id"]]
    assert {row["kind"] for row in matching} >= {
        "CallExpr",
        "GenericInstantiationExpr",
        "MemberAccessExpr",
    }
    assert all(row["resolved_type"]["base"] != "unknown" for row in matching)
    assert bundle["content_hash"]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("constructor", CONSTRUCTORS[1:])
def test_generic_fact_fix_does_not_enable_new_collections_in_old_versions(version, constructor):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(f'//@version={version}\nstudy("negative")\nx={constructor}\n')


@pytest.mark.parametrize(
    "constructor",
    [
        "map.new<int>()",
        "matrix.new<int,float>(1,1,0)",
        "map.new<string,int>(1)",
        'matrix.new<int>(1,1,"bad")',
    ],
)
def test_bad_types_and_arity_are_not_hidden_by_callee_identity(constructor):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle('//@version=6\nindicator("bad")\nx=' + constructor + "\n")


@pytest.mark.parametrize("count", [1, 2])
def test_matrix_for_in_produces_array_type_not_scalar(count):
    expected = ["array<float>"] if count == 1 else ["int", "array<float>"]
    assert for_in_target_types("matrix<float>", count) == expected
    target = "row" if count == 1 else "[i,row]"
    source = f'//@version=6\nindicator("rows")\nm=matrix.new<float>(2,2,3.0)\ns=0.0\nfor {target} in m\n    for value in row\n        s+=value\nplot(s)\n'
    assert build_consumer_bundle(source)["content_hash"]


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "args,expected",
    [("1,0", "int"), ("na,0", "int"), ("1,0.0", "float"), ("replacement=0,source=1", "int")],
)
def test_nz_result_follows_the_selected_numeric_overload(version, args, expected):
    declaration = "indicator" if version >= 5 else "study"
    if version <= 4:
        # The v5 migration renamed nz(x, y) to nz(source, replacement).
        args = args.replace("source=", "x=").replace("replacement=", "y=")
    source = f'//@version={version}\n{declaration}("nz")\nx=nz({args})\n'
    call = next(
        c for c in semantic_facts_payload(parse_source(source))["calls"] if c["callee"] == "nz"
    )
    assert call["return_type"] == expected
    assert build_consumer_bundle(source)["content_hash"]


@pytest.mark.parametrize("args", ['"x","y"', "true,0", "true,false"])
def test_nz_does_not_accept_arbitrary_any_or_boolean_v6(args):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(f'//@version=6\nindicator("bad")\nx=nz({args})\n')
