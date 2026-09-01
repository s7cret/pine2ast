#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pine2ast.semantic.completeness import pinned_catalog_static_completeness  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    reports = []
    for version in (5, 6):
        report = pinned_catalog_static_completeness(version)
        payload = report.to_dict()
        reports.append(payload)
        if args.write:
            target = root / "catalog_reports" / f"static_completeness_v{version}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
    print(
        json.dumps(
            {"ok": all(item["ok"] for item in reports), "reports": reports},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(item["ok"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
