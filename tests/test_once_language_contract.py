"""August 2026 once syntax is versioned and statement-only, not a var mode."""

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle, ConsumerBundleError


def bundle(body, version=6):
    declaration = "indicator" if version >= 5 else "study"
    return build_consumer_bundle(f'//@version={version}\n{declaration}("once")\n{body}\n')


def errors(b):
    return [
        d for d in b.get("diagnostics", []) if d.get("severity", "").lower() in {"error", "fatal"}
    ]


def nodes(obj):
    if isinstance(obj, dict):
        if "kind" in obj:
            yield obj
        for value in obj.values():
            yield from nodes(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from nodes(value)


@pytest.mark.parametrize("condition", ["", " close>0", " true", " false"])
def test_once_is_a_statement_with_an_explicit_condition(condition):
    b = bundle(f"var int n=0\nonce{condition}\n    n+=1\nplot(n)")
    assert not errors(b), b.get("diagnostics")
    once = [n for n in nodes(b["ast"]) if n["kind"] == "OnceStructure"]
    assert len(once) == 1 and once[0]["condition"]
    assert once[0]["span"]["start_line"] == 4


@pytest.mark.parametrize("version", range(1, 6))
def test_old_versions_can_still_use_once_as_identifier(version):
    b = bundle("once=2\nplot(once)", version)
    assert not errors(b), b.get("diagnostics")
    assert not any(n["kind"] == "OnceStructure" for n in nodes(b["ast"]))


@pytest.mark.parametrize("version", range(1, 6))
def test_once_structure_not_enabled_for_older_versions(version):
    with pytest.raises(ConsumerBundleError, match="production-blocking"):
        bundle("once\n    x=1", version)


@pytest.mark.parametrize(
    "body",
    [
        "x=once\n    1",
        "once 1\n    x=1",
        "once na\n    x=1",
        'once "yes"\n    x=1',
        "once\n    plot(close)",
        "f()=>\n    once\n        x=1\ny=f()",
        'once\n    strategy("local")',
    ],
)
def test_invalid_once_forms_are_rejected(body):
    with pytest.raises(ConsumerBundleError, match="production-blocking"):
        bundle(body)


@pytest.mark.parametrize(
    "body",
    [
        "for i=0 to 2\n    once i==1\n        x=1",
        "f()=>\n    var int n=0\n    once\n        n+=1\n    n\nx=f()",
        "if true\n    once\n        x=1",
        "once\n    once\n        x=1",
    ],
)
def test_nested_loop_and_function_contexts_have_real_ast_nodes(body):
    b = bundle(body)
    assert not errors(b), b.get("diagnostics")
    assert any(n["kind"] == "OnceStructure" for n in nodes(b["ast"]))
