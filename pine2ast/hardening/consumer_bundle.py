from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .introspection import (
    artifact_payload,
    ast_payload,
    diagnostics_payload,
    iter_ast_nodes,
    parse_source,
    result_ok,
    semantic_facts_payload,
    version_context_payload,
)
from .invariants import (
    InvariantViolation,
    validate_ast_identity,
    validate_consumer_lineage,
    validate_semantic_facts,
    validate_version_context,
)
from .model import canonical_json, content_hash, sha256_bytes
from pine2ast.semantic.type_model import QUALIFIER_ORDER, qualifier_allows

CONSUMER_BUNDLE_CONTRACT = "pine2ast.consumer_bundle.v1"
CONSUMER_BUNDLE_SCHEMA_VERSION = "1.0.0"
_PRODUCTION_BLOCKING_DIAGNOSTIC_CODES = frozenset({"P2A1702"})


class ConsumerBundleError(ValueError):
    pass


def _production_diagnostic_codes(diagnostics: object) -> set[str]:
    if not isinstance(diagnostics, list):
        return set()
    return {
        str(item.get("code"))
        for item in diagnostics
        if isinstance(item, Mapping) and item.get("code") in _PRODUCTION_BLOCKING_DIAGNOSTIC_CODES
    }


def _release_axes(
    facts: Mapping[str, Any], diagnostics: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    calls = [item for item in facts.get("calls", []) if isinstance(item, Mapping)]
    coverage = facts.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}
    call_nodes = int(coverage.get("call_nodes", len(calls)))

    registered_verified = sum(1 for item in calls if item.get("symbol_id"))
    resolved_verified = sum(
        1
        for item in calls
        if item.get("resolution_status") == "RESOLVED" and item.get("overload_id")
    )
    arguments = [
        argument
        for call in calls
        if call.get("resolution_status") == "RESOLVED"
        for argument in call.get("arguments", [])
        if isinstance(argument, Mapping)
    ]

    def qualifier_checked(argument: Mapping[str, Any]) -> bool:
        actual = argument.get("actual_qualifier")
        maximum = argument.get("max_qualifier")
        return (
            actual in QUALIFIER_ORDER
            and maximum in QUALIFIER_ORDER
            and qualifier_allows(str(maximum), str(actual))
        )

    def binding_complete(argument: Mapping[str, Any]) -> bool:
        return bool(
            argument.get("argument_node_id")
            and argument.get("parameter_name") is not None
            and argument.get("parameter_index") is not None
            and argument.get("binding") in {"positional", "named", "vararg"}
            and isinstance(argument.get("actual_type"), str)
            and bool(str(argument.get("actual_type")).strip())
            and isinstance(argument.get("expected_type"), str)
            and bool(str(argument.get("expected_type")).strip())
        )

    qualifier_verified = sum(1 for argument in arguments if qualifier_checked(argument))
    binding_verified = sum(1 for argument in arguments if binding_complete(argument))
    methods = [item for item in calls if item.get("call_form") in {"METHOD", "USER_METHOD"}]
    method_verified = sum(1 for item in methods if item.get("receiver_type"))

    def axis(verified: int, total: int) -> dict[str, Any]:
        status = "NOT_APPLICABLE" if total == 0 else ("PASS" if verified == total else "FAIL")
        return {"status": status, "verified": verified, "total": total}

    version_verified = 0 if _production_diagnostic_codes(diagnostics) else 1
    coverage_verified = 1 if bool(coverage.get("ok")) else 0
    return {
        "name_registered": axis(registered_verified, call_nodes),
        "overload_resolved": axis(resolved_verified, call_nodes),
        "qualifier_enforced": axis(qualifier_verified, len(arguments)),
        "arguments_bound": axis(binding_verified, len(arguments)),
        "method_receiver_typed": axis(method_verified, len(methods)),
        "version_availability_enforced": axis(version_verified, 1),
        "bundle_fact_coverage_complete": axis(coverage_verified, 1),
        "tradingview_compile_oracle": {"status": "NOT_RUN", "evidence_id": None},
    }


def _node_index(ast: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, node in enumerate(iter_ast_nodes(ast)):
        result.append(
            {
                "ordinal": index,
                "node_id": node.get("node_id", f"n{index:08d}"),
                "kind": node.get("kind"),
                "span": node.get("span"),
            }
        )
    return result


def build_consumer_bundle(
    source: str,
    *,
    source_name: str = "<consumer-vector>",
    producer_commit: str | None = None,
    require_clean_frontend: bool = True,
    created_at_utc_ms: int = 0,
) -> dict[str, Any]:
    result = parse_source(
        source,
        source_name=source_name,
        created_at_utc_ms=created_at_utc_ms,
    )
    diagnostics = diagnostics_payload(result)
    production_blockers = _production_diagnostic_codes(diagnostics)
    if require_clean_frontend and (not result_ok(result) or production_blockers):
        suffix = (
            f": {', '.join(sorted(production_blockers))} is unavailable in the declared version"
            if production_blockers
            else ""
        )
        raise ConsumerBundleError(
            f"frontend result contains production-blocking diagnostics{suffix}"
        )
    ast = ast_payload(result)
    context = version_context_payload(result, ast)
    facts = semantic_facts_payload(result, ast)
    index = _node_index(ast)
    try:
        validate_version_context(context)
        validate_ast_identity(ast, context)
        validate_semantic_facts(ast, facts, node_index=index)
    except InvariantViolation as exc:
        raise ConsumerBundleError(str(exc)) from exc

    from pine2ast import __version__

    artifacts: dict[str, Any] = {
        "ast_hash": content_hash(ast),
        "semantic_facts_hash": content_hash(facts),
        "node_index_hash": content_hash(index),
    }
    optional_payloads: dict[str, Any] = {}
    for name in ("ast_artifact", "frontend_artifact", "support_profile"):
        payload = artifact_payload(result, name)
        if payload is not None:
            optional_payloads[name] = payload
            artifacts[f"{name}_hash"] = content_hash(payload)

    body: dict[str, Any] = {
        "schema_id": CONSUMER_BUNDLE_CONTRACT,
        "schema_version": CONSUMER_BUNDLE_SCHEMA_VERSION,
        "producer": {
            "name": "pine2ast",
            "version": __version__,
            "commit": producer_commit,
        },
        "source": {
            "name": source_name,
            "encoding": "utf-8",
            "byte_length": len(source.encode("utf-8")),
            "source_hash": sha256_bytes(source.encode("utf-8")),
        },
        "version_context": context,
        "ast": ast,
        "semantic_facts": facts,
        "node_index": index,
        "diagnostics": diagnostics,
        "release_axes": _release_axes(facts, diagnostics),
        "artifacts": artifacts,
        "linked_artifacts": optional_payloads,
        "consumer_contract": {
            "consumer": "ast2python",
            "minimum_consumer_version": "5.0.0rc6",
            "required_capabilities": [
                "pine_version_context_v1",
                "pine_ast_v2",
                "pine_semantic_facts_v1",
                "resolved_symbol_identity",
                "resolved_overload_identity",
                "source_span_identity",
            ],
        },
    }
    body["content_hash"] = content_hash(body)
    verify_consumer_bundle(body, source=source, expected_producer_commit=producer_commit)
    return body


def verify_consumer_bundle(
    bundle: Mapping[str, Any],
    *,
    source: str | None = None,
    expected_producer_commit: str | None = None,
) -> None:
    try:
        if bundle.get("schema_id") != CONSUMER_BUNDLE_CONTRACT:
            raise ConsumerBundleError("unsupported consumer bundle schema_id")
        if bundle.get("schema_version") != CONSUMER_BUNDLE_SCHEMA_VERSION:
            raise ConsumerBundleError("unsupported consumer bundle schema_version")
        production_blockers = _production_diagnostic_codes(bundle.get("diagnostics"))
        if production_blockers:
            raise ConsumerBundleError(
                "consumer bundle contains symbols unavailable in its declared version: "
                + ", ".join(sorted(production_blockers))
            )
        stored = bundle.get("content_hash")
        body = {k: deepcopy(v) for k, v in bundle.items() if k != "content_hash"}
        if stored != content_hash(body):
            raise ConsumerBundleError("consumer bundle content hash mismatch")
        context = bundle.get("version_context")
        ast = bundle.get("ast")
        facts = bundle.get("semantic_facts")
        if (
            not isinstance(context, Mapping)
            or not isinstance(ast, Mapping)
            or not isinstance(facts, Mapping)
        ):
            raise ConsumerBundleError("bundle core sections are missing")
        diagnostics = bundle.get("diagnostics")
        diagnostic_rows = (
            [dict(item) for item in diagnostics if isinstance(item, Mapping)]
            if isinstance(diagnostics, list)
            else []
        )
        if bundle.get("release_axes") != _release_axes(facts, diagnostic_rows):
            raise ConsumerBundleError("consumer bundle release axes mismatch")
        validate_version_context(context)
        validate_ast_identity(ast, context)
        validate_semantic_facts(ast, facts, node_index=bundle.get("node_index"))
        validate_consumer_lineage(bundle)
        artifacts = bundle["artifacts"]
        if artifacts.get("ast_hash") != content_hash(ast):
            raise ConsumerBundleError("AST hash mismatch")
        if artifacts.get("semantic_facts_hash") != content_hash(facts):
            raise ConsumerBundleError("semantic facts hash mismatch")
        if artifacts.get("node_index_hash") != content_hash(bundle.get("node_index")):
            raise ConsumerBundleError("node index hash mismatch")
        producer = bundle.get("producer")
        if not isinstance(producer, Mapping):
            raise ConsumerBundleError("producer identity is missing")
        producer_commit = producer.get("commit")
        if producer_commit is not None and (
            not isinstance(producer_commit, str)
            or len(producer_commit) != 40
            or any(char not in "0123456789abcdef" for char in producer_commit)
        ):
            raise ConsumerBundleError("producer commit must be 40 lowercase hexadecimal characters")
        if producer_commit is not None and expected_producer_commit is None:
            raise ConsumerBundleError(
                "bundle declares a producer commit but no trusted producer commit was supplied"
            )
        if producer_commit != expected_producer_commit:
            raise ConsumerBundleError("producer commit mismatch")
        if source is not None:
            if bundle["source"].get("source_hash") != sha256_bytes(source.encode("utf-8")):
                raise ConsumerBundleError("source hash mismatch")
            source_name = bundle["source"].get("name", "<consumer-vector>")
            linked = bundle.get("linked_artifacts")
            ast_artifact = linked.get("ast_artifact") if isinstance(linked, Mapping) else None
            created_at_utc_ms = (
                ast_artifact.get("created_at_utc_ms") if isinstance(ast_artifact, Mapping) else 0
            )
            parsed_source = parse_source(
                source,
                source_name=str(source_name),
                created_at_utc_ms=created_at_utc_ms,
            )
            parsed_diagnostics = diagnostics_payload(parsed_source)
            if not result_ok(parsed_source) or _production_diagnostic_codes(parsed_diagnostics):
                raise ConsumerBundleError("source does not produce a clean frontend result")
            reparsed_ast = ast_payload(parsed_source)
            if content_hash(reparsed_ast) != content_hash(ast):
                raise ConsumerBundleError("source and AST do not match")
    except InvariantViolation as exc:
        raise ConsumerBundleError(str(exc)) from exc


def write_consumer_bundle(path: str | Path, source: str, **kwargs: Any) -> dict[str, Any]:
    bundle = build_consumer_bundle(source, **kwargs)
    Path(path).write_text(canonical_json(bundle) + "\n", encoding="utf-8")
    return bundle
