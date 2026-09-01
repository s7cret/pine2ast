from __future__ import annotations

from pathlib import Path
from typing import Any

from pine2ast._version import __version__
from pine2ast.api import ParseOptions, ParseResult, parse_file
from pine2ast.versioning import PineVersionContext
from pine2ast.frontend.callables import extract_callable_contract
from pine2ast.frontend.collections import extract_collection_contract
from pine2ast.frontend.control_flow import extract_control_flow_contract
from pine2ast.frontend.ids import FRONTEND_CONTRACT, SECTION_CONTRACTS
from pine2ast.frontend.requests import extract_request_contract
from pine2ast.frontend.strategy import extract_strategy_contract
from pine2ast.frontend.types import extract_type_contract
from pine2ast.frontend.validation import extract_validation_contract
from pine2ast.semantic.facts import extract_method_contract


def build_frontend_contract_payload(
    result: ParseResult,
    *,
    source_path: str | Path = "<memory>",
    source_name: str | None = None,
    profile: PineVersionContext | None = None,
) -> dict[str, Any]:
    path = Path(source_path)
    program = result.ast
    actual_profile = profile or (program.version_context if program else None)
    return {
        "schema_version": 1,
        "contract": FRONTEND_CONTRACT,
        "contracts": {
            "frontend": FRONTEND_CONTRACT,
            "sections": dict(SECTION_CONTRACTS),
        },
        "producer": {"name": "pine2ast", "version": __version__},
        "version_context": program.version_context.to_dict() if program else None,
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


def frontend_contract_file_payload(
    path: str | Path,
    options: ParseOptions | None = None,
) -> dict[str, Any]:
    result = parse_file(str(path), options or ParseOptions(source_name=str(path)))
    return build_frontend_contract_payload(
        result, source_path=str(path), source_name=Path(path).name
    )


__all__ = [
    "build_frontend_contract_payload",
    "frontend_contract_file_payload",
]
