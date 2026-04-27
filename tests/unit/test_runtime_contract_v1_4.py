from __future__ import annotations

import inspect
import json
from dataclasses import fields, is_dataclass
from pathlib import Path

from pine2ast.api import parse_code
from pine2ast.ast.base import ASTNode
from pine2ast.ast.types import TypeRef
import pine2ast.ast.nodes as nodes
from pine2ast.diagnostics import codes
from pine2ast.runtime_contract import unsupported_features_for_program
from pine2ast.semantic.passes import PASS_PIPELINE

MAPPING_PATH = Path("tests/fixtures/runtime_contract_v1_4/frontend_node_mapping.json")


def _schema_node_kinds() -> dict[str, type[ASTNode]]:
    result: dict[str, type[ASTNode]] = {}
    for name, obj in vars(nodes).items():
        if (
            inspect.isclass(obj)
            and issubclass(obj, ASTNode)
            and obj is not ASTNode
            and obj.__module__ == nodes.__name__
            and name != "ArrayLiteralExpr"
        ):
            result[name] = obj
    result["TypeRef"] = TypeRef
    return result


def test_runtime_contract_mapping_covers_every_ast_node_kind() -> None:
    payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "runtime_contract_v1.4"
    mapped = {item["kind"]: item for item in payload["nodes"]}
    assert mapped.keys() == _schema_node_kinds().keys()

    for kind, cls in _schema_node_kinds().items():
        item = mapped[kind]
        assert isinstance(item["required_fields"], list)
        assert isinstance(item["optional_fields"], list)
        if is_dataclass(cls):
            dataclass_field_names = {field.name for field in fields(cls)} - {"span"}
            mapped_fields = set(item["required_fields"]) | set(item["optional_fields"])
            assert mapped_fields == dataclass_field_names
        if not item["ast2python_lowerable"] or not item["pinelib_runtime_support"]:
            assert item["unsupported_diagnostic_code"] == codes.UNSUPPORTED_FEATURE


def test_mapping_unsupported_feature_catalog_is_consistent() -> None:
    payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    unsupported = {
        item["kind"]: item
        for item in payload["nodes"]
        if not item["ast2python_lowerable"] or not item["pinelib_runtime_support"]
    }
    assert payload["unsupported_features"] == list(unsupported.values())
    assert "ImportDeclaration" in unsupported


def test_imports_have_runtime_contract_unsupported_marker_without_diagnostic_drift() -> None:
    src = """//@version=6
library("L")
import user/lib/1 as lib
"""
    result = parse_code(src)
    assert result.ok
    assert not [diag for diag in result.diagnostics if diag.code == codes.UNSUPPORTED_FEATURE]
    assert result.ast is not None
    unsupported = unsupported_features_for_program(result.ast)
    assert unsupported
    assert unsupported[0]["code"] == codes.UNSUPPORTED_FEATURE
    assert unsupported[0]["severity"] == "WARNING"


def test_semantic_pass_pipeline_names_frontend_contract_phases() -> None:
    assert PASS_PIPELINE == (
        "declaration_index",
        "scope_symbols",
        "type_inference",
        "qualifier_inference",
        "builtin_validation",
        "strategy_context_validation",
        "unsupported_feature_extraction",
    )
