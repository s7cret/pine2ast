from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterator

from .model import content_hash, to_plain


class FrontendIntrospectionError(RuntimeError):
    pass


def parse_source(
    source: str,
    *,
    source_name: str = "<stage4>",
    created_at_utc_ms: int | None = None,
    producer_commit: str | None = None,
) -> Any:
    from pine2ast import ParseOptions, parse_code

    options = ParseOptions(
        source_name=source_name,
        created_at_utc_ms=created_at_utc_ms,
        producer_commit=producer_commit,
    )
    return parse_code(source, options)


def ast_payload(result: Any) -> dict[str, Any]:
    ast = getattr(result, "ast", None)
    if ast is None:
        raise FrontendIntrospectionError("parse result contains no AST")
    value = to_plain(ast)
    if not isinstance(value, dict):
        raise FrontendIntrospectionError("AST is not serializable as an object")
    return value


def diagnostics_payload(result: Any) -> list[dict[str, Any]]:
    raw = getattr(result, "diagnostics", ()) or ()
    return [to_plain(item) for item in raw]


def result_ok(result: Any) -> bool:
    value = getattr(result, "ok", None)
    if isinstance(value, bool):
        return value
    return not any(
        str(d.get("severity", "")).upper() in {"ERROR", "FATAL"}
        for d in diagnostics_payload(result)
    )


def _candidate_contexts(result: Any, ast: Mapping[str, Any]) -> Iterator[Any]:
    for owner in (result, getattr(result, "ast", None)):
        if owner is None:
            continue
        for name in ("version_context", "pine_version_context", "language_identity"):
            value = getattr(owner, name, None)
            if value is not None:
                yield value
    for name in ("version_context", "pine_version_context", "language_identity"):
        if name in ast:
            yield ast[name]
    for artifact_name in ("ast_artifact", "frontend_artifact"):
        artifact = to_plain(getattr(result, artifact_name, None))
        if isinstance(artifact, dict):
            for name in ("version_context", "pine_version_context", "language_identity"):
                if name in artifact:
                    yield artifact[name]


def version_context_payload(result: Any, ast: Mapping[str, Any] | None = None) -> dict[str, Any]:
    tree = dict(ast or ast_payload(result))
    for candidate in _candidate_contexts(result, tree):
        value = to_plain(candidate)
        if not isinstance(value, dict):
            continue
        version = value.get("pine_version", value.get("effective_version", value.get("version")))
        if type(version) is int:
            normalized = dict(value)
            normalized["pine_version"] = version
            if "catalog_hash" not in normalized:
                for alias in (
                    "catalog_pack_hash",
                    "version_pack_hash",
                    "pack_hash",
                    "profile_hash",
                ):
                    candidate = normalized.get(alias)
                    if isinstance(candidate, str) and candidate.startswith("sha256:"):
                        normalized["catalog_hash"] = candidate
                        break
            normalized.setdefault(
                "context_hash",
                content_hash({k: v for k, v in normalized.items() if k != "context_hash"}),
            )
            return normalized
    raise FrontendIntrospectionError("single Pine version context is missing")


def effective_version(result: Any) -> int:
    return int(version_context_payload(result)["pine_version"])


def _artifact_candidate(result: Any, names: tuple[str, ...]) -> dict[str, Any] | None:
    for name in names:
        value = to_plain(getattr(result, name, None))
        if isinstance(value, dict) and value:
            return value
    return None


def normalize_semantic_facts(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    # Unwrap one explicit payload layer, preserving envelope identity outside the facts list.
    payload = normalized.get("payload")
    if isinstance(payload, dict) and any(
        isinstance(payload.get(k), list) for k in ("facts", "nodes", "node_facts")
    ):
        normalized = {**normalized, **payload}
    canonical_schema = normalized.get("schema_id") == "pine.semantic_facts.v1"
    for key in ("facts", "nodes", "node_facts"):
        raw = normalized.get(key)
        if not isinstance(raw, list):
            continue
        rows = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("node_id", row.get("id", f"n{index:08d}"))
            if not canonical_schema:
                row.setdefault("node_kind", row.get("kind", row.get("ast_kind", "Unknown")))
            row.setdefault("span", row.get("source_span", row.get("location")))
            rows.append(row)
        normalized["facts"] = rows
        if key != "facts":
            normalized.pop(key, None)
        break
    if "content_hash" in normalized:
        normalized["content_hash"] = content_hash(
            {key: value for key, value in normalized.items() if key != "content_hash"}
        )
    return normalized


def semantic_facts_payload(result: Any, ast: Mapping[str, Any] | None = None) -> dict[str, Any]:
    direct = _artifact_candidate(
        result,
        (
            "semantic_facts_artifact",
            "semantic_facts",
            "semantic_snapshot",
            "semantic_snapshot_artifact",
        ),
    )
    if direct is not None:
        return normalize_semantic_facts(direct)
    frontend = _artifact_candidate(result, ("frontend_artifact",))
    if frontend:
        for key in ("semantic_facts", "semantic_snapshot", "node_facts"):
            value = frontend.get(key)
            if isinstance(value, dict) and value:
                return normalize_semantic_facts(value)
    model = getattr(result, "semantic_model", None)
    facts: list[dict[str, Any]] = []
    tree = dict(ast or ast_payload(result))
    nodes = list(iter_ast_nodes(tree))
    node_types = getattr(model, "node_types", {}) if model is not None else {}
    node_qualifiers = getattr(model, "node_qualifiers", {}) if model is not None else {}
    for index, node in enumerate(nodes):
        fact = {
            "node_id": node.get("node_id", f"n{index:08d}"),
            "node_kind": node.get("kind", "Unknown"),
            "span": node.get("span"),
        }
        # Object-id maps cannot be reconstructed from serialized AST, so this fallback is
        # deliberately marked derived and is not accepted for canonical consumer release.
        if index < len(node_types):
            fact["resolved_type"] = list(node_types.values())[index]
        if index < len(node_qualifiers):
            fact["resolved_qualifier"] = list(node_qualifiers.values())[index]
        facts.append(fact)
    return {
        "schema_id": "pine.semantic_facts.fallback.v1",
        "canonical": False,
        "facts": facts,
    }


_ANNOTATION_KINDS = frozenset(
    {
        "VERSION",
        "DESCRIPTION",
        "FUNCTION",
        "PARAM",
        "RETURNS",
        "TYPE",
        "FIELD",
        "ENUM",
        "VARIABLE",
        "STRATEGY_ALERT_MESSAGE",
        "REGION_START",
        "REGION_END",
        "UNKNOWN",
    }
)


def iter_ast_nodes(value: Any) -> Iterator[dict[str, Any]]:
    """Yield serialized AST nodes while excluding non-AST metadata records.

    Compiler annotations also carry a ``kind`` field, but they are provenance
    records rather than nodes indexed by :class:`SemanticBinder`. Treating them
    as AST nodes creates a false one-node coverage gap at the consumer boundary.
    """

    if isinstance(value, dict):
        kind = value.get("kind")
        if isinstance(kind, str) and kind not in _ANNOTATION_KINDS:
            yield value
        for child in value.values():
            yield from iter_ast_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_ast_nodes(child)


def artifact_payload(result: Any, name: str) -> dict[str, Any] | None:
    value = to_plain(getattr(result, name, None))
    return value if isinstance(value, dict) and value else None


def package_root() -> Path:
    import pine2ast

    return Path(pine2ast.__file__).resolve().parent


def version_pack(version: int) -> dict[str, Any]:
    root = package_root()
    candidates = sorted(root.rglob(f"pine_v{version}.pack.json"))
    if not candidates:
        candidates = sorted(root.rglob(f"*v{version}*pack*.json"))
    if len(candidates) != 1:
        raise FrontendIntrospectionError(
            f"expected exactly one materialized pack for Pine v{version}, found {len(candidates)}"
        )
    import json

    return json.loads(candidates[0].read_text(encoding="utf-8"))
