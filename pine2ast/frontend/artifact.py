"""Catalog-valid ``openpine.frontend.v2`` / support-profile artifacts."""

from __future__ import annotations

import os
import time
from typing import Any, Mapping

from openpine_contracts import (
    SemanticProfile,
    content_hash,
    validate_payload,
)
from openpine_contracts.hashing import CONTENT_HASH_ALG, SERIALIZER_ID

from pine2ast._version import __version__
from pine2ast.api import ParseResult
from pine2ast.frontend.ids import (
    CATALOG_SCHEMA_VERSION,
    FRONTEND_CONTRACT,
    SECTION_CONTRACTS,
    STACK_ID,
    SUPPORT_PROFILE_CONTRACT,
)
from pine2ast.frontend.payload import build_openpine_contract_payload
from pine2ast.inspect_contract import input_dict
from pine2ast.semantic.extractors import extract_inputs, extract_request_calls
from pine2ast.semantic.type_infer import callee_name


def _producer_commit() -> str:
    commit = os.environ.get("OPENPINE_PRODUCER_COMMIT", "").strip()
    return commit or "unknown"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _seal(schema_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("content_hash", None)
    sealed = dict(unsigned)
    sealed["content_hash"] = content_hash(unsigned, schema_id=schema_id)
    validate_payload(schema_id, sealed)
    return sealed


def resolve_semantic_profile(value: str | None = None) -> str:
    if value is None:
        return SemanticProfile.STRICT_5X.value
    allowed = {item.value for item in SemanticProfile}
    if value not in allowed:
        raise ValueError(f"PL_UNKNOWN_SEMANTIC_PROFILE: {value}")
    return value


def build_support_profile_v2(
    *,
    created_at_utc_ms: int | None = None,
    producer_commit: str | None = None,
    features: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_id": SUPPORT_PROFILE_CONTRACT,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": "pine2ast",
        "producer_version": __version__,
        "producer_commit": producer_commit or _producer_commit(),
        "stack_id": STACK_ID,
        "created_at_utc_ms": (created_at_utc_ms if created_at_utc_ms is not None else _now_ms()),
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "features": [dict(item) for item in (features or ())],
    }
    return _seal(SUPPORT_PROFILE_CONTRACT, payload)


def build_frontend_v2_payload(
    result: ParseResult,
    *,
    source_path: str = "<memory>",
    source_name: str | None = None,
    semantic_profile: str | None = None,
) -> dict[str, Any]:
    profile = resolve_semantic_profile(semantic_profile)
    created_at = _now_ms()
    commit = _producer_commit()
    support = build_support_profile_v2(created_at_utc_ms=created_at, producer_commit=commit)
    metadata = build_openpine_contract_payload(
        result, source_path=source_path, source_name=source_name
    )
    program = result.ast
    inputs: list[dict[str, Any]] = []
    request_usage: list[str] = []
    if program is not None:
        inputs = [
            {"name": str(item.get("name") or item.get("input_function") or "input")}
            for item in (input_dict(row) for row in extract_inputs(program, result.semantic_model))
        ]
        request_usage = sorted(
            {name for call in extract_request_calls(program) if (name := callee_name(call.callee))}
        )
    declarations = {
        "ok": bool(metadata.get("ok")),
        "source_name": str((metadata.get("source") or {}).get("name") or source_name or ""),
        "sections_present": {key: metadata.get(key) is not None for key in SECTION_CONTRACTS},
    }
    payload: dict[str, Any] = {
        "schema_id": FRONTEND_CONTRACT,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": "pine2ast",
        "producer_version": __version__,
        "producer_commit": commit,
        "stack_id": STACK_ID,
        "created_at_utc_ms": created_at,
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "declarations": declarations,
        "inputs": inputs,
        "request_usage": request_usage,
        "support_profile_ref": support["content_hash"],
        "semantic_profile": profile,
    }
    return _seal(FRONTEND_CONTRACT, payload)


__all__ = [
    "build_frontend_v2_payload",
    "build_support_profile_v2",
    "resolve_semantic_profile",
]
