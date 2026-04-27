#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pine2ast.testing.compile_oracle import build_compile_oracle_report, report_to_dict


def _project_version() -> str | None:
    pyproject = Path("pyproject.toml")
    if not pyproject.is_file():
        return None
    match = re.search(
        r"^version\s*=\s*['\"]([^'\"]+)['\"]",
        pyproject.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1) if match else None


def _is_release_candidate(version: str | None) -> bool:
    return version is not None and "rc" in version.lower()


def _allows_pending_release_suffix(value: str | None) -> bool:
    """Allow honest non-verified production packaging names for pending expansions.

    Pending oracle metadata must never be packaged as `oracle_verified`.  v3.6 uses
    the explicit `oracle_expansion_pending` suffix so release gates can pass while
    the compile-oracle report still records pending external TradingView work.
    """

    return value == "oracle_expansion_pending"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate TradingView compile-oracle metadata.")
    parser.add_argument("--path", default="tests/fixtures/compile_oracle")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Return success even when external TradingView checks are still pending.",
    )
    parser.add_argument(
        "--pending-release-suffix",
        help="Required non-RC suffix for honest pending-oracle production packages.",
    )
    args = parser.parse_args(argv)

    report = build_compile_oracle_report(args.path)
    payload = report_to_dict(report)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if args.json_path:
        Path(args.json_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)

    if args.allow_pending and not (
        _is_release_candidate(_project_version())
        or _allows_pending_release_suffix(args.pending_release_suffix)
    ):
        print(
            "--allow-pending requires an rc package version or "
            "--pending-release-suffix oracle_expansion_pending",
            file=sys.stderr,
        )
        return 2
    if report.invalid_count:
        return 2
    if report.pending_count and not args.allow_pending:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
