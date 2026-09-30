"""Retained PR18 structural-proof counterexamples; not an import-admission oracle.

Port of the reviewed six-method unittest patch: each former subtest is an
ordinary pytest item. These exercise the uncalled structural-proof utility,
not real library admission or v6-to-v5 conversion.
"""

import pytest

from pine2ast.libraries import version_compatibility as m


def lib(body, version=5):
    return f'//@version={version}\nlibrary("Invariant")\n' + body + "\n"


@pytest.mark.parametrize("v", (5, 6), ids=("v5", "v6"))
@pytest.mark.parametrize(
    "expr",
    ("x + 1", "x - 1", "x * 3", "x % 2", "-x", "+x", "42"),
    ids=("add", "subtract", "multiply", "modulo", "unary-minus", "unary-plus", "literal"),
)
def test_versions_and_exact_bytes(v, expr):
    source = lib("export f(int x) => " + expr, v)
    proof = m.prove_version_invariant_library(source)
    assert proof["source_pine_version"] == v
    assert proof["compatible_consumer_versions"] == [5, 6]
    m.verify_version_invariant_proof(source, proof)
    with pytest.raises(m.VersionSensitiveLibrary):
        m.verify_version_invariant_proof(source + "\n", proof)


def test_local_acyclic_calls():
    source = lib("helper(float x) => x * 2.0\nexport f(float x) => helper(x) + 1.0")
    proof = m.prove_version_invariant_library(source)
    assert proof["functions"]["f"]["calls"] == ["helper"]
    assert proof["functions"]["f"]["return_type"] == "float"


def test_string_comment_scanning():
    proof = m.prove_version_invariant_library(
        lib('export f(string x) => x + "http://example" // comment')
    )
    assert proof["functions"]["f"]["return_type"] == "string"


@pytest.mark.parametrize(
    "body",
    (
        "export f() => 5 / 2",
        "export f() => na",
        "export f() => close",
        "export f() => true",
        "export f(int x) => x > 0",
        "export f(int x) => x[1]",
        "export f(int x) => x if x else 0",
        "export f(int x) => abs(x)",
        "export f(int x = 1) => x",
        "export f(int x) => f(x)",
        "var int n = 0\nexport f() => 1",
        "export f(int x) =>\n    x + 1",
        "import user/Other/1 as other\nexport f() => other.f()",
        "export f(int x) => x\nexport f(float x) => x",
        "export f() => 1e999",
        "export f() => None",
        "export f(bool x) => x",
        'export f() => __import__("os")',
    ),
    ids=(
        "division",
        "na",
        "global-close",
        "true-name",
        "comparison",
        "history",
        "conditional",
        "builtin-abs",
        "default-parameter",
        "recursive-call",
        "persistent-state",
        "multiline",
        "external-import",
        "overloads",
        "nonfinite-literal",
        "none-literal",
        "bool-parameter",
        "python-import",
    ),
)
def test_sensitive_constructs_are_never_converted(body):
    with pytest.raises(m.VersionSensitiveLibrary):
        m.prove_version_invariant_library(lib(body))


def test_rehashed_forgery_is_rejected():
    source = lib("export f(int x) => x + 1")
    proof = m.prove_version_invariant_library(source)
    proof["compatible_consumer_versions"] = [4, 5, 6]
    proof.pop("content_hash")
    proof["content_hash"] = m._canonical(proof)
    with pytest.raises(m.VersionSensitiveLibrary):
        m.verify_version_invariant_proof(source, proof)


@pytest.mark.parametrize(
    "source",
    (
        lib("export f() => 1", 4),
        lib("export f() => 1") + "//@version=6\n",
        'library("X")\nexport f() => 1\n',
    ),
    ids=("v4", "duplicate-directive", "missing-directive"),
)
def test_wrong_versions_and_directives(source):
    with pytest.raises(m.VersionSensitiveLibrary):
        m.prove_version_invariant_library(source)
