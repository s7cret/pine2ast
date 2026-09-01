from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .introspection import iter_ast_nodes
from .model import content_hash


class InvariantViolation(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise InvariantViolation(code, message)


def _require_mapping(value: object, code: str, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvariantViolation(code, message)
    return value


def validate_version_context(context: Mapping[str, Any]) -> None:
    version = context.get("pine_version")
    if type(version) is not int:
        raise InvariantViolation("S4_VERSION_TYPE", "pine_version must be an integer")
    require(1 <= version <= 6, "S4_VERSION_RANGE", "pine_version must be within 1..6")
    require(
        isinstance(context.get("catalog_hash"), str)
        and str(context["catalog_hash"]).startswith("sha256:"),
        "S4_CATALOG_HASH_MISSING",
        "version context must be bound to a catalog hash",
    )
    stored = context.get("context_hash")
    if stored is not None:
        require(
            isinstance(stored, str) and stored.startswith("sha256:") and len(stored) == 71,
            "S4_CONTEXT_HASH_FORMAT",
            "version context hash must be a sha256 identity",
        )
        expected = content_hash(
            {key: value for key, value in context.items() if key != "context_hash"}
        )
        require(
            stored == expected,
            "S4_CONTEXT_HASH_MISMATCH",
            "version context hash does not match its canonical body",
        )


def validate_ast_identity(ast: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    embedded = _require_mapping(
        ast.get("version_context")
        or ast.get("pine_version_context")
        or ast.get("language_identity"),
        "S4_AST_CONTEXT_MISSING",
        "AST must embed version context",
    )
    embedded_version = embedded.get(
        "pine_version", embedded.get("effective_version", embedded.get("version"))
    )
    require(
        embedded_version == context.get("pine_version"),
        "S4_AST_VERSION_MISMATCH",
        "AST and resolved version context disagree",
    )
    embedded_catalog = embedded.get("catalog_hash")
    require(
        embedded_catalog == context.get("catalog_hash"),
        "S4_AST_CATALOG_MISMATCH",
        "AST and version context catalog hashes disagree",
    )
    if embedded.get("context_hash") is not None and context.get("context_hash") is not None:
        require(
            embedded.get("context_hash") == context.get("context_hash"),
            "S4_AST_CONTEXT_HASH_MISMATCH",
            "AST and resolved version context hashes disagree",
        )


def facts_list(facts: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("facts", "nodes", "node_facts"):
        value = facts.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def validate_semantic_facts(
    ast: Mapping[str, Any],
    facts: Mapping[str, Any],
    *,
    node_index: object | None = None,
) -> None:
    require(
        facts.get("canonical") is not False,
        "S4_FACTS_NONCANONICAL",
        "fallback facts are not release-safe",
    )
    stored_hash = facts.get("content_hash")
    if stored_hash is not None:
        require(
            stored_hash
            == content_hash({key: value for key, value in facts.items() if key != "content_hash"}),
            "S4_FACTS_HASH_MISMATCH",
            "semantic facts content hash does not match its canonical body",
        )

    ast_context = _require_mapping(
        ast.get("version_context")
        or ast.get("pine_version_context")
        or ast.get("language_identity"),
        "S4_AST_CONTEXT_MISSING",
        "AST must embed version context",
    )
    facts_context = _require_mapping(
        facts.get("version_context"),
        "S4_FACTS_CONTEXT_MISSING",
        "semantic facts must embed version context",
    )
    require(
        facts_context.get("pine_version") == ast_context.get("pine_version"),
        "S4_FACTS_VERSION_MISMATCH",
        "semantic facts version does not match the AST version",
    )
    require(
        facts_context.get("catalog_hash") == ast_context.get("catalog_hash"),
        "S4_FACTS_CATALOG_MISMATCH",
        "semantic facts catalog does not match the AST catalog",
    )
    facts_context_ref = facts.get("version_context_ref")
    if facts_context_ref is not None:
        require(
            facts_context_ref == content_hash(facts_context),
            "S4_FACTS_CONTEXT_HASH_MISMATCH",
            "semantic facts version_context_ref does not match its context",
        )

    nodes = list(iter_ast_nodes(ast))
    resolved = facts_list(facts)
    require(bool(resolved), "S4_FACTS_EMPTY", "semantic facts are empty")
    node_ids = [str(item.get("node_id")) for item in resolved]
    require(
        len(node_ids) == len(set(node_ids)),
        "S4_FACT_ID_DUPLICATE",
        "semantic fact node_id is duplicated",
    )
    require(
        len(resolved) == len(nodes),
        "S4_FACT_COVERAGE",
        f"semantic fact coverage is {len(resolved)}/{len(nodes)}",
    )

    expected_nodes: list[Mapping[str, Any]]
    if node_index is None:
        expected_nodes = [
            {
                "node_id": str(node.get("node_id", f"n{index:08d}")),
                "kind": node.get("kind"),
                "span": node.get("span"),
            }
            for index, node in enumerate(nodes)
        ]
    else:
        if not isinstance(node_index, list) or not all(
            isinstance(item, Mapping) for item in node_index
        ):
            raise InvariantViolation(
                "S4_NODE_INDEX_SHAPE",
                "node index must be a list of mappings",
            )
        expected_nodes = [item for item in node_index if isinstance(item, Mapping)]
        require(
            len(expected_nodes) == len(nodes),
            "S4_NODE_INDEX_COVERAGE",
            f"node index coverage is {len(expected_nodes)}/{len(nodes)}",
        )
        for index, item in enumerate(expected_nodes):
            require(
                item.get("ordinal") == index and item.get("node_id") == f"n{index:08d}",
                "S4_NODE_INDEX_IDENTITY",
                "node index ordinal/node_id is not canonical",
            )
            require(
                isinstance(item.get("kind"), str) and isinstance(item.get("span"), Mapping),
                "S4_NODE_INDEX_ROW",
                "node index row is missing kind/span",
            )
        ast_identities = Counter(
            (node.get("kind"), content_hash(node.get("span"))) for node in nodes
        )
        index_identities = Counter(
            (item.get("kind"), content_hash(item.get("span"))) for item in expected_nodes
        )
        require(
            ast_identities == index_identities,
            "S4_NODE_INDEX_AST_MISMATCH",
            "node index kind/span identities do not match the AST",
        )

    for expected, item in zip(expected_nodes, resolved):
        expected_node_id = str(expected.get("node_id"))
        require(
            item.get("node_id") == expected_node_id,
            "S4_FACT_NODE_ID_MISMATCH",
            f"semantic fact node_id does not match AST node {expected_node_id}",
        )
        expected_kind = expected.get("kind")
        actual_kind = item.get("node_kind", item.get("kind"))
        require(
            isinstance(actual_kind, str) and actual_kind == expected_kind,
            "S4_FACT_KIND",
            f"semantic fact kind does not match AST node {expected_node_id}",
        )
        require(
            item.get("span") == expected.get("span"),
            "S4_FACT_SPAN",
            f"semantic fact span does not match AST node {expected_node_id}",
        )

    calls = facts.get("calls")
    if not isinstance(calls, list):
        raise InvariantViolation("S4_CALL_FACTS_SHAPE", "call facts must be a list")
    for call in calls:
        if not isinstance(call, Mapping) or call.get("resolution_status") != "RESOLVED":
            continue
        arguments = call.get("arguments")
        if not isinstance(arguments, list):
            raise InvariantViolation(
                "S4_CALL_ARGUMENTS_SHAPE",
                "resolved call arguments must be a list",
            )
        for argument in arguments:
            require(
                isinstance(argument, Mapping)
                and isinstance(argument.get("actual_type"), str)
                and bool(str(argument.get("actual_type")).strip())
                and isinstance(argument.get("expected_type"), str)
                and bool(str(argument.get("expected_type")).strip()),
                "S4_CALL_ARGUMENT_TYPE_EVIDENCE",
                "resolved call argument must include non-empty actual_type and expected_type",
            )


def validate_consumer_lineage(bundle: Mapping[str, Any]) -> None:
    source = _require_mapping(bundle.get("source"), "S4_BUNDLE_SOURCE", "source envelope missing")
    artifacts = _require_mapping(
        bundle.get("artifacts"), "S4_BUNDLE_ARTIFACTS", "artifact envelope missing"
    )
    for key in ("source_hash",):
        require(
            isinstance(source.get(key), str) and str(source[key]).startswith("sha256:"),
            "S4_BUNDLE_HASH",
            f"{key} missing",
        )
    for key in ("ast_hash", "semantic_facts_hash", "node_index_hash"):
        require(
            isinstance(artifacts.get(key), str) and str(artifacts[key]).startswith("sha256:"),
            "S4_BUNDLE_HASH",
            f"{key} missing",
        )
