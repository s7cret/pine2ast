from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from typing import Any, Mapping

from pine2ast._version import __version__
from pine2ast.api import ParseOptions, ParseResult
from pine2ast.ast.visitors import walk
from pine2ast.catalog.hashing import seal_hash, sha256_id, verify_hash
from pine2ast.frontend.ids import (
    AST_CATALOG_CONTRACT,
    FRONTEND_CONTRACT,
    SEMANTIC_FACTS_CONTRACT,
    SOURCE_MANIFEST_CONTRACT,
    SUPPORT_PROFILE_CONTRACT,
)
from pine2ast.frontend.immutable import deep_freeze
from pine2ast.frontend.payload import build_frontend_contract_payload

_FRONTEND_AXES = (
    "parse",
    "bind",
    "type",
    "qualifier",
    "overload",
    "static_rule",
    "diagnostic",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _producer_identity(explicit_commit: str | None) -> dict[str, Any]:
    """Return an honest producer identity; never synthesize a Git commit."""

    if explicit_commit is None:
        return {
            "name": "pine2ast",
            "version": __version__,
            "commit": None,
            "source_state": "UNCOMMITTED_LOCAL_BUILD",
        }
    if len(explicit_commit) != 40 or any(
        char not in "0123456789abcdef" for char in explicit_commit
    ):
        raise ValueError("producer_commit must be exactly 40 lowercase hexadecimal characters")
    return {
        "name": "pine2ast",
        "version": __version__,
        "commit": explicit_commit,
        "source_state": "COMMIT_PINNED",
    }


def _source_hash(source: str | bytes) -> str:
    data = source.encode("utf-8") if isinstance(source, str) else bytes(source)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _source_manifest(
    result: ParseResult,
    *,
    source: str | bytes,
    source_path: str,
    source_name: str,
    created_at: int,
    producer: Mapping[str, Any],
) -> dict[str, Any]:
    version_context = result.version_context.to_dict() if result.version_context else None
    payload = {
        "schema_id": SOURCE_MANIFEST_CONTRACT,
        "schema_version": "1.0.0",
        "producer": dict(producer),
        "created_at_utc_ms": created_at,
        "source": {"path": source_path, "name": source_name},
        "source_hash": _source_hash(source),
        "version_context": version_context,
        "version_context_ref": sha256_id(version_context) if version_context else None,
    }
    return seal_hash(payload)


def _semantic_artifact(result: ParseResult) -> dict[str, Any] | None:
    facts = getattr(result.semantic_model, "semantic_facts", None)
    artifact = getattr(facts, "artifact", None)
    if artifact is None:
        return None
    if not isinstance(artifact, dict):
        raise ValueError("semantic facts artifact must be a mapping")
    if artifact.get("schema_id") != SEMANTIC_FACTS_CONTRACT:
        raise ValueError("semantic facts artifact has an unexpected schema_id")
    if not verify_hash(artifact):
        raise ValueError("semantic facts artifact content_hash is invalid")
    return artifact


def _ast_artifact(
    result: ParseResult,
    *,
    source_manifest: Mapping[str, Any],
    created_at: int,
    producer: Mapping[str, Any],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    if result.ast is not None:
        for index, node in enumerate(walk(result.ast)):
            span = getattr(node, "span", None)
            if span is not None:
                nodes.append(
                    {
                        "node_id": f"n{index:08d}",
                        "kind": type(node).__name__,
                        "span": span.to_dict(),
                    }
                )
    version_context = result.version_context.to_dict() if result.version_context else None
    payload = {
        "schema_id": AST_CATALOG_CONTRACT,
        "schema_version": "2.0.0",
        "producer": dict(producer),
        "created_at_utc_ms": created_at,
        "version_context": version_context,
        "version_context_ref": sha256_id(version_context) if version_context else None,
        "source_manifest_ref": source_manifest["content_hash"],
        "source_hash": source_manifest["source_hash"],
        "nodes": nodes,
        "diagnostics": [item.to_dict() for item in result.diagnostics],
    }
    return seal_hash(payload)


def _support_profile(
    result: ParseResult,
    *,
    semantic_artifact: Mapping[str, Any] | None,
    ast_artifact: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    created_at: int,
    producer: Mapping[str, Any],
) -> dict[str, Any]:
    blocking = [item.to_dict() for item in result.diagnostics if item.is_error]
    semantic_coverage = None
    if semantic_artifact is not None:
        semantic_coverage = semantic_artifact.get("coverage")
    semantic_complete = bool(
        isinstance(semantic_coverage, Mapping)
        and semantic_coverage.get("ok") is True
        and not blocking
    )
    parse_state = "SUPPORTED" if result.ast is not None else "UNSUPPORTED"
    semantic_state = (
        "SUPPORTED"
        if semantic_complete
        else ("NOT_RUN" if result.semantic_model is None else "UNSUPPORTED")
    )
    axes = {
        "parse": parse_state,
        "bind": semantic_state,
        "type": semantic_state,
        "qualifier": semantic_state,
        "overload": semantic_state,
        "static_rule": semantic_state,
        "diagnostic": "SUPPORTED",
    }
    payload = {
        "schema_id": SUPPORT_PROFILE_CONTRACT,
        "schema_version": "3.0.0",
        "producer": dict(producer),
        "created_at_utc_ms": created_at,
        "version_context": result.version_context.to_dict() if result.version_context else None,
        "source_manifest_ref": source_manifest["content_hash"],
        "ast_ref": ast_artifact["content_hash"],
        "semantic_facts_ref": (
            semantic_artifact["content_hash"] if semantic_artifact is not None else None
        ),
        "axes": axes,
        "semantic_coverage": semantic_coverage,
        "blocking_diagnostics": blocking,
    }
    return seal_hash(payload)


def _build_artifacts(
    result: ParseResult,
    *,
    source: str | bytes,
    source_path: str,
    source_name: str,
    producer_commit: str | None,
    created_at: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    producer = _producer_identity(producer_commit)
    source_manifest = _source_manifest(
        result,
        source=source,
        source_path=source_path,
        source_name=source_name,
        created_at=created_at,
        producer=producer,
    )
    ast_artifact = _ast_artifact(
        result,
        source_manifest=source_manifest,
        created_at=created_at,
        producer=producer,
    )
    semantic_artifact = _semantic_artifact(result)
    support = _support_profile(
        result,
        semantic_artifact=semantic_artifact,
        ast_artifact=ast_artifact,
        source_manifest=source_manifest,
        created_at=created_at,
        producer=producer,
    )
    frontend_body = build_frontend_contract_payload(
        result,
        source_path=source_path,
        source_name=source_name,
    )
    version_context = result.version_context.to_dict() if result.version_context else None
    frontend = seal_hash(
        {
            "schema_id": FRONTEND_CONTRACT,
            "schema_version": "3.0.0",
            "producer": dict(producer),
            "created_at_utc_ms": created_at,
            "version_context": version_context,
            "version_context_ref": sha256_id(version_context) if version_context else None,
            "source_hash": source_manifest["source_hash"],
            "source_manifest_ref": source_manifest["content_hash"],
            "ast_ref": ast_artifact["content_hash"],
            "semantic_facts_ref": (
                semantic_artifact["content_hash"] if semantic_artifact is not None else None
            ),
            "frontend_support_ref": support["content_hash"],
            "frontend": frontend_body,
        }
    )
    return source_manifest, ast_artifact, semantic_artifact, support, frontend


def attach_frontend_artifacts(
    result: ParseResult,
    *,
    source: str | bytes,
    options: ParseOptions,
    source_path: str,
) -> ParseResult:
    created_at = _now_ms() if options.created_at_utc_ms is None else options.created_at_utc_ms
    source_manifest, ast_artifact, semantic_artifact, support, frontend = _build_artifacts(
        result,
        source=source,
        source_path=source_path,
        source_name=options.source_name,
        producer_commit=options.producer_commit,
        created_at=created_at,
    )
    return replace(
        result,
        ast_artifact=deep_freeze(ast_artifact),
        semantic_facts_artifact=(
            deep_freeze(semantic_artifact) if semantic_artifact is not None else None
        ),
        source_manifest=deep_freeze(source_manifest),
        frontend_artifact=deep_freeze(frontend),
        support_profile=deep_freeze(support),
        created_at_utc_ms=created_at,
    )


def build_frontend_v3_payload(
    result: ParseResult,
    *,
    source: str | bytes,
    source_path: str = "<memory>",
    source_name: str | None = None,
    producer_commit: str | None = None,
    created_at_utc_ms: int | None = None,
) -> dict[str, Any]:
    """Build a fully lineage-bound frontend artifact.

    Production callers must supply the exact source bytes; a frontend artifact is
    never synthesized from an AST alone because that would break provenance.
    """

    created = _now_ms() if created_at_utc_ms is None else created_at_utc_ms
    if type(created) is not int or created < 0:
        raise ValueError("created_at_utc_ms must be a nonnegative integer")
    manifest = result.source_manifest
    if not isinstance(manifest, Mapping):
        raise ValueError("parse result is not bound to an exact source manifest")
    parsed_source_hash = manifest.get("source_hash")
    if parsed_source_hash != _source_hash(source):
        raise ValueError("source does not match the source used to produce the parse result")
    _, _, _, _, frontend = _build_artifacts(
        result,
        source=source,
        source_path=source_path,
        source_name=source_name or source_path,
        producer_commit=producer_commit,
        created_at=created,
    )
    return frontend


__all__ = ["attach_frontend_artifacts", "build_frontend_v3_payload"]
