#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pine2ast.testing.compile_oracle import build_compile_oracle_report, report_to_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate TradingView compile-oracle metadata.")
    parser.add_argument("--path", default="tests/fixtures/compile_oracle")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Return success even when external TradingView checks are still pending.",
    )
    args = parser.parse_args(argv)

    report = build_compile_oracle_report(args.path)
    payload = report_to_dict(report)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.json_path:
        Path(args.json_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    if report.invalid_count:
        return 2
    if report.pending_count and not args.allow_pending:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
