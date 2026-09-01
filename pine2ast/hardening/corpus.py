from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .introspection import (
    FrontendIntrospectionError,
    diagnostics_payload,
    effective_version,
    parse_source,
    result_ok,
)
from .model import GateFinding, GateResult, content_hash


def load_corpus_manifest() -> dict[str, Any]:
    resource = files("pine2ast.hardening.data").joinpath("corpus_manifest.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_case_source(filename: str) -> str:
    return files("pine2ast.hardening.data.corpus").joinpath(filename).read_text(encoding="utf-8")


def run_corpus_gate() -> GateResult:
    manifest = load_corpus_manifest()
    findings: list[GateFinding] = []
    source_ids = {item["id"] for item in manifest.get("sources", [])}
    for case in manifest.get("cases", []):
        refs = case.get("source_refs")
        if not isinstance(refs, list) or not refs or any(ref not in source_ids for ref in refs):
            findings.append(
                GateFinding("S4_CORPUS_PROVENANCE", f"{case.get('id')}: invalid source_refs")
            )
    outcomes: dict[str, dict[str, Any]] = {}
    for case in manifest["cases"]:
        source = load_case_source(case["file"])
        result = parse_source(source, source_name=case["file"])
        ok = result_ok(result)
        version: int | None = None
        try:
            version = effective_version(result)
        except FrontendIntrospectionError:
            if not case.get("context_optional", False):
                findings.append(
                    GateFinding("S4_CORPUS_CONTEXT", f"{case['id']}: version context missing")
                )
        if ok != bool(case["expect_ok"]):
            findings.append(
                GateFinding(
                    "S4_CORPUS_OUTCOME",
                    f"{case['id']}: expected ok={case['expect_ok']}, got {ok}",
                    details={"diagnostics": diagnostics_payload(result)},
                )
            )
        if (
            "expected_version" in case
            and version is not None
            and version != case["expected_version"]
        ):
            findings.append(
                GateFinding(
                    "S4_CORPUS_VERSION",
                    f"{case['id']}: expected Pine {case['expected_version']}, got {version}",
                )
            )
        outcomes[case["id"]] = {
            "ok": ok,
            "version": version,
            "diagnostic_codes": [item.get("code") for item in diagnostics_payload(result)],
            "source_hash": content_hash(source),
        }
    return GateResult(
        "stage4.corpus",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "case_count": len(outcomes),
            "outcomes": outcomes,
            "manifest_hash": content_hash(manifest),
        },
    )
