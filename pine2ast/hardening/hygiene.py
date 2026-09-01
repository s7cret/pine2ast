from __future__ import annotations

from pathlib import Path
import re

from .model import GateFinding, GateResult, content_hash

FORBIDDEN_SYMBOLS = (
    "strict_v6",
    "target_version",
    "language_version",
    "compatibility_mode",
    "runtime_contract_v1_4",
    "runtime_contract_profile",
    "implicit_version_rewrite",
    "legacy_4x",
    "strict_5x",
)
FORBIDDEN_PATH_PARTS = ("runtime_contract_v1_4", "unit_legacy_v1_18", "compatibility")


def run_hygiene_gate(root: str | Path) -> GateResult:
    root = Path(root).resolve()
    findings = []
    scanned = []
    ignored = {
        ".git",
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    # The gate covers shipped runtime/package sources. Audit tools and tests
    # intentionally name forbidden legacy identifiers and are verified by their
    # own tests; scanning them would be a vacuous self-match.
    scan_roots = [root / "pine2ast"]
    for path in sorted(p for base in scan_roots if base.exists() for p in base.rglob("*")):
        if any(part in ignored for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            if any(part in FORBIDDEN_PATH_PARTS for part in path.parts):
                findings.append(GateFinding("S4_LEGACY_PATH", f"legacy path remains: {rel}"))
            continue
        if path.suffix not in {".py", ".toml", ".json", ".yml", ".yaml", ".md", ".sh"}:
            continue
        scanned.append(rel)
        text = path.read_text("utf-8", errors="replace")
        # The hardening hygiene source lists forbidden words by design; do not self-report it.
        if rel.endswith("hardening/hygiene.py"):
            continue
        for symbol in FORBIDDEN_SYMBOLS:
            if re.search(rf"\b{re.escape(symbol)}\b", text):
                findings.append(
                    GateFinding("S4_LEGACY_SYMBOL", f"legacy symbol {symbol} remains in {rel}")
                )
    return GateResult(
        "stage4.hygiene",
        "PASS" if not findings else "FAIL",
        findings,
        {"scanned_files": len(scanned), "inventory_hash": content_hash(scanned)},
    )
