"""A same-spelled local declaration never changes a different global binding."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations",
    [
        "BASE=2\nother()=>\n    BASE=3\n    BASE:=4\n    BASE\nvalue()=>BASE",
        "BASE=2\nif true\n    BASE=3\n    BASE:=4\nvalue()=>BASE",
    ],
)
def test_reassignment_to_distinct_local_binding_does_not_poison_global_constant(
    version, declarations
):
    code = f'//@version={version}\nindicator("Bindings")\n{declarations}\nx=input.int(value())\nplot(x)\n'
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    fact = next(
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.kind == "CallExpr" and f.call_form == "USER_FUNCTION" and f.scope_id == "scope:global"
    )
    assert fact.resolved_type.qualifier == "const" and fact.const_value == 2
    build_consumer_bundle(code)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations",
    [
        "BASE=2\nBASE:=3\nvalue()=>BASE",
        "BASE=2\nvalue()=>BASE\nBASE:=3",
        "BASE=2\nif true\n    BASE:=3\nvalue()=>BASE",
        "BASE=2\nvalue()=>BASE\nif true\n    BASE:=3",
    ],
)
def test_actual_global_reassignment_before_or_after_definition_cannot_be_laundered(
    version, declarations
):
    code = f'//@version={version}\nindicator("Mutable global")\n{declarations}\nx=input.int(value())\nplot(x)\n'
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(code)
