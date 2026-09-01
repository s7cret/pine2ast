from __future__ import annotations

from .corpus import load_case_source, load_corpus_manifest
from .introspection import effective_version, parse_source, result_ok, version_pack
from .model import GateFinding, GateResult, content_hash


def run_differential_gate() -> GateResult:
    manifest = load_corpus_manifest()
    cases = {item["id"]: item for item in manifest["cases"]}
    findings: list[GateFinding] = []
    pairs: list[dict] = []
    for pair in manifest["differential_pairs"]:
        left_case, right_case = cases[pair["left"]], cases[pair["right"]]
        left = parse_source(load_case_source(left_case["file"]), source_name=left_case["file"])
        right = parse_source(load_case_source(right_case["file"]), source_name=right_case["file"])
        lv, rv = effective_version(left), effective_version(right)
        lo, ro = result_ok(left), result_ok(right)
        if lv == rv:
            findings.append(
                GateFinding("S4_DIFF_VERSION", f"{pair['id']}: version identities collapsed")
            )
        if lo == ro:
            findings.append(
                GateFinding(
                    "S4_DIFF_OUTCOME",
                    f"{pair['id']}: expected version-sensitive outcome difference",
                )
            )
        lp, rp = version_pack(lv), version_pack(rv)
        if content_hash(lp) == content_hash(rp):
            findings.append(
                GateFinding("S4_DIFF_PACK", f"{pair['id']}: v5/v6 pack hashes are identical")
            )
        pairs.append(
            {
                "id": pair["id"],
                "left": {"version": lv, "ok": lo},
                "right": {"version": rv, "ok": ro},
            }
        )
    return GateResult(
        "stage4.differential",
        "PASS" if not findings else "FAIL",
        findings,
        {"pair_count": len(pairs), "pairs": pairs},
    )
