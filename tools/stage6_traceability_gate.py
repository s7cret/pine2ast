"""Command-line gate for concrete Stage 6 requirement evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stage6_integrity import (  # noqa: E402
    canonical_source_hash,
    parse_junit_results,
    verify_traceability,
)


def _text_hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def execute_pytest_evidence(
    root: Path, evidence_dir: Path
) -> tuple[set[str], dict[str, str], dict[str, Any]]:
    """Collect and execute pytest inside the gate instead of trusting supplied files."""

    base = root.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    junit_path = evidence_dir / "pytest-junit.xml"
    common = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
    ]
    collect_command = [*common, "--collect-only", "-q"]
    test_command = [*common, "-q", f"--junitxml={junit_path}"]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    collected_run = subprocess.run(
        collect_command,
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    test_run = subprocess.run(
        test_command,
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    (evidence_dir / "collect.stdout.txt").write_text(collected_run.stdout, encoding="utf-8")
    (evidence_dir / "collect.stderr.txt").write_text(collected_run.stderr, encoding="utf-8")
    (evidence_dir / "test.stdout.txt").write_text(test_run.stdout, encoding="utf-8")
    (evidence_dir / "test.stderr.txt").write_text(test_run.stderr, encoding="utf-8")
    collected = {
        line.strip().replace("\\", "/")
        for line in collected_run.stdout.splitlines()
        if "::" in line and not line.startswith(("=", " "))
    }
    outcomes = parse_junit_results(junit_path) if junit_path.is_file() else {}
    evidence = {
        "origin": "gate_executed_pytest",
        "collect_command": collect_command,
        "test_command": test_command,
        "collect_exit_code": collected_run.returncode,
        "test_exit_code": test_run.returncode,
        "collect_stdout_hash": _text_hash(collected_run.stdout),
        "collect_stderr_hash": _text_hash(collected_run.stderr),
        "test_stdout_hash": _text_hash(test_run.stdout),
        "test_stderr_hash": _text_hash(test_run.stderr),
        "junit_hash": (
            "sha256:" + sha256(junit_path.read_bytes()).hexdigest()
            if junit_path.is_file()
            else None
        ),
    }
    return collected, outcomes, evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collected", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--junit", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.collected is not None or args.junit is not None:
        parser.error("external collected/JUnit evidence is no longer accepted")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    evidence_dir = args.output.parent / f"{args.output.stem}-pytest-evidence"
    collected, outcomes, evidence = execute_pytest_evidence(args.root, evidence_dir)
    report = verify_traceability(manifest, collected, outcomes, root=args.root)
    report["source_root_hash"] = canonical_source_hash(args.root)
    report["pytest_evidence"] = evidence
    if evidence["collect_exit_code"] != 0 or evidence["test_exit_code"] != 0:
        report["status"] = "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
