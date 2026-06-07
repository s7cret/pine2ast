"""Enrich builtins_v6.json with 5-axis support statuses per TЗ §6.5.

For each function/variable/constant/method/type in the registry, derive:

  - official_known:    always True (data from TradingView reference manual)
  - implemented:       True if entry exists in builtins_v6.json
  - lowerable:         True if codegen_status in {DONE_VERIFIED, IMPLEMENTED_UNVERIFIED}
  - runtime_supported: True if runtime_status in {DONE_VERIFIED, IMPLEMENTED_UNVERIFIED}
  - oracle_verified:   True if golden_status == DONE_VERIFIED

Output: writes support_statuses into the same JSON, alongside existing data,
in a new top-level section. Does NOT mutate existing function/method/etc entries.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILTINS = ROOT / "pine2ast" / "semantic" / "builtins_v6.json"
PARITY = ROOT / "pine2ast" / "reference_catalog" / "parity_matrix.json"

# Build lookup: id -> {parser, semantic, codegen, runtime, oracle}
PARITY_BY_ID: dict[str, dict[str, str]] = {}


def load_parity() -> None:
    d = json.loads(PARITY.read_text(encoding="utf-8"))
    for it in d.get("items", []):
        PARITY_BY_ID[it["id"]] = {
            "parser": it.get("parser_status", "NOT_STARTED"),
            "semantic": it.get("semantic_status", "NOT_STARTED"),
            "codegen": it.get("codegen_status", "NOT_STARTED"),
            "runtime": it.get("runtime_status", "NOT_STARTED"),
            "oracle": it.get("golden_status", "NOT_STARTED"),
        }


def status_for(builtin_id: str) -> dict[str, str | bool]:
    """Return 5-axis support status for one builtin name."""
    parity = PARITY_BY_ID.get(builtin_id)
    if parity is None:
        # Builtin exists in registry but not in parity matrix.
        # Treat as official_known + implemented, but unsupported downstream.
        return {
            "official_known": True,
            "implemented": True,
            "lowerable": False,
            "runtime_supported": False,
            "oracle_verified": False,
            "_note": "no parity_matrix entry",
        }
    return {
        "official_known": True,
        "implemented": parity["parser"] in {"DONE_VERIFIED", "IMPLEMENTED_UNVERIFIED"},
        "lowerable": parity["codegen"]
        in {"DONE_VERIFIED", "IMPLEMENTED_UNVERIFIED"},
        "runtime_supported": parity["runtime"]
        in {"DONE_VERIFIED", "IMPLEMENTED_UNVERIFIED"},
        "oracle_verified": parity["oracle"] == "DONE_VERIFIED",
    }


def main() -> int:
    load_parity()
    data = json.loads(BUILTINS.read_text(encoding="utf-8"))
    # Add support_statuses as a new top-level section
    statuses: dict[str, dict[str, dict[str, str | bool]]] = {
        "functions": {},
        "variables": {},
        "constants": {},
        "methods": {},
        "types": {},
    }
    sections = [
        ("functions", "functions"),
        ("variables", "variables"),
        ("constants", "constants"),
        ("methods", "methods"),
        ("types", "types"),
    ]
    for registry_key, status_key in sections:
        registry = data.get(registry_key, {})
        for name in registry:
            statuses[status_key][name] = status_for(name)
    # Write back
    data["support_statuses"] = {
        "schema_version": "openpine.support_statuses.v1",
        "axes": [
            "official_known",
            "implemented",
            "lowerable",
            "runtime_supported",
            "oracle_verified",
        ],
        "data": statuses,
        "coverage": {
            key: {
                "total": len(v),
                "official_known": sum(1 for s in v.values() if s.get("official_known")),
                "implemented": sum(1 for s in v.values() if s.get("implemented")),
                "lowerable": sum(1 for s in v.values() if s.get("lowerable")),
                "runtime_supported": sum(
                    1 for s in v.values() if s.get("runtime_supported")
                ),
                "oracle_verified": sum(1 for s in v.values() if s.get("oracle_verified")),
            }
            for key, v in statuses.items()
        },
    }
    BUILTINS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cov = data["support_statuses"]["coverage"]
    print("support_statuses added:")
    for k, v in cov.items():
        print(
            f"  {k}: total={v['total']} implemented={v['implemented']} "
            f"lowerable={v['lowerable']} runtime={v['runtime_supported']} "
            f"oracle={v['oracle_verified']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
