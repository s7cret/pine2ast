"""Per-occurrence lexical symbol identities are source-only static facts.

The v1/v2 forward-reference assertions come from the documented migration policy;
this module intentionally makes no runtime-value assertion for legacy `n`.
"""

from __future__ import annotations

import pytest

from pine2ast import parse_code
from pine2ast.diagnostics import codes


def script(version: int, body: str) -> str:
    declaration = "study" if version <= 4 else "indicator"
    return f'//@version={version}\n{declaration}("lexical ids")\n{body}\n'


def facts_for(version: int, body: str):
    result = parse_code(script(version, body))
    assert result.semantic_model is not None
    assert result.semantic_model.semantic_facts is not None
    return result, result.semantic_model.semantic_facts.artifact


def rows_at(facts: dict, line: int) -> list[dict]:
    return [
        row
        for row in facts["facts"]
        if row["kind"] == "Identifier" and row["span"]["start_line"] == line
    ]


def row_at(facts: dict, line: int, col: int) -> dict:
    return next(row for row in rows_at(facts, line) if row["span"]["start_col"] == col)


def declaration_id(facts: dict, kind: str, name: str) -> str:
    row = next(
        row for row in facts["facts"] if row["kind"] == kind and row["declaration_target"] == name
    )
    assert isinstance(row["symbol_id"], str)
    return row["symbol_id"]


@pytest.mark.parametrize("version", range(1, 7))
def test_declared_user_n_beats_catalog_at_its_later_occurrence(version: int) -> None:
    result, facts = facts_for(version, "n=input(7)\nplot(n)")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    declared = declaration_id(facts, "VarDeclaration", "n")
    assert row_at(facts, 4, 6)["symbol_id"] == declared
    assert declared.startswith("user:vardeclaration:n:n")
    assert "lexical_binding_ids_v1" in facts["capabilities"]


@pytest.mark.parametrize("version", range(1, 7))
def test_builtin_identity_is_preserved_without_a_user_declaration(version: int) -> None:
    result, facts = facts_for(version, "plot(close)")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    assert row_at(facts, 3, 6)["symbol_id"] == "pine:variable:close"


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_global_forward_reference_binds_to_its_declaration(version: int) -> None:
    result, facts = facts_for(version, "plot(n)\nn=input(7)\nplot(n)")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    declared = declaration_id(facts, "VarDeclaration", "n")
    # This is an identity assertion only; historical runtime values are unproven.
    assert row_at(facts, 3, 6)["symbol_id"] == declared
    assert row_at(facts, 5, 6)["symbol_id"] == declared


@pytest.mark.parametrize("version", [3])
def test_v3_builtin_before_later_shadow_remains_builtin(version: int) -> None:
    result, facts = facts_for(version, "plot(n)\nn=input(7)\nplot(n)")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    declared = declaration_id(facts, "VarDeclaration", "n")
    assert row_at(facts, 3, 6)["symbol_id"] == "pine:variable:bar_index"
    assert row_at(facts, 5, 6)["symbol_id"] == declared


@pytest.mark.parametrize("version", range(4, 7))
def test_modern_forward_use_is_not_retroactively_bound_to_a_later_declaration(version: int) -> None:
    result, facts = facts_for(version, "plot(n)\nn=input(7)\nplot(n)")
    assert any(item.code == codes.UNDECLARED_VARIABLE for item in result.diagnostics)
    assert row_at(facts, 3, 6)["symbol_id"] is None
    assert row_at(facts, 5, 6)["symbol_id"] == declaration_id(facts, "VarDeclaration", "n")


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_forward_chain_binds_each_identifier_to_its_own_declaration(version: int) -> None:
    result, facts = facts_for(version, "plot(a+b)\na=b\nb=input(7)")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    assert row_at(facts, 3, 6)["symbol_id"] == declaration_id(facts, "VarDeclaration", "a")
    assert row_at(facts, 3, 8)["symbol_id"] == declaration_id(facts, "VarDeclaration", "b")
    assert row_at(facts, 4, 3)["symbol_id"] == declaration_id(facts, "VarDeclaration", "b")


@pytest.mark.parametrize("version", range(2, 7))
def test_parameter_and_global_shadowing_bind_each_occurrence_to_its_declaration(
    version: int,
) -> None:
    result, facts = facts_for(version, "n=input(7)\nf(n)=>n+1\nplot(f(n))")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    global_n = declaration_id(facts, "VarDeclaration", "n")
    parameter_n = declaration_id(facts, "Parameter", "n")
    assert parameter_n != global_n
    assert row_at(facts, 4, 7)["symbol_id"] == parameter_n
    assert row_at(facts, 5, 8)["symbol_id"] == global_n


@pytest.mark.parametrize("version", range(3, 7))
def test_block_shadow_and_tuple_targets_keep_exact_declaration_ids(version: int) -> None:
    source = "n=input(7)\nif true\n    n=2\n    x=n\nf()=>[1,2]\n[a,b]=f()\nplot(n+a+b)"
    result, facts = facts_for(version, source)
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    n_declarations = [
        row["symbol_id"]
        for row in facts["facts"]
        if row["kind"] == "VarDeclaration" and row["declaration_target"] == "n"
    ]
    assert len(n_declarations) == 2
    assert row_at(facts, 6, 7)["symbol_id"] == n_declarations[1]
    assert row_at(facts, 9, 6)["symbol_id"] == n_declarations[0]
    a_declared = declaration_id(facts, "TupleTarget", "a")
    b_declared = declaration_id(facts, "TupleTarget", "b")
    assert row_at(facts, 9, 8)["symbol_id"] == a_declared
    assert row_at(facts, 9, 10)["symbol_id"] == b_declared


@pytest.mark.parametrize("version", range(2, 7))
def test_for_range_binder_has_a_deterministic_owner_identity(version: int) -> None:
    result, facts = facts_for(version, "n=0\nfor i=0 to 1\n    n=i\nplot(n)")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    owner = next(row for row in facts["facts"] if row["kind"] == "ForRangeStructure")
    assert row_at(facts, 5, 7)["symbol_id"] == (
        f"user:forrangestructure:i:{owner['node_id']}:role:iterator"
    )
    assert "implicit_lexical_binder_ids_v1" in facts["capabilities"]


@pytest.mark.parametrize("version", [5, 6])
def test_for_in_binder_and_method_receiver_have_deterministic_owner_identities(
    version: int,
) -> None:
    source = """xs=array.from(1,2)
for value in xs
    n=value
type Point
    float x
method get(Point self)=>self.x
p=Point.new(1)
plot(p.get())"""
    result, facts = facts_for(version, source)
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    for_in = next(row for row in facts["facts"] if row["kind"] == "ForInStructure")
    method = next(row for row in facts["facts"] if row["kind"] == "MethodDeclaration")
    assert row_at(facts, 5, 7)["symbol_id"] == (
        f"user:forinstructure:value:{for_in['node_id']}:role:target"
    )
    assert row_at(facts, 8, 25)["symbol_id"] == (
        f"user:methodreceiver:self:{method['node_id']}:role:receiver"
    )
