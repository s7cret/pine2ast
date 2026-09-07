"""Explicit map/matrix export profile; old scalar/array identities stay stable."""

import pytest
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from pine2ast.hardening.consumer_bundle import build_consumer_bundle


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "kind,typeargs,make,body",
    [
        (
            "map",
            "string,int",
            "map.new<string,int>()",
            'map.put(m,"x",2)\n    result=0\n    for [k,v] in m\n        result+=v\n    result',
        ),
        (
            "matrix",
            "int",
            "matrix.new<int>(2,1,3)",
            "result=0\n    for row in m\n        result+=array.get(row,0)\n    result",
        ),
    ],
)
def test_typed_exports_link_with_new_profile(version, kind, typeargs, make, body):
    lib = f'//@version={version}\nlibrary("Lib")\nexport f({kind}<{typeargs}> m)=>\n    {body}\n'
    script = f'//@version={version}\nindicator("profile")\nimport u/Lib/1 as lib\nm={make}\nplot(lib.f(m))\n'
    out = link_libraries(script, LibraryStore.create({"u/Lib/1": lib}))
    assert out.receipt()["profile"] == "same_version_collections_v3"
    out.verify()
    assert build_consumer_bundle(out.code)


@pytest.mark.parametrize(
    "dtype",
    ["simple map<string,int>", "matrix<line>", "map<string,array<int>>", "map<array<int>,int>"],
)
def test_unsupported_element_or_reference_qualifier_not_admitted(dtype):
    lib = f'//@version=6\nlibrary("Lib")\nexport f({dtype} m)=>1\n'
    with pytest.raises(LibraryError):
        link_libraries(
            '//@version=6\nindicator("bad")\nimport u/Lib/1 as lib\nplot(1)\n',
            LibraryStore.create({"u/Lib/1": lib}),
        )


def test_later_array_dependency_does_not_downgrade_collection_profile():
    source = '//@version=6\nindicator("profile")\nimport u/Lib/1 as lib\nm=matrix.new<int>(1,1,2)\nplot(lib.f(m))\n'
    lib = '//@version=6\nlibrary("Lib")\nexport f(matrix<int> m)=>\n    a=array.new<int>(1,2)\n    matrix.get(m,0,0)+array.get(a,0)\n'
    out = link_libraries(source, LibraryStore.create({"u/Lib/1": lib}))
    assert out.receipt()["profile"] == "same_version_collections_v3"
    out.verify()
