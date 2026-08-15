from __future__ import annotations

from pathlib import Path
from typing import Any

from pine2ast._version import __version__
from pine2ast.api import ParseOptions, ParseResult, parse_file
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.openpine_contracts.callables import extract_callable_contract
from pine2ast.openpine_contracts.collections import extract_collection_contract
from pine2ast.openpine_contracts.control_flow import extract_control_flow_contract
from pine2ast.openpine_contracts.requests import extract_request_contract
from pine2ast.openpine_contracts.schema import (
    FRONTEND_CONTRACT,
    FRONTEND_SCHEMA_CONTRACT,
    SECTION_CONTRACTS,
)
from pine2ast.openpine_contracts.strategy import extract_strategy_contract
from pine2ast.openpine_contracts.types import extract_type_contract
from pine2ast.openpine_contracts.validation import extract_validation_contract
from pine2ast.semantic.facts import extract_method_contract


def build_openpine_contract_payload(
    result: ParseResult,
    *,
    source_path: str | Path = "<memory>",
    source_name: str | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    path = Path(source_path)
    program = result.ast
    actual_profile = profile or pine_language_profile(
        (program.version if program else None) or 6,
    )
    return {
        "schema_version": 1,
        "contract": FRONTEND_CONTRACT,
        "schema_contract": FRONTEND_SCHEMA_CONTRACT,
        "contracts": {
            "frontend": FRONTEND_CONTRACT,
            "schema": FRONTEND_SCHEMA_CONTRACT,
            "sections": dict(SECTION_CONTRACTS),
        },
        "producer": {"name": "pine2ast", "version": __version__},
        "source": {"path": str(source_path), "name": source_name or path.name},
        "ok": result.ok,
        "diagnostics": [d.to_dict() for d in result.diagnostics],
        "static_validation": (
            extract_validation_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "requests": (
            extract_request_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "strategy": (
            extract_strategy_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "types": (
            extract_type_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "methods": (
            extract_method_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "collections": (
            extract_collection_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "callables": (
            extract_callable_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
        "control_flow": (
            extract_control_flow_contract(
                program, semantic_model=result.semantic_model, profile=actual_profile
            )
            if program
            else None
        ),
    }


def openpine_contract_file_payload(
    path: str | Path,
    options: ParseOptions | None = None,
) -> dict[str, Any]:
    result = parse_file(str(path), options or ParseOptions(source_name=str(path)))
    return build_openpine_contract_payload(
        result, source_path=str(path), source_name=Path(path).name
    )
