"""Run the Pine2AST release quality gate.

Normal dev environments should run with ``--strict-dev-tools``. Minimal agent
sandboxes can still execute the parser-owned release gates and will record
missing optional dev tools explicitly instead of silently pretending they passed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = ".release_gate_reports"


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def pytest_gate_steps(py: str, *, strict_dev_tools: bool) -> list[dict[str, Any]]:
    pytest_available = has_module("pytest")
    pytest_cov_available = has_module("pytest_cov")
    if not pytest_available:
        return [
            skipped("pytest", "pytest is not installed", required=strict_dev_tools),
            skipped("pytest-cov", "pytest-cov is not installed", required=strict_dev_tools),
        ]

    command = [py, "-m", "pytest"]
    if pytest_cov_available:
        command.extend(["--cov=pine2ast", "--cov-report=term-missing"])
        return [run_cmd(command, required=True)]

    return [
        run_cmd(command, required=True),
        skipped("pytest-cov", "pytest-cov is not installed", required=strict_dev_tools),
    ]


def run_cmd(cmd: list[str], *, required: bool, timeout: int = 300) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": cmd,
            "status": "passed" if proc.returncode == 0 else "failed",
            "required": required,
            "ok": proc.returncode == 0 or not required,
            "returncode": proc.returncode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "output_tail": proc.stdout[-8000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "status": "timeout",
            "required": required,
            "ok": not required,
            "returncode": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "output_tail": (exc.stdout or "")[-8000:] if isinstance(exc.stdout, str) else "",
        }


def skipped(name: str, reason: str, *, required: bool) -> dict[str, Any]:
    return {
        "cmd": [name],
        "status": "skipped",
        "required": required,
        "ok": not required,
        "returncode": None,
        "duration_ms": 0,
        "output_tail": reason,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def artifact_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=f"{DEFAULT_ARTIFACT_DIR}/QUALITY_GATE_LOCAL_v2_16_0.json")
    parser.add_argument("--quality-json", default=f"{DEFAULT_ARTIFACT_DIR}/QUALITY_GATE_v2_16_0.json")
    parser.add_argument("--builtin-json", default=f"{DEFAULT_ARTIFACT_DIR}/BUILTIN_COVERAGE_v2_16_0.json")
    parser.add_argument("--test-log", default=f"{DEFAULT_ARTIFACT_DIR}/TEST_RUN_v2_16_0.log")
    parser.add_argument("--coverage-md", default=f"{DEFAULT_ARTIFACT_DIR}/COVERAGE_v2_16_0.md")
    parser.add_argument("--strict-dev-tools", action="store_true")
    parser.add_argument(
        "--allow-subprocess-fallback",
        action="store_true",
        help="Run the stdlib fallback test subprocess before pytest; unsafe for production gates.",
    )
    args = parser.parse_args(argv)
    json_path = artifact_path(args.json)
    quality_json_path = artifact_path(args.quality_json)
    builtin_json_path = artifact_path(args.builtin_json)
    test_log_path = artifact_path(args.test_log)
    coverage_md_path = artifact_path(args.coverage_md)

    py = sys.executable
    steps: list[dict[str, Any]] = []

    steps.extend(pytest_gate_steps(py, strict_dev_tools=args.strict_dev_tools))
    if args.allow_subprocess_fallback:
        test = subprocess.run(
            [py, "tools/run_tests_no_pytest.py"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
        )
        test_log_path.parent.mkdir(parents=True, exist_ok=True)
        test_log_path.write_text(test.stdout, encoding="utf-8")
        steps.append(
            {
                "cmd": [py, "tools/run_tests_no_pytest.py"],
                "status": "passed" if test.returncode == 0 else "failed",
                "required": False,
                "ok": True,
                "returncode": test.returncode,
                "duration_ms": None,
                "output_tail": test.stdout[-8000:],
                "artifact": args.test_log,
                "unsafe_metadata": {
                    "explicit": True,
                    "reason": "subprocess fallback runner enabled",
                },
            }
        )

    for module, command in [
        ("ruff", [py, "-m", "ruff", "check", "."]),
        ("black", [py, "-m", "black", "--check", "."]),
        ("mypy", [py, "-m", "mypy", "pine2ast"]),
    ]:
        if has_module(module):
            steps.append(run_cmd(command, required=args.strict_dev_tools))
        else:
            steps.append(
                skipped(module, f"{module} is not installed", required=args.strict_dev_tools)
            )

    from pine2ast.quality import quality_gate_json
    from pine2ast.semantic.builtin_registry import builtin_registry_coverage_report

    q_started = time.perf_counter()
    q_text = quality_gate_json(ROOT / "tests/fixtures/real_world")
    quality_json_path.parent.mkdir(parents=True, exist_ok=True)
    quality_json_path.write_text(q_text, encoding="utf-8")
    q_payload = json.loads(q_text)
    steps.append(
        {
            "cmd": ["quality_gate_json", "tests/fixtures/real_world"],
            "status": "passed" if q_payload.get("ok") else "failed",
            "required": True,
            "ok": bool(q_payload.get("ok")),
            "returncode": 0 if q_payload.get("ok") else 1,
            "duration_ms": round((time.perf_counter() - q_started) * 1000, 3),
            "output_tail": json.dumps(
                {
                    k: q_payload.get(k)
                    for k in [
                        "ok",
                        "file_count",
                        "ok_count",
                        "error_count",
                        "fatal_count",
                        "warning_count",
                    ]
                },
                ensure_ascii=False,
            ),
            "artifact": args.quality_json,
        }
    )

    b_started = time.perf_counter()
    b_payload = builtin_registry_coverage_report()
    write_json(builtin_json_path, b_payload)
    steps.append(
        {
            "cmd": ["builtin_registry_coverage_report"],
            "status": "passed" if not b_payload.get("missing_expected") else "failed",
            "required": True,
            "ok": not b_payload.get("missing_expected"),
            "returncode": 0 if not b_payload.get("missing_expected") else 1,
            "duration_ms": round((time.perf_counter() - b_started) * 1000, 3),
            "output_tail": json.dumps(
                {
                    k: b_payload.get(k)
                    for k in ["function_count", "variable_count", "missing_expected"]
                },
                ensure_ascii=False,
            ),
            "artifact": args.builtin_json,
        }
    )

    coverage_note = (
        "Coverage was not measured in this sandbox because pytest/pytest-cov are unavailable. "
        "CI enforces pytest-cov with fail_under=90."
        if not (has_module("pytest") and has_module("pytest_cov"))
        else "Coverage is generated by pytest-cov."
    )
    coverage_md_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_md_path.write_text(
        "# Coverage v2.16.0\n\n" + coverage_note + "\n",
        encoding="utf-8",
    )

    report = {
        "schema_version": 1,
        "project": "pine2ast",
        "release": "0.2.16",
        "ok": all(step["ok"] for step in steps),
        "strict_dev_tools": args.strict_dev_tools,
        "allow_subprocess_fallback": args.allow_subprocess_fallback,
        "steps": steps,
        "artifacts": {
            "test_log": args.test_log,
            "quality_gate": args.quality_json,
            "builtin_coverage": args.builtin_json,
            "coverage_note": args.coverage_md,
        },
    }
    write_json(json_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
