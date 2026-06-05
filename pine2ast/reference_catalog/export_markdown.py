from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pine2ast.reference_catalog.loader import load_entries


def catalog_markdown() -> str:
    entries = load_entries()
    by_priority: dict[str, list] = defaultdict(list)
    for entry in entries:
        by_priority[entry.priority].append(entry)

    lines = [
        "# Pine v6 Reference Catalog",
        "",
        "Scope: amended 6-package Pain Stack P0 catalog. This is a verified-subset/status matrix, not a claim of full Pine v6 or full TradingView compatibility.",
        "",
        "Status fields:",
        "",
        "- `parser_status` — Pine2AST parse/frontend status.",
        "- `semantic_status` — Pine2AST semantic/catalog binding status.",
        "- `codegen_status` — AST2Python lowering status.",
        "- `runtime_status` — PineLib/Backtest Engine runtime status.",
        "- `golden_status` — TradingView/golden evidence status.",
        "",
    ]
    for priority in sorted(by_priority):
        group = sorted(by_priority[priority], key=lambda item: item.id)
        lines.extend([f"## {priority}", ""])
        lines.append("| ID | Kind | Owner | Parser | Semantic | Codegen | Runtime | Golden |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for entry in group:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{entry.id}`",
                        entry.kind,
                        f"`{entry.runtime_owner}`" if entry.runtime_owner else "",
                        entry.parser_status,
                        entry.semantic_status,
                        entry.codegen_status,
                        entry.runtime_status,
                        entry.golden_status,
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_catalog_markdown(path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(catalog_markdown(), encoding="utf-8")
    return out
