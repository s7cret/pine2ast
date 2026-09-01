from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from .consumer_bundle import ConsumerBundleError, verify_consumer_bundle
from .model import GateFinding, GateResult, content_hash

Mutation = Callable[[dict[str, Any]], None]


def _mutations() -> list[tuple[str, Mutation]]:
    def set_version_7(b):
        b["version_context"]["pine_version"] = 7

    def alter_catalog(b):
        b["version_context"]["catalog_hash"] = "sha256:" + "0" * 64

    def alter_ast_version(b):
        b["ast"]["version_context"]["pine_version"] = (
            5 if b["version_context"]["pine_version"] == 6 else 6
        )

    def alter_ast_catalog(b):
        b["ast"]["version_context"]["catalog_hash"] = "sha256:" + "1" * 64

    def remove_fact(b):
        b["semantic_facts"][
            next(
                k
                for k in ("facts", "nodes", "node_facts")
                if isinstance(b["semantic_facts"].get(k), list)
            )
        ].pop()

    def duplicate_fact(b):
        k = next(
            k
            for k in ("facts", "nodes", "node_facts")
            if isinstance(b["semantic_facts"].get(k), list)
        )
        b["semantic_facts"][k].append(deepcopy(b["semantic_facts"][k][0]))

    def alter_ast_hash(b):
        b["artifacts"]["ast_hash"] = "sha256:" + "2" * 64

    def alter_facts_hash(b):
        b["artifacts"]["semantic_facts_hash"] = "sha256:" + "3" * 64

    def alter_index_hash(b):
        b["artifacts"]["node_index_hash"] = "sha256:" + "4" * 64

    def alter_source_hash(b):
        b["source"]["source_hash"] = "sha256:" + "5" * 64

    def remove_schema(b):
        b.pop("schema_id")

    def alter_context_hash(b):
        b["version_context"]["context_hash"] = "sha256:" + "7" * 64

    def alter_content_hash(b):
        b["content_hash"] = "sha256:" + "6" * 64

    return [
        ("version-out-of-range", set_version_7),
        ("catalog-hash", alter_catalog),
        ("ast-version-split-brain", alter_ast_version),
        ("ast-catalog-split-brain", alter_ast_catalog),
        ("missing-semantic-fact", remove_fact),
        ("duplicate-semantic-fact", duplicate_fact),
        ("ast-hash", alter_ast_hash),
        ("facts-hash", alter_facts_hash),
        ("index-hash", alter_index_hash),
        ("source-hash", alter_source_hash),
        ("context-hash", alter_context_hash),
        ("schema-removed", remove_schema),
        ("content-hash", alter_content_hash),
    ]


def run_contract_mutation_gate(bundle: dict[str, Any], *, source: str) -> GateResult:
    findings: list[GateFinding] = []
    killed: list[str] = []
    survived: list[str] = []
    for name, mutate in _mutations():
        candidate = deepcopy(bundle)
        mutate(candidate)
        # Re-seal every structural/data mutant so it cannot be killed merely by the outer
        # checksum. The verifier must detect the violated inner invariant. The dedicated
        # content-hash mutant intentionally remains unsealed.
        if name != "content-hash":
            body = {k: deepcopy(v) for k, v in candidate.items() if k != "content_hash"}
            candidate["content_hash"] = content_hash(body)
        try:
            verify_consumer_bundle(candidate, source=source)
        except (ConsumerBundleError, ValueError, KeyError, StopIteration):
            killed.append(name)
        else:
            survived.append(name)
            findings.append(GateFinding("S4_MUTANT_SURVIVED", f"contract mutant survived: {name}"))
    return GateResult(
        "stage4.contract-mutation",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "mutant_count": len(killed) + len(survived),
            "killed": killed,
            "survived": survived,
            "mutation_set_hash": content_hash([name for name, _ in _mutations()]),
        },
    )
