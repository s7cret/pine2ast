"""Independent library minimum-simple rule, documented for Pine v5 and v6."""

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import CallExpr, FunctionDeclaration
from pine2ast.ast.visitors import walk
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def linked_program(version, body, usage="plot(lib.value())"):
    library = f'//@version={version}\nlibrary("Values")\n{body}\n'
    root = f'//@version={version}\nindicator("Caller")\nimport qa/Values/1 as lib\n{usage}\n'
    return link_libraries(root, LibraryStore.create({"qa/Values/1": library}))


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("origin", ["ordinary", "exported", "linked"])
@pytest.mark.parametrize(
    "body,arguments,actual",
    [
        ("value()=>2", "", "const"),
        ("value(simple int unused)=>2", "2", "const"),
        ("value()=>\n    if true\n        2\n    else\n        3", "", "const"),
        ("value()=>\n    switch 1\n        1=>2\n        =>3", "", "const"),
        ("value()=>bar_index+2", "", "series"),
    ],
)
def test_return_minimum_uses_verified_origin(version, origin, body, arguments, actual):
    call = f"value({arguments})"
    if origin == "linked":
        linked = linked_program(version, "export " + body, f"plot(lib.{call})")
        code = linked.code
        options = ParseOptions(library_context=linked.qualifier_context())
        bundle = build_consumer_bundle(code, linked_source=linked)
        assert bundle["schema_version"] == "1.1.0"
        assert (
            "library_qualifier_context_v1" in bundle["consumer_contract"]["required_capabilities"]
        )
    else:
        declaration = 'library("Values")' if origin == "exported" else 'indicator("Values")'
        code = (
            f"//@version={version}\n{declaration}\n"
            + ("export " if origin == "exported" else "")
            + body
            + f"\nplot({call})\n"
        )
        options = ParseOptions()
        bundle = build_consumer_bundle(code)
        assert bundle["schema_version"] == "1.0.0"
        assert "library_context" not in bundle
    parsed = parse_code(code, options)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    function = next(n for n in parsed.ast.items if isinstance(n, FunctionDeclaration))
    expected = "simple" if origin != "ordinary" and actual == "const" else actual
    assert parsed.semantic_model.symbols[function.name].qualifier == expected
    call_node = next(
        n
        for n in walk(parsed.ast)
        if isinstance(n, CallExpr) and getattr(n.callee, "name", None) == function.name
    )
    assert parsed.semantic_model.node_qualifiers[id(call_node)] == expected
    # Source export flags are never fabricated in a linked indicator AST.
    assert function.is_exported is (origin == "exported")


@pytest.mark.parametrize("version", [5, 6])
def test_ordinary_constant_function_remains_usable_as_const_defval(version):
    code = (
        f'//@version={version}\nindicator("Ordinary")\nvalue()=>2\nx=input.int(value())\nplot(x)\n'
    )
    assert parse_code(code).ok
    assert build_consumer_bundle(code)["schema_version"] == "1.0.0"


@pytest.mark.parametrize("version", [5, 6])
def test_imported_constant_is_not_a_const_defval(version):
    linked = linked_program(version, "export value()=>2", "x=input.int(lib.value())\nplot(x)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "Argument defval " in d.message for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(linked.code, linked_source=linked)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("origin", ["ordinary", "exported", "linked"])
@pytest.mark.parametrize("tail,expected", [("[2,3]", "const"), ("[2,bar_index]", "series")])
def test_tuple_result_floor_preserves_the_strongest_element(version, origin, tail, expected):
    body = "value()=>" + tail
    if origin == "linked":
        linked = linked_program(version, "export " + body, "[a,b]=lib.value()\nplot(a+b)")
        parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
        build_consumer_bundle(linked.code, linked_source=linked)
    else:
        declaration = 'library("Tuple")' if origin == "exported" else 'indicator("Tuple")'
        code = (
            f"//@version={version}\n{declaration}\n"
            + ("export " if origin == "exported" else "")
            + body
            + "\n[a,b]=value()\nplot(a+b)\n"
        )
        parsed = parse_code(code)
        build_consumer_bundle(code)
    assert parsed.ok
    function = next(n for n in parsed.ast.items if isinstance(n, FunctionDeclaration))
    floor = "simple" if origin != "ordinary" and expected == "const" else expected
    assert parsed.semantic_model.symbols[function.name].qualifier == floor


@pytest.mark.parametrize("version", [5, 6])
def test_generated_spelling_alone_never_assigns_exported_origin(version):
    code = f'//@version={version}\nindicator("Spelling")\n__p2a_library_imposter()=>2\nplot(__p2a_library_imposter())\n'
    parsed = parse_code(code)
    assert parsed.ok
    assert parsed.semantic_model.symbols["__p2a_library_imposter"].qualifier == "const"
    assert build_consumer_bundle(code)["schema_version"] == "1.0.0"


@pytest.mark.parametrize("version", [2, 3, 4])
def test_earlier_function_qualifier_contract_is_unchanged(version):
    code = f'//@version={version}\nstudy("Earlier")\nvalue()=>2\nplot(value())\n'
    parsed = parse_code(code)
    assert parsed.ok
    assert parsed.semantic_model.symbols["value"].qualifier is None
    assert build_consumer_bundle(code)["schema_version"] == "1.0.0"
