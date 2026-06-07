"""Generate compatibility_matrix.md and compatibility_matrix.json from parity_matrix.json.

Five-axis status (per TЗ §6.5):
  - parser:    DONE_VERIFIED | UNSUPPORTED_DIAGNOSTIC | NOT_STARTED
  - semantic:  DONE_VERIFIED | UNSUPPORTED_DIAGNOSTIC | NOT_STARTED
  - codegen:   DONE_VERIFIED | IMPLEMENTED_UNVERIFIED | UNSUPPORTED_DIAGNOSTIC | NOT_STARTED
  - runtime:   DONE_VERIFIED | IMPLEMENTED_UNVERIFIED | UNSUPPORTED_DIAGNOSTIC | PARTIAL | NOT_STARTED
  - oracle:    DONE_VERIFIED | IMPLEMENTED_UNVERIFIED | NOT_STARTED

Output:
  - pine2ast/compatibility/compatibility_matrix.json (machine-readable)
  - pine2ast/compatibility/compatibility_matrix.md   (human-readable, summary + sample table)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PARITY_PATH = ROOT / "pine2ast" / "reference_catalog" / "parity_matrix.json"
OUT_DIR = ROOT / "pine2ast" / "compatibility"
OUT_JSON = OUT_DIR / "compatibility_matrix.json"
OUT_MD = OUT_DIR / "compatibility_matrix.md"

STATUS_VALUES = {
    "DONE_VERIFIED",
    "IMPLEMENTED_UNVERIFIED",
    "UNSUPPORTED_DIAGNOSTIC",
    "PARTIAL",
    "NOT_STARTED",
}

AXES = ["parser", "semantic", "codegen", "runtime", "golden"]


def load_parity() -> dict[str, Any]:
    return json.loads(PARITY_PATH.read_text(encoding="utf-8"))


def build_matrix(parity: dict[str, Any]) -> dict[str, Any]:
    """Compress parity_matrix.json items into 5-axis compatibility records."""
    items: list[dict[str, Any]] = []
    for it in parity.get("items", []):
        items.append(
            {
                "id": it["id"],
                "category": it.get("official_category", "unknown"),
                "priority": it.get("priority", "P1"),
                "parser": it.get("parser_status", "NOT_STARTED"),
                "semantic": it.get("semantic_status", "NOT_STARTED"),
                "codegen": it.get("codegen_status", "NOT_STARTED"),
                "runtime": it.get("runtime_status", "NOT_STARTED"),
                "oracle": it.get("golden_status", "NOT_STARTED"),
                "runtime_owner": it.get("runtime_owner"),
            }
        )
    summary: dict[str, Counter] = {ax: Counter() for ax in AXES}
    for it in items:
        for ax in AXES:
            val = it.get(ax, "NOT_STARTED")
            if val not in STATUS_VALUES:
                val = "NOT_STARTED"
            summary[ax][val] += 1
    return {
        "schema_version": "openpine.compatibility_matrix.v1",
        "pine_version": parity.get("pine_version", 6),
        "scope": parity.get("scope", "unknown"),
        "axes": AXES,
        "status_values": sorted(STATUS_VALUES),
        "summary": {ax: dict(counter) for ax, counter in summary.items()},
        "items": items,
    }


def render_markdown(matrix: dict[str, Any]) -> str:
    total = len(matrix["items"])
    pine = matrix["pine_version"]
    summary = matrix["summary"]
    lines: list[str] = []
    lines.append(f"# OpenPine Compatibility Matrix — Pine v{pine}\n")
    lines.append(
        f"Total features: **{total}** (scope: `{matrix['scope']}`). "
        f"Schema: `{matrix['schema_version']}`.\n"
    )
    lines.append("Status values per axis:")
    lines.append("")
    for ax in AXES:
        lines.append(f"- **{ax}**: {', '.join(f'`{s}`' for s in matrix['status_values'])}")
    lines.append("")

    # Per-axis summary
    lines.append("## Summary by axis\n")
    lines.append(
        "| Axis | DONE_VERIFIED | IMPLEMENTED_UNVERIFIED | UNSUPPORTED_DIAGNOSTIC | PARTIAL | NOT_STARTED |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for ax in AXES:
        c = summary[ax]
        lines.append(
            f"| {ax} | {c.get('DONE_VERIFIED', 0)} | {c.get('IMPLEMENTED_UNVERIFIED', 0)} | "
            f"{c.get('UNSUPPORTED_DIAGNOSTIC', 0)} | {c.get('PARTIAL', 0)} | {c.get('NOT_STARTED', 0)} |"
        )
    lines.append("")

    # Overall readiness (parser + semantic = DONE_VERIFIED, codegen/runtime/oracle any)
    ready_parser = sum(1 for it in matrix["items"] if it["parser"] == "DONE_VERIFIED")
    ready_semantic = sum(1 for it in matrix["items"] if it["semantic"] == "DONE_VERIFIED")
    ready_codegen = sum(1 for it in matrix["items"] if it["codegen"] == "DONE_VERIFIED")
    ready_runtime = sum(1 for it in matrix["items"] if it["runtime"] == "DONE_VERIFIED")
    ready_oracle = sum(1 for it in matrix["items"] if it["oracle"] == "DONE_VERIFIED")

    def pct(n: int) -> str:
        return f"{n/total*100:.1f}%" if total else "0%"

    lines.append("## Overall readiness\n")
    lines.append(f"- parser DONE_VERIFIED: **{ready_parser}/{total}** ({pct(ready_parser)})")
    lines.append(f"- semantic DONE_VERIFIED: **{ready_semantic}/{total}** ({pct(ready_semantic)})")
    lines.append(f"- codegen DONE_VERIFIED: **{ready_codegen}/{total}** ({pct(ready_codegen)})")
    lines.append(f"- runtime DONE_VERIFIED: **{ready_runtime}/{total}** ({pct(ready_runtime)})")
    lines.append(f"- oracle DONE_VERIFIED: **{ready_oracle}/{total}** ({pct(ready_oracle)})")
    lines.append("")
    lines.append(
        "Reading: parser + semantic at ~100% means *parsing and static checks* are covered. "
        "codegen and runtime are partial by design — full TradingView parity is **not claimed**.\n"
    )

    # Top categories
    cat_counter: Counter = Counter()
    cat_codegen_done: Counter = Counter()
    for it in matrix["items"]:
        cat_counter[it["category"]] += 1
        if it["codegen"] == "DONE_VERIFIED":
            cat_codegen_done[it["category"]] += 1
    lines.append("## Coverage by category\n")
    lines.append("| Category | Total | Codegen DONE | % |")
    lines.append("|---|---:|---:|---:|")
    for cat, n in sorted(cat_counter.items(), key=lambda x: -x[1]):
        done = cat_codegen_done.get(cat, 0)
        lines.append(f"| {cat} | {n} | {done} | {done/n*100:.1f}% |")
    lines.append("")

    # Sample detailed table (first 30 + last 10)
    lines.append("## Sample feature statuses\n")
    lines.append(
        "Five-axis status per feature_id. Full data: `compatibility_matrix.json`. "
        "Subset below — first 30 and last 10.\n"
    )
    lines.append("| Feature | Parser | Semantic | Codegen | Runtime | Oracle |")
    lines.append("|---|---|---|---|---|---|")
    sample = matrix["items"][:30] + (matrix["items"][-10:] if total > 30 else [])
    for it in sample:
        lines.append(
            f"| `{it['id']}` | {it['parser']} | {it['semantic']} | "
            f"{it['codegen']} | {it['runtime']} | {it['oracle']} |"
        )
    lines.append("")

    lines.append("## Regeneration\n")
    lines.append("```bash")
    lines.append("python scripts/generate_compatibility_matrix.py")
    lines.append("```\n")
    return "\n".join(lines)


def main() -> int:
    parity = load_parity()
    matrix = build_matrix(parity)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(matrix), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} ({len(matrix['items'])} items)")
    print(f"wrote {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
