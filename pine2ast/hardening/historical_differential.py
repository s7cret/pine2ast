from __future__ import annotations

from typing import Any

from .historical import load_historical_manifest, load_historical_source
from .introspection import effective_version, parse_source, result_ok, version_pack
from .model import GateFinding, GateResult, content_hash


def _rules(result: Any) -> set[str]:
    model = getattr(result, "semantic_model", None)
    artifact = getattr(model, "semantic_facts", None)
    return {
        str(rule)
        for fact in getattr(artifact, "facts", ()) or ()
        for rule in getattr(fact, "semantic_rule_ids", ()) or ()
    }


def run_historical_differential_gate() -> GateResult:
    manifest = load_historical_manifest()
    cases = {str(case["id"]): case for case in manifest["cases"]}
    findings: list[GateFinding] = []
    evidence: list[dict[str, Any]] = []
    for pair in manifest["differential_pairs"]:
        left_case = cases[str(pair["left"])]
        right_case = cases[str(pair["right"])]
        left = parse_source(
            load_historical_source(str(left_case["file"])), source_name=str(left_case["file"])
        )
        right = parse_source(
            load_historical_source(str(right_case["file"])), source_name=str(right_case["file"])
        )
        lv, rv = effective_version(left), effective_version(right)
        lo, ro = result_ok(left), result_ok(right)
        lr, rr = _rules(left), _rules(right)
        if lv == rv:
            findings.append(
                GateFinding("S5_DIFF_VERSION", f"{pair['id']}: version identities collapsed")
            )
        if content_hash(version_pack(lv)) == content_hash(version_pack(rv)):
            findings.append(GateFinding("S5_DIFF_PACK", f"{pair['id']}: adjacent packs collapsed"))
        expect_outcome_difference = bool(pair.get("expect_outcome_difference", False))
        if expect_outcome_difference and lo == ro:
            findings.append(
                GateFinding("S5_DIFF_OUTCOME", f"{pair['id']}: expected outcome difference")
            )
        left_rule = pair.get("left_required_rule")
        right_rule = pair.get("right_required_rule")
        if left_rule and str(left_rule) not in lr:
            findings.append(GateFinding("S5_DIFF_LEFT_RULE", f"{pair['id']}: missing {left_rule}"))
        if right_rule and str(right_rule) not in rr:
            findings.append(
                GateFinding("S5_DIFF_RIGHT_RULE", f"{pair['id']}: missing {right_rule}")
            )
        if (
            not expect_outcome_difference
            and left_rule
            and right_rule
            and str(left_rule) == str(right_rule)
        ):
            findings.append(
                GateFinding("S5_DIFF_RULE_SPEC", f"{pair['id']}: rule identities must differ")
            )
        evidence.append(
            {
                "id": pair["id"],
                "left": {"case": pair["left"], "version": lv, "ok": lo, "rules": sorted(lr)},
                "right": {"case": pair["right"], "version": rv, "ok": ro, "rules": sorted(rr)},
            }
        )
    return GateResult(
        "stage5.historical-differential",
        "PASS" if not findings else "FAIL",
        findings,
        {"pair_count": len(evidence), "pairs": evidence},
    )


__all__ = ["run_historical_differential_gate"]
