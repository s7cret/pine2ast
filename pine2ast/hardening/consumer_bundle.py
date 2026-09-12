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
from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError, ASTReplayLimits
from .method_functions import METHOD_FUNCTION_CAPABILITY, method_function_feature
from .function_overloads import (
    FUNCTION_OVERLOAD_CAPABILITY,
    LIBRARY_OVERLOAD_CAPABILITY,
    function_overload_feature,
    library_overload_feature,
)
from .method_receivers import (
    METHOD_RECEIVER_CAPABILITY,
    receiver_feature,
    verify_method_receiver_semantics,
)

CONSUMER_BUNDLE_CONTRACT = "pine2ast.consumer_bundle.v1"
CONSUMER_BUNDLE_SCHEMA_VERSION = "1.0.0"
LIBRARY_CONSUMER_BUNDLE_SCHEMA_VERSION = "1.1.0"
_BASE_CONSUMER_CAPABILITIES = (
    "pine_version_context_v1",
    "pine_ast_v2",
    "pine_semantic_facts_v1",
    "resolved_symbol_identity",
    "resolved_overload_identity",
    "source_span_identity",
)
_PRODUCTION_BLOCKING_DIAGNOSTIC_CODES = frozenset({"P2A1702"})


class ConsumerBundleError(ValueError):
    """Admission failure; retain frontend diagnostics without changing bundle bytes."""

    def __init__(self, message: str, *, diagnostics=(), source_name: str | None = None):
        super().__init__(message)
        self._diagnostics = deepcopy(tuple(diagnostics)) if diagnostics else ()
        self.source_name = source_name

    @property
    def diagnostics(self) -> list[dict[str, Any]]:
        return deepcopy(list(self._diagnostics)) if self._diagnostics else []


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
    linked_source: Any = None,
) -> dict[str, Any]:
    library_context = None
    if linked_source is not None:
        from pine2ast.libraries import LinkedSource

        if not isinstance(linked_source, LinkedSource):
            raise ConsumerBundleError("linked_source must be a verified LinkedSource")
        library_context = linked_source.qualifier_context()
        if source != library_context.code:
            raise ConsumerBundleError("source differs from library projection")
    result = parse_source(
        source,
        source_name=source_name,
        created_at_utc_ms=created_at_utc_ms,
        producer_commit=producer_commit,
        library_context=library_context,
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
            f"frontend result contains production-blocking diagnostics{suffix}",
            diagnostics=diagnostics, source_name=source_name,
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
    for name in ("source_manifest", "ast_artifact", "frontend_artifact", "support_profile"):
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
            "required_capabilities": list(_BASE_CONSUMER_CAPABILITIES),
        },
    }
    if library_context is not None:
        body["schema_version"] = LIBRARY_CONSUMER_BUNDLE_SCHEMA_VERSION
        body["library_context"] = library_context.to_dict()
        body["consumer_contract"]["required_capabilities"].append("library_qualifier_context_v1")
        if body["library_context"]["schema_id"] == "pine2ast.library_qualifier_context.v2":
            body["consumer_contract"]["required_capabilities"].append("library_method_projection_v1")
    if ast.get("schema_version") == "2.1":
        body["consumer_contract"]["required_capabilities"].append(METHOD_RECEIVER_CAPABILITY)
    if method_function_feature(ast, context, budget=ASTAdmissionBudget()):
        body["consumer_contract"]["required_capabilities"].append(METHOD_FUNCTION_CAPABILITY)
    if function_overload_feature(ast, context, budget=ASTAdmissionBudget()):
        body["consumer_contract"]["required_capabilities"].append(FUNCTION_OVERLOAD_CAPABILITY)
    if library_overload_feature(body.get("library_context")):
        body["consumer_contract"]["required_capabilities"].append(LIBRARY_OVERLOAD_CAPABILITY)
    body["content_hash"] = content_hash(body)
    verify_consumer_bundle(body, source=source, expected_producer_commit=producer_commit)
    return body


def verify_consumer_bundle(
    bundle: Mapping[str, Any],
    *,
    source: str | None = None,
    expected_producer_commit: str | None = None,
    ast_replay_limits: ASTReplayLimits | None = None,
) -> None:
    from pine2ast.libraries import LibraryError

    try:
        budget = ASTAdmissionBudget(ast_replay_limits)
        if not isinstance(bundle, Mapping):
            raise ConsumerBundleError("consumer bundle must be an object")
        raw_ast = bundle.get("ast")
        raw_context = bundle.get("version_context")
        if not isinstance(raw_ast, Mapping) or not isinstance(raw_context, Mapping):
            raise ConsumerBundleError("bundle core sections are missing")
        # The whole-bundle replay profile belongs only to the new feature.
        # Legacy bundles still need a bounded AST scan to reject concealed
        # receiver fields, without imposing replay-only limits on old facts
        # and linked metadata. Capability probing shares the same work budget.
        raw_contract = bundle.get("consumer_contract")
        raw_caps = (
            raw_contract.get("required_capabilities") if isinstance(raw_contract, Mapping) else None
        )
        requests_receiver = raw_ast.get("schema_version") == "2.1"
        if type(raw_caps) is list:
            for cap in raw_caps:
                budget.charge()
                if type(cap) is str and cap in {METHOD_RECEIVER_CAPABILITY, METHOD_FUNCTION_CAPABILITY}:
                    requests_receiver = True
                    break
        budget.preflight(bundle if requests_receiver else raw_ast)
        has_receiver_feature = receiver_feature(raw_ast, raw_context, budget=budget)
        if bundle.get("schema_id") != CONSUMER_BUNDLE_CONTRACT:
            raise ConsumerBundleError("unsupported consumer bundle schema_id")
        revision = bundle.get("schema_version")
        if not isinstance(revision, str) or revision not in {
            CONSUMER_BUNDLE_SCHEMA_VERSION,
            LIBRARY_CONSUMER_BUNDLE_SCHEMA_VERSION,
        }:
            raise ConsumerBundleError("unsupported consumer bundle schema_version")
        from pine2ast.libraries.qualifier_context import CONTEXT_CAPABILITY, LibraryQualifierContext

        contract = bundle.get("consumer_contract")
        capabilities = (
            contract.get("required_capabilities", []) if isinstance(contract, Mapping) else []
        )
        if (
            not isinstance(capabilities, list)
            or (METHOD_RECEIVER_CAPABILITY in capabilities) != has_receiver_feature
        ):
            raise ConsumerBundleError(
                "method receiver capability and AST feature must match exactly"
            )
        has_method_function_feature = method_function_feature(raw_ast, raw_context, budget=budget)
        if (METHOD_FUNCTION_CAPABILITY in capabilities) != has_method_function_feature:
            raise ConsumerBundleError("explicit method syntax and consumer capability must match exactly")
        has_function_overloads = function_overload_feature(raw_ast, raw_context, budget=budget)
        has_library_overloads = library_overload_feature(bundle.get("library_context"))
        if (FUNCTION_OVERLOAD_CAPABILITY in capabilities) != has_function_overloads:
            raise ConsumerBundleError("function overload syntax and capability must match exactly")
        if (LIBRARY_OVERLOAD_CAPABILITY in capabilities) != has_library_overloads:
            raise ConsumerBundleError("function overload projection and capability must match exactly")
        has_context = "library_context" in bundle
        has_capability = isinstance(capabilities, list) and CONTEXT_CAPABILITY in capabilities
        needs_context = revision == LIBRARY_CONSUMER_BUNDLE_SCHEMA_VERSION
        if has_context != needs_context or has_capability != needs_context:
            raise ConsumerBundleError(
                "consumer version, library context and capability must match exactly"
            )
        library_context = None
        raw_ast = bundle.get("ast")
        ast_metadata = raw_ast.get("producer_metadata", {}) if isinstance(raw_ast, Mapping) else {}
        if not isinstance(ast_metadata, Mapping):
            raise ConsumerBundleError("AST producer metadata must be an object")
        marker = "library_qualifier_context_ref"
        if not needs_context and marker in ast_metadata:
            raise ConsumerBundleError(
                "consumer 1.0 cannot contain a library context provenance marker"
            )
        if needs_context:
            expected_caps = {*_BASE_CONSUMER_CAPABILITIES, CONTEXT_CAPABILITY}
            context_payload = bundle.get("library_context")
            if isinstance(context_payload, Mapping) and context_payload.get("schema_id") == "pine2ast.library_qualifier_context.v2":
                expected_caps.add("library_method_projection_v1")
            if has_receiver_feature:
                expected_caps.add(METHOD_RECEIVER_CAPABILITY)
            if has_method_function_feature:
                expected_caps.add(METHOD_FUNCTION_CAPABILITY)
            if has_function_overloads:
                expected_caps.add(FUNCTION_OVERLOAD_CAPABILITY)
            if has_library_overloads:
                expected_caps.add(LIBRARY_OVERLOAD_CAPABILITY)
            if (
                not isinstance(capabilities, list)
                or len(capabilities) != len(expected_caps)
                or not all(isinstance(cap, str) for cap in capabilities)
                or set(capabilities) != expected_caps
            ):
                raise ConsumerBundleError(
                    "library context consumer capability set must match exactly"
                )
            if (
                not isinstance(contract, Mapping)
                or contract.get("minimum_consumer_version") != "5.0.0rc6"
            ):
                raise ConsumerBundleError("library context requires consumer 5.0.0rc6")
            if (
                set(contract) != {"consumer", "minimum_consumer_version", "required_capabilities"}
                or contract.get("consumer") != "ast2python"
            ):
                raise ConsumerBundleError("library context consumer contract must match exactly")
            if set(bundle) != {
                "schema_id",
                "schema_version",
                "producer",
                "source",
                "version_context",
                "ast",
                "semantic_facts",
                "node_index",
                "diagnostics",
                "release_axes",
                "artifacts",
                "linked_artifacts",
                "consumer_contract",
                "content_hash",
                "library_context",
            }:
                raise ConsumerBundleError("library context bundle fields must match exactly")
            library_context = LibraryQualifierContext.admit(bundle["library_context"])
            if ast_metadata.get(marker) != library_context.to_dict()["content_hash"]:
                raise ConsumerBundleError("AST library context provenance reference mismatch")
            if source is not None and source != library_context.code:
                raise ConsumerBundleError("source differs from library context")
            source = library_context.code
            bundle_version = bundle.get("version_context")
            if (
                not isinstance(bundle_version, Mapping)
                or bundle_version.get("pine_version") != library_context.to_dict()["pine_version"]
            ):
                raise ConsumerBundleError("library context Pine version mismatch")
        elif has_receiver_feature or has_method_function_feature or has_function_overloads:
            expected_caps = set(_BASE_CONSUMER_CAPABILITIES)
            if has_receiver_feature:
                expected_caps.add(METHOD_RECEIVER_CAPABILITY)
            if has_method_function_feature:
                expected_caps.add(METHOD_FUNCTION_CAPABILITY)
            if has_function_overloads:
                expected_caps.add(FUNCTION_OVERLOAD_CAPABILITY)
            if has_library_overloads:
                expected_caps.add(LIBRARY_OVERLOAD_CAPABILITY)
            if (
                not isinstance(contract, Mapping)
                or not all(isinstance(cap, str) for cap in capabilities)
                or len(capabilities) != len(expected_caps)
                or set(capabilities) != expected_caps
                or set(contract)
                != {"consumer", "minimum_consumer_version", "required_capabilities"}
                or contract.get("consumer") != "ast2python"
                or contract.get("minimum_consumer_version") != "5.0.0rc6"
            ):
                raise ConsumerBundleError("method receiver consumer contract must match exactly")
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
        for axis_name, axis in bundle["release_axes"].items():
            if isinstance(axis, Mapping) and axis.get("status") == "FAIL":
                raise ConsumerBundleError(f"release axis {axis_name} failed")
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
        facts_producer = facts.get("producer")
        if facts_producer is not None:
            if not isinstance(facts_producer, Mapping):
                raise ConsumerBundleError("semantic facts producer mismatch")
            if facts_producer.get("name") != producer.get("name"):
                raise ConsumerBundleError("semantic facts producer mismatch")
            if facts_producer.get("version") != producer.get("version"):
                raise ConsumerBundleError("semantic facts producer mismatch")
            if facts_producer.get("commit") != producer_commit:
                raise ConsumerBundleError("semantic facts producer mismatch")
        linked = bundle.get("linked_artifacts")
        if not isinstance(linked, Mapping):
            raise ConsumerBundleError("linked artifacts are missing")
        required_linked = {
            "source_manifest",
            "ast_artifact",
            "frontend_artifact",
            "support_profile",
        }
        if producer_commit is not None and set(linked) != required_linked:
            raise ConsumerBundleError("linked artifact inventory mismatch")
        for name, payload in linked.items():
            if not isinstance(payload, Mapping):
                raise ConsumerBundleError(f"linked artifact {name} is not an object")
            payload_body = {
                key: deepcopy(value) for key, value in payload.items() if key != "content_hash"
            }
            if payload.get("content_hash") != content_hash(payload_body):
                raise ConsumerBundleError(f"linked artifact {name} content hash mismatch")
            if artifacts.get(f"{name}_hash") not in {None, content_hash(payload)}:
                raise ConsumerBundleError(f"linked artifact {name} envelope hash mismatch")
            payload_producer = payload.get("producer")
            if isinstance(payload_producer, Mapping):
                if payload_producer.get("name") != producer.get("name"):
                    raise ConsumerBundleError("linked artifact producer mismatch")
                if payload_producer.get("version") != producer.get("version"):
                    raise ConsumerBundleError("linked artifact producer mismatch")
                if payload_producer.get("commit") != producer_commit:
                    raise ConsumerBundleError("linked artifact producer mismatch")

        if required_linked <= set(linked):
            source_manifest = linked["source_manifest"]
            ast_artifact = linked["ast_artifact"]
            support_profile = linked["support_profile"]
            expected_refs = {
                "source_manifest_ref": source_manifest["content_hash"],
                "ast_ref": ast_artifact["content_hash"],
                "semantic_facts_ref": facts.get("content_hash"),
                "frontend_support_ref": support_profile["content_hash"],
            }
            linked_refs = {
                "ast_artifact": {"source_manifest_ref"},
                "support_profile": {"source_manifest_ref", "ast_ref", "semantic_facts_ref"},
                "frontend_artifact": set(expected_refs),
            }
            for name, ref_names in linked_refs.items():
                payload = linked[name]
                for ref_name in ref_names:
                    if payload.get(ref_name) != expected_refs[ref_name]:
                        raise ConsumerBundleError("linked artifact reference mismatch")
            if source_manifest.get("source_hash") != bundle["source"].get("source_hash"):
                raise ConsumerBundleError("linked artifact reference mismatch")
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
                producer_commit=producer_commit,
                library_context=library_context,
            )
            parsed_diagnostics = diagnostics_payload(parsed_source)
            if not result_ok(parsed_source) or _production_diagnostic_codes(parsed_diagnostics):
                raise ConsumerBundleError("source does not produce a clean frontend result")
            reparsed_ast = ast_payload(parsed_source)
            if content_hash(reparsed_ast) != content_hash(ast):
                raise ConsumerBundleError("source and AST do not match")
            reparsed_facts = semantic_facts_payload(parsed_source, reparsed_ast)
            if content_hash(reparsed_facts) != content_hash(facts):
                raise ConsumerBundleError("source and semantic facts do not match")
        elif has_receiver_feature or has_method_function_feature or has_function_overloads:
            # Callable features share the existing bounded producer replay owner.
            verify_method_receiver_semantics(ast, facts, budget=budget)
    except (InvariantViolation, LibraryError, ASTDecodeError, RecursionError) as exc:
        raise ConsumerBundleError(str(exc)) from exc


def write_consumer_bundle(path: str | Path, source: str, **kwargs: Any) -> dict[str, Any]:
    bundle = build_consumer_bundle(source, **kwargs)
    Path(path).write_text(canonical_json(bundle) + "\n", encoding="utf-8")
    return bundle
