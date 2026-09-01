from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Mapping

from .introspection import diagnostics_payload, effective_version, parse_source, result_ok
from .model import GateFinding, GateResult, content_hash


def load_historical_manifest() -> dict[str, Any]:
    resource = files("pine2ast.hardening.data").joinpath("stage5_historical_corpus_manifest.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_historical_source(filename: str) -> str:
    return (
        files("pine2ast.hardening.data.historical_corpus")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


def _semantic_evidence(result: Any) -> tuple[set[str], set[str]]:
    model = getattr(result, "semantic_model", None)
    artifact = getattr(model, "semantic_facts", None)
    rules: set[str] = set()
    coercions: set[str] = set()
    for fact in getattr(artifact, "facts", ()) or ():
        rules.update(str(item) for item in getattr(fact, "semantic_rule_ids", ()) or ())
        for coercion in getattr(fact, "coercions", ()) or ():
            reason = getattr(coercion, "reason", None)
            if reason:
                coercions.add(str(reason))
    return rules, coercions


def run_historical_corpus_gate() -> GateResult:
    manifest = load_historical_manifest()
    findings: list[GateFinding] = []
    sources = manifest.get("sources", [])
    source_ids = {str(item.get("id")) for item in sources if isinstance(item, Mapping)}
    if len(source_ids) != len(sources):
        findings.append(GateFinding("S5_HIST_SOURCE_ID", "historical source IDs must be unique"))
    outcomes: dict[str, dict[str, Any]] = {}
    seen_case_ids: set[str] = set()
    for case in manifest.get("cases", []):
        case_id = str(case.get("id"))
        if case_id in seen_case_ids:
            findings.append(GateFinding("S5_HIST_CASE_DUPLICATE", f"duplicate case id: {case_id}"))
            continue
        seen_case_ids.add(case_id)
        refs = case.get("source_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or any(str(ref) not in source_ids for ref in refs)
        ):
            findings.append(GateFinding("S5_HIST_PROVENANCE", f"{case_id}: invalid source_refs"))
        source = load_historical_source(str(case["file"]))
        result = parse_source(source, source_name=str(case["file"]))
        ok = result_ok(result)
        version = effective_version(result)
        diagnostics = diagnostics_payload(result)
        error_codes = {
            str(item.get("code"))
            for item in diagnostics
            if str(item.get("severity", "")).upper() in {"ERROR", "FATAL"}
        }
        rules, coercions = _semantic_evidence(result)
        if ok != bool(case["expect_ok"]):
            findings.append(
                GateFinding(
                    "S5_HIST_OUTCOME",
                    f"{case_id}: expected ok={case['expect_ok']}, got {ok}",
                    details={"diagnostics": diagnostics},
                )
            )
        if version != int(case["expected_version"]):
            findings.append(
                GateFinding(
                    "S5_HIST_VERSION",
                    f"{case_id}: expected Pine {case['expected_version']}, got {version}",
                )
            )
        missing_errors = set(map(str, case.get("required_error_codes", []))) - error_codes
        forbidden_errors = set(map(str, case.get("forbidden_error_codes", []))) & error_codes
        missing_rules = set(map(str, case.get("required_rule_ids", []))) - rules
        missing_coercions = set(map(str, case.get("required_coercion_reasons", []))) - coercions
        for code in sorted(missing_errors):
            findings.append(GateFinding("S5_HIST_DIAGNOSTIC", f"{case_id}: missing error {code}"))
        for code in sorted(forbidden_errors):
            findings.append(
                GateFinding("S5_HIST_FORBIDDEN_DIAGNOSTIC", f"{case_id}: forbidden error {code}")
            )
        for rule in sorted(missing_rules):
            findings.append(GateFinding("S5_HIST_RULE", f"{case_id}: missing semantic rule {rule}"))
        for reason in sorted(missing_coercions):
            findings.append(
                GateFinding("S5_HIST_COERCION", f"{case_id}: missing coercion {reason}")
            )
        outcomes[case_id] = {
            "ok": ok,
            "version": version,
            "error_codes": sorted(error_codes),
            "semantic_rule_ids": sorted(rules),
            "coercion_reasons": sorted(coercions),
            "source_hash": content_hash(source),
        }
    return GateResult(
        "stage5.historical-corpus",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "case_count": len(outcomes),
            "source_count": len(source_ids),
            "manifest_hash": content_hash(manifest),
            "outcomes": outcomes,
        },
    )


__all__ = [
    "load_historical_manifest",
    "load_historical_source",
    "run_historical_corpus_gate",
]
