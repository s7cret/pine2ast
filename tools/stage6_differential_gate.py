#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pine2ast import parse_code  # noqa: E402


def outcome(source: str) -> dict:
    result = parse_code(source)
    ast = result.ast
    context = getattr(ast, "version_context", None) if ast is not None else None
    return {
        "ast": ast is not None,
        "version": getattr(context, "pine_version", None),
        "catalog_hash": getattr(context, "catalog_hash", None),
        "codes": sorted({item.code for item in result.diagnostics}),
        "error": any(item.severity.value in {"ERROR", "FATAL"} for item in result.diagnostics),
    }


pairs = [
    {
        "id": "v2-v3-self-reference",
        "left": ("v2", '//@version=2\nstudy("x")\nx=nz(x[1])\n', False),
        "right": ("v3", '//@version=3\nstudy("x")\nx=nz(x[1])\n', True),
    },
    {
        "id": "v2-v3-forward-reference",
        "left": ("v2", '//@version=2\nstudy("x")\nx=y\ny=close\n', False),
        "right": ("v3", '//@version=3\nstudy("x")\nx=y\ny=close\n', True),
    },
    {
        "id": "v2-v3-bool-arithmetic",
        "left": ("v2", '//@version=2\nstudy("x")\nx=true+1\n', False),
        "right": ("v3", '//@version=3\nstudy("x")\nx=true+1\n', True),
    },
    {
        "id": "v3-v4-typed-na",
        "left": ("v3", '//@version=3\nstudy("x")\nfloat x=na\n', True),
        "right": ("v4", '//@version=4\nstudy("x")\nfloat x=na\n', False),
    },
    {
        "id": "v4-v5-modern-namespace",
        "left": ("v4", '//@version=4\nstudy("x")\nx=ta.sma(close,3)\n', True),
        "right": ("v5", '//@version=5\nindicator("x")\nx=ta.sma(close,3)\n', False),
    },
    {
        "id": "v5-v6-numeric-condition",
        "left": ("v5", '//@version=5\nindicator("x")\nif close\n    x=1\n', False),
        "right": ("v6", '//@version=6\nindicator("x")\nif close\n    x=1\n', True),
    },
    {
        "id": "v5-v6-bool-na",
        "left": ("v5", '//@version=5\nindicator("x")\nbool x=na\n', False),
        "right": ("v6", '//@version=6\nindicator("x")\nbool x=na\n', True),
    },
    {
        "id": "v5-v6-strategy-when",
        "left": (
            "v5",
            '//@version=5\nstrategy("x")\nstrategy.entry("L",strategy.long,when=close>open)\n',
            False,
        ),
        "right": (
            "v6",
            '//@version=6\nstrategy("x")\nstrategy.entry("L",strategy.long,when=close>open)\n',
            True,
        ),
    },
]
rows = []
for pair in pairs:
    row = {"pair_id": pair["id"]}
    for side in ("left", "right"):
        label, source, expected_error = pair[side]
        actual = outcome(source)
        actual["label"] = label
        actual["expected_error"] = expected_error
        actual["pass"] = actual["error"] is expected_error
        row[side] = actual
    row["catalogs_distinct"] = row["left"]["catalog_hash"] != row["right"]["catalog_hash"]
    row["pass"] = row["left"]["pass"] and row["right"]["pass"] and row["catalogs_distinct"]
    rows.append(row)
report = {
    "schema_id": "pine2ast.stage6.differential.v1",
    "pair_count": len(rows),
    "passed": sum(r["pass"] for r in rows),
    "failed": [r["pair_id"] for r in rows if not r["pass"]],
    "pairs": rows,
}
report["content_hash"] = (
    "sha256:"
    + sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)
out = ROOT / "stage6_reports" / "differential-gate.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + "\n")
raise SystemExit(0 if not report["failed"] else 1)
