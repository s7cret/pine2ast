"""Stage 2.4 producer gates for typed collection/reference lifecycle."""
import pytest

from pine2ast.hardening.consumer_bundle import build_consumer_bundle, ConsumerBundleError


def source(body: str, version: int = 6) -> str:
    decl = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{decl}("stage24")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "expression",
    [
        "array.new<array<int>>()",
        "map.new<string,array<int>>()",
        "matrix.new<map<string,int>>()",
    ],
)
def test_generic_constructors_reject_direct_nested_collection_ids(version, expression):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source("x=" + expression, version))


@pytest.mark.parametrize(
    "declaration",
    [
        "array<array<int>> x=na",
        "map<string,array<int>> x=na",
        "matrix<map<string,int>> x=na",
    ],
)
def test_explicit_collection_types_reject_direct_nested_collections(declaration):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(declaration))


@pytest.mark.parametrize(
    "body",
    [
        'a=array.new<int>()\narray.push(a,"x")',
        'm=map.new<string,int>()\nmap.put(m,1,2)',
        'm=map.new<string,int>()\nmap.put(m,"x","bad")',
        'm=matrix.new<int>(1,1,0)\nmatrix.set(m,0,0,"bad")',
    ],
)
def test_collection_mutations_reject_wrong_element_key_or_value_types(body):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(body))


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("expression", ["map.new<string,int>()", "matrix.new<int>()"])
def test_map_and_matrix_remain_unavailable_before_v5(version, expression):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source("x=" + expression, version))


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "a=array.new<int>(1,1)\nf(array<int> x)=>x\nb=f(a)\narray.set(b,0,2)",
        'm=map.new<string,int>()\nf(map<string,int> x)=>x\nn=f(m)\nmap.put(n,"x",2)',
        "m=matrix.new<int>(1,1,1)\nf(matrix<int> x)=>x\nn=f(m)\nmatrix.set(n,0,0,2)",
    ],
)
def test_reference_parameters_and_returns_are_admitted_for_v5_v6(version, body):
    assert build_consumer_bundle(source(body, version))["content_hash"]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "a=array.new<int>(1,1)\np=a[1]",
        'm=map.new<string,int>()\np=m[1]',
        "m=matrix.new<int>(1,1,1)\np=m[1]",
    ],
)
def test_collection_reference_history_is_admitted_in_v5_v6(version, body):
    assert build_consumer_bundle(source(body, version))["content_hash"]

@pytest.mark.parametrize(
    "expression",
    ["array.new<bool>(1, na)", "matrix.new<bool>(1,1, na)"],
)
def test_v6_bool_collections_reject_explicit_na_initial(expression):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source("x=" + expression, 6))


@pytest.mark.parametrize(
    "expression",
    ["array.new<bool>(1, na)", "matrix.new<bool>(1,1, na)"],
)
def test_v5_bool_collections_keep_legacy_explicit_na_initial(expression):
    assert build_consumer_bundle(source("x=" + expression, 5))["content_hash"]
