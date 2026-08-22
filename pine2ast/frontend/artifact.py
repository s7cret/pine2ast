"""Immutable catalog artifacts emitted by the production frontend path."""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from openpine_contracts import SemanticProfile, seal_content_hash, validate_payload
from openpine_contracts.hashing import CONTENT_HASH_ALG, SERIALIZER_ID

from pine2ast._version import __version__
from pine2ast.api import ParseOptions, ParseResult
from pine2ast.ast.visitors import walk
from pine2ast.frontend.ids import (
    AST_CATALOG_CONTRACT,
    CATALOG_SCHEMA_VERSION,
    FRONTEND_CONTRACT,
    SECTION_CONTRACTS,
    STACK_ID,
    SUPPORT_PROFILE_CONTRACT,
)
from pine2ast.frontend.immutable import deep_freeze
from pine2ast.frontend.payload import build_openpine_contract_payload
from pine2ast.semantic.extractors import extract_inputs, extract_plots, extract_request_calls
from pine2ast.semantic.type_infer import callee_name

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SUPPORT_AXES = (
    "parse",
    "bind_type",
    "lower",
    "runtime",
    "data_mtf",
    "simulation",
    "live_safe",
    "visual",
    "numeric_parity",
)


def _semver() -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)rc(\d+)", __version__)
    if match:
        major, minor, patch, rc = match.groups()
        return f"{major}.{minor}.{patch}-rc.{rc}"
    return __version__


def _producer_commit(explicit: str | None = None) -> str:
    if explicit is not None:
        if not _GIT_SHA_RE.fullmatch(explicit):
            raise ValueError("producer commit must be exactly 40 lowercase hexadecimal characters")
        return explicit
    override = os.environ.get("OPENPINE_PRODUCER_COMMIT", "").strip()
    if override:
        if not _GIT_SHA_RE.fullmatch(override):
            raise ValueError(
                "OPENPINE_PRODUCER_COMMIT must be exactly 40 lowercase hexadecimal characters"
            )
        return override
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            "producer commit unavailable; set OPENPINE_PRODUCER_COMMIT to an exact Git SHA"
        ) from exc
    if not _GIT_SHA_RE.fullmatch(commit):
        raise ValueError("producer commit must be exactly 40 lowercase hexadecimal characters")
    return commit


def _now_ms() -> int:
    return int(time.time() * 1000)


def _seal(schema_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    sealed = seal_content_hash(payload, schema_id=schema_id)
    validate_payload(schema_id, sealed)
    return sealed


def resolve_semantic_profile(value: str | None = None) -> str:
    if value is None:
        return SemanticProfile.STRICT_5X.value
    allowed = {item.value for item in SemanticProfile}
    if value not in allowed:
        raise ValueError(f"PL_UNKNOWN_SEMANTIC_PROFILE: {value}")
    return value


def _feature(
    feature_id: str,
    *,
    parse: str = "SUPPORTED",
    bind_type: str = "SUPPORTED",
    lower: str = "CONDITIONAL",
    runtime: str = "CONDITIONAL",
    data_mtf: str = "NOT_APPLICABLE",
    simulation: str = "CONDITIONAL",
    live_safe: str = "UNSUPPORTED",
    visual: str = "NOT_APPLICABLE",
    numeric_parity: str = "CONDITIONAL",
    capability_predicate: str | None = None,
    limitation_code: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "feature_id": feature_id,
        "parse": parse,
        "bind_type": bind_type,
        "lower": lower,
        "runtime": runtime,
        "data_mtf": data_mtf,
        "simulation": simulation,
        "live_safe": live_safe,
        "visual": visual,
        "numeric_parity": numeric_parity,
    }
    if capability_predicate is not None:
        row["capability_predicate"] = capability_predicate
    if limitation_code is not None:
        row["limitation_code"] = limitation_code
    return row


def _support_features(blocking_diagnostics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        _feature(
            "broker_projection_reads",
            capability_predicate="interactive_broker_projection",
        ),
        _feature(
            "calc_on_order_fills",
            capability_predicate="interactive_fill_recalculation",
        ),
        _feature(
            "mtf_requested_series",
            data_mtf="CONDITIONAL",
            capability_predicate="explicit_confirmed_series",
        ),
        _feature(
            "visuals",
            lower="VISUAL_ONLY",
            runtime="VISUAL_ONLY",
            simulation="NOT_APPLICABLE",
            live_safe="NOT_APPLICABLE",
            visual="SUPPORTED",
            numeric_parity="NOT_APPLICABLE",
        ),
        _feature(
            "unsupported_features",
            lower="UNSUPPORTED" if blocking_diagnostics else "SUPPORTED",
            runtime="UNSUPPORTED" if blocking_diagnostics else "SUPPORTED",
            simulation="UNSUPPORTED" if blocking_diagnostics else "SUPPORTED",
            limitation_code=(
                str(blocking_diagnostics[0]["code"]) if blocking_diagnostics else None
            ),
        ),
    ]


def build_support_profile_v2(
    *,
    created_at_utc_ms: int | None = None,
    producer_commit: str | None = None,
    features: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    commit = producer_commit or _producer_commit()
    if not _GIT_SHA_RE.fullmatch(commit):
        raise ValueError("producer commit must be exactly 40 lowercase hexadecimal characters")
    payload = {
        "schema_id": SUPPORT_PROFILE_CONTRACT,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": "pine2ast",
        "producer_version": _semver(),
        "producer_commit": commit,
        "stack_id": STACK_ID,
        "created_at_utc_ms": created_at_utc_ms if created_at_utc_ms is not None else _now_ms(),
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "features": [dict(item) for item in (features or _support_features(()))],
    }
    return _seal(SUPPORT_PROFILE_CONTRACT, payload)


def _contract_value(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("input metadata contains a non-finite float")
        return format(value, ".17g")
    if isinstance(value, list):
        return [_contract_value(item) for item in value]
    if isinstance(value, tuple):
        return [_contract_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _contract_value(item) for key, item in value.items()}
    return value


def _input_definitions(result: ParseResult) -> list[dict[str, Any]]:
    if result.ast is None:
        return []
    definitions: list[dict[str, Any]] = []
    for item in extract_inputs(result.ast, result.semantic_model):
        row = {
            "name": item.name,
            "type": item.input_function.rsplit(".", 1)[-1],
            "default": _contract_value(item.default_value),
            "min": _contract_value(item.minval),
            "max": _contract_value(item.maxval),
            "step": _contract_value(item.step),
            "options": _contract_value(item.options),
            "group": item.group,
        }
        definitions.append({key: value for key, value in row.items() if value is not None})
    return definitions


def _blocking_diagnostics(result: ParseResult) -> list[dict[str, Any]]:
    return [
        {
            "code": diagnostic.code,
            "severity": diagnostic.severity.value,
            "message": diagnostic.message,
            "span": diagnostic.span.to_dict(),
        }
        for diagnostic in result.diagnostics
        if diagnostic.severity.value in {"ERROR", "FATAL"}
    ]


def _capability_usage(
    result: ParseResult,
) -> tuple[list[str], list[str], list[str], dict[str, Any]]:
    if result.ast is None:
        return [], [], [], {}
    request_names = {callee_name(call.callee) for call in extract_request_calls(result.ast)}
    request_usage = ["mtf_requested_series"] if "request.security" in request_names else []
    visual_requirements = ["visuals"] if extract_plots(result.ast) else []
    referenced_names = {name for node in walk(result.ast) if (name := callee_name(node))}
    referenced_builtins = (
        ["broker_projection_reads"]
        if any(name.startswith("strategy.position") for name in referenced_names)
        else []
    )
    settings: dict[str, Any] = {}
    declaration = getattr(result.ast, "declaration", None)
    call = getattr(declaration, "call", None)
    for argument in getattr(call, "arguments", ()):
        if argument.name == "calc_on_order_fills":
            settings["calc_on_order_fills"] = {
                "enabled": bool(getattr(argument.value, "value", False)),
                "capability": "calc_on_order_fills",
            }
    return referenced_builtins, request_usage, visual_requirements, settings


def _frontend_payload(
    result: ParseResult,
    *,
    support_profile: Mapping[str, Any],
    created_at_utc_ms: int,
    producer_commit: str,
    source_path: str,
    source_name: str | None,
    semantic_profile: str | None,
) -> dict[str, Any]:
    profile = resolve_semantic_profile(semantic_profile)
    metadata = build_openpine_contract_payload(
        result, source_path=source_path, source_name=source_name
    )
    blocking = _blocking_diagnostics(result)
    referenced, requests, visuals, settings = _capability_usage(result)
    declarations = {
        "ok": bool(metadata.get("ok")),
        "source_name": str((metadata.get("source") or {}).get("name") or source_name or ""),
        "sections_present": {key: metadata.get(key) is not None for key in SECTION_CONTRACTS},
        "blocking_diagnostics": blocking,
    }
    payload: dict[str, Any] = {
        "schema_id": FRONTEND_CONTRACT,
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": "pine2ast",
        "producer_version": _semver(),
        "producer_commit": producer_commit,
        "stack_id": STACK_ID,
        "created_at_utc_ms": created_at_utc_ms,
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "declarations": declarations,
        "inputs": _input_definitions(result),
        "strategy_settings": settings,
        "referenced_builtins": referenced,
        "request_usage": requests,
        "visual_requirements": visuals,
        "support_profile_ref": support_profile["content_hash"],
        "semantic_profile": profile,
    }
    return _seal(FRONTEND_CONTRACT, payload)


def build_frontend_v2_payload(
    result: ParseResult,
    *,
    source_path: str = "<memory>",
    source_name: str | None = None,
    semantic_profile: str | None = None,
    producer_commit: str | None = None,
) -> dict[str, Any]:
    created_at = _now_ms()
    commit = _producer_commit(producer_commit)
    blocking = _blocking_diagnostics(result)
    support = build_support_profile_v2(
        created_at_utc_ms=created_at,
        producer_commit=commit,
        features=_support_features(blocking),
    )
    return _frontend_payload(
        result,
        support_profile=support,
        created_at_utc_ms=created_at,
        producer_commit=commit,
        source_path=source_path,
        source_name=source_name,
        semantic_profile=semantic_profile,
    )


def _ast_artifact(
    result: ParseResult,
    *,
    source: str | bytes,
    created_at_utc_ms: int,
    producer_commit: str,
    options: ParseOptions,
) -> dict[str, Any]:
    source_bytes = source.encode("utf-8") if isinstance(source, str) else bytes(source)
    nodes: list[dict[str, Any]] = []
    if result.ast is not None:
        for index, node in enumerate(walk(result.ast)):
            span = getattr(node, "span", None)
            if span is None:
                continue
            nodes.append(
                {
                    "node_id": f"n{index:08d}",
                    "kind": type(node).__name__,
                    "span": {
                        "start_line": int(span.start_line),
                        "start_col": int(span.start_col),
                        "end_line": int(span.end_line),
                        "end_col": int(span.end_col),
                    },
                }
            )
    payload = {
        "schema_id": AST_CATALOG_CONTRACT,
        "schema_version": "1.0.0",
        "producer": "pine2ast",
        "producer_version": _semver(),
        "producer_commit": producer_commit,
        "stack_id": STACK_ID,
        "created_at_utc_ms": created_at_utc_ms,
        "serializer_id": SERIALIZER_ID,
        "content_hash_alg": CONTENT_HASH_ALG,
        "pine_version": str(getattr(result.ast, "version", None) or options.version),
        "source_hash": f"sha256:{hashlib.sha256(source_bytes).hexdigest()}",
        "nodes": nodes,
        "diagnostics": [
            {"code": diagnostic.code, "message": diagnostic.message}
            for diagnostic in result.diagnostics
        ],
    }
    return _seal(AST_CATALOG_CONTRACT, payload)


def attach_frontend_artifacts(
    result: ParseResult,
    *,
    source: str | bytes,
    options: ParseOptions,
    source_path: str,
    semantic_profile: str | None,
) -> ParseResult:
    """Attach one immutable frontend/AST/support bundle to a parse result."""

    created_at = _now_ms()
    commit = _producer_commit(options.producer_commit)
    blocking = _blocking_diagnostics(result)
    support = build_support_profile_v2(
        created_at_utc_ms=created_at,
        producer_commit=commit,
        features=_support_features(blocking),
    )
    frontend = _frontend_payload(
        result,
        support_profile=support,
        created_at_utc_ms=created_at,
        producer_commit=commit,
        source_path=source_path,
        source_name=options.source_name,
        semantic_profile=semantic_profile,
    )
    ast_artifact = _ast_artifact(
        result,
        source=source,
        created_at_utc_ms=created_at,
        producer_commit=commit,
        options=options,
    )
    return replace(
        result,
        ast_artifact=deep_freeze(ast_artifact),
        frontend_artifact=deep_freeze(frontend),
        support_profile=deep_freeze(support),
        created_at_utc_ms=created_at,
    )


__all__ = [
    "attach_frontend_artifacts",
    "build_frontend_v2_payload",
    "build_support_profile_v2",
    "resolve_semantic_profile",
]
