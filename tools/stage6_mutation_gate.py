#!/usr/bin/env python3
"""Kill deterministic mutations in shipped parser and semantic code.

Every mutant is applied to a disposable source-tree copy and exercised by a
focused regression test. The working tree is never edited. A mutant counts as
killed only when pytest reports an ordinary test failure (exit code 1); test
collection or infrastructure errors fail the gate instead of producing a false
kill.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stage6_integrity import canonical_source_hash  # noqa: E402


@dataclass(frozen=True, slots=True)
class SourceMutation:
    name: str
    layer: str
    target: str
    search: str
    replacement: str
    pytest_nodes: tuple[str, ...]


SOURCE_MUTATIONS: tuple[SourceMutation, ...] = (
    SourceMutation(
        name="parser_literal_dispatch_disabled",
        layer="parser",
        target="pine2ast/parser/expressions.py",
        search="        if tok.kind in _LITERAL_KINDS:\n",
        replacement="        if False and tok.kind in _LITERAL_KINDS:\n",
        pytest_nodes=("tests/stage6/test_version_semantic_hardening.py::test_v6_multiline_string",),
    ),
    SourceMutation(
        name="diagnostic_warning_hides_error",
        layer="parser",
        target="pine2ast/api.py",
        search=(
            "    severity_rank = {\n"
            "        Severity.FATAL: 0,\n"
            "        Severity.ERROR: 1,\n"
            "        Severity.WARNING: 2,\n"
            "        Severity.INFO: 3,\n"
            "    }\n"
        ),
        replacement=(
            "    severity_rank = {\n"
            "        Severity.FATAL: 0,\n"
            "        Severity.ERROR: 0,\n"
            "        Severity.WARNING: 0,\n"
            "        Severity.INFO: 0,\n"
            "    }\n"
        ),
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_diagnostic_limit_preserves_error_and_fail_closed_status",
        ),
    ),
    SourceMutation(
        name="method_receiver_identity_removed",
        layer="semantic",
        target="pine2ast/semantic/analyzer.py",
        search="                method_key = (receiver_name, item.name)\n",
        replacement="                method_key = item.name\n",
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_user_methods_with_same_name_are_dispatched_by_receiver_type",
        ),
    ),
    SourceMutation(
        name="generic_type_arity_disabled",
        layer="semantic",
        target="pine2ast/semantic/static_validation.py",
        search="    if expected is None or actual == 0 or actual == expected:\n",
        replacement="    if True or expected is None or actual == 0 or actual == expected:\n",
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_collection_type_references_enforce_generic_arity",
        ),
    ),
    SourceMutation(
        name="mutable_collection_covariance_restored",
        layer="semantic",
        target="pine2ast/semantic/type_model.py",
        search=(
            "        return all(\n"
            '            expected_arg.base in {"any", "unknown"} or expected_arg == actual_arg\n'
            "            for expected_arg, actual_arg in zip(exp.args, act.args, strict=True)\n"
            "        )\n"
        ),
        replacement=(
            "        return all(\n"
            '            expected_arg.base in {"any", "unknown"}\n'
            "            or is_assignable_type(expected_arg.to_string(), actual_arg.to_string())\n"
            "            for expected_arg, actual_arg in zip(exp.args, act.args, strict=True)\n"
            "        )\n"
        ),
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_mutable_collection_assignments_are_invariant",
        ),
    ),
    SourceMutation(
        name="user_callable_binding_ignored",
        layer="semantic",
        target="pine2ast/semantic/version_semantics.py",
        search="        if version >= 5 and name in legacy_names and not is_user_callable:\n",
        replacement="        if version >= 5 and name in legacy_names:\n",
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_v6_version_rules_do_not_reject_user_callable_names_or_parameters",
        ),
    ),
    SourceMutation(
        name="v6_barssince_legacy_rule_removed",
        layer="semantic",
        target="pine2ast/semantic/version_semantics.py",
        search='        "barssince",\n',
        replacement="",
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_v6_rejects_removed_bare_global_builtin_names",
        ),
    ),
    SourceMutation(
        name="receiver_diagnostic_order_unsorted",
        layer="semantic",
        target="pine2ast/semantic/analyzer_validation_calls.py",
        search='f"Method {method_name} expects receiver {sorted(valid_receivers)}, got {actual}."',
        replacement='f"Method {method_name} expects receiver {list(valid_receivers)}, got {actual}."',
        pytest_nodes=(
            "tests/regression/test_rc6_implementation_review.py::test_receiver_diagnostic_is_stable_across_hash_seeds",
        ),
    ),
)


def _hash_text(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _copy_mutant_inputs(root: Path, mutant_root: Path, mutation: SourceMutation) -> None:
    shutil.copytree(root / "pine2ast", mutant_root / "pine2ast", symlinks=True)
    for node in mutation.pytest_nodes:
        test_rel = Path(node.split("::", 1)[0])
        source = root / test_rel
        destination = mutant_root / test_rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        shutil.copy2(pyproject, mutant_root / "pyproject.toml")


def _apply_mutation(mutant_root: Path, mutation: SourceMutation) -> tuple[str, str]:
    target = (mutant_root / mutation.target).resolve()
    try:
        target.relative_to(mutant_root.resolve())
    except ValueError as exc:
        raise ValueError(f"mutation target escapes root: {mutation.target}") from exc
    text = target.read_text(encoding="utf-8")
    occurrences = text.count(mutation.search)
    if occurrences != 1:
        raise ValueError(
            f"mutation {mutation.name} expected one target occurrence, found {occurrences}"
        )
    mutated = text.replace(mutation.search, mutation.replacement, 1)
    target.write_text(mutated, encoding="utf-8")
    return _hash_text(text), _hash_text(mutated)


def _run_mutant(root: Path, mutation: SourceMutation, mutant_root: Path) -> dict[str, Any]:
    _copy_mutant_inputs(root, mutant_root, mutation)
    try:
        original_hash, mutant_hash = _apply_mutation(mutant_root, mutation)
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "mutant": mutation.name,
            "layer": mutation.layer,
            "target": mutation.target,
            "pytest_nodes": list(mutation.pytest_nodes),
            "killed": False,
            "infrastructure_error": str(exc),
        }

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        "-q",
        *mutation.pytest_nodes,
    ]
    environment = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(mutant_root),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )
    completed = subprocess.run(
        command,
        cwd=mutant_root,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    killed = completed.returncode == 1
    infrastructure_error = None
    if completed.returncode not in {0, 1}:
        infrastructure_error = f"pytest infrastructure exit code {completed.returncode}"
    return {
        "mutant": mutation.name,
        "layer": mutation.layer,
        "target": mutation.target,
        "pytest_nodes": list(mutation.pytest_nodes),
        "command": command,
        "original_file_hash": original_hash,
        "mutant_file_hash": mutant_hash,
        "pytest_exit_code": completed.returncode,
        "stdout_hash": _hash_text(completed.stdout),
        "stderr_hash": _hash_text(completed.stderr),
        "killed": killed,
        "infrastructure_error": infrastructure_error,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_source_mutation_gate(
    root: Path | str, *, work_dir: Path | str | None = None
) -> dict[str, Any]:
    """Run all production-source mutants in disposable copies of *root*."""

    base = Path(root).resolve()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="pine2ast-stage6-mutation-")
        workspace = Path(temporary.name)
    else:
        workspace = Path(work_dir).resolve()
        workspace.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    try:
        for index, mutation in enumerate(SOURCE_MUTATIONS, 1):
            mutant_root = workspace / f"{index:02d}-{mutation.name}"
            if mutant_root.exists():
                shutil.rmtree(mutant_root)
            mutant_root.mkdir(parents=True)
            results.append(_run_mutant(base, mutation, mutant_root))
    finally:
        if temporary is not None:
            temporary.cleanup()

    survivors = [row["mutant"] for row in results if not row["killed"]]
    infrastructure_errors = [
        {"mutant": row["mutant"], "error": row["infrastructure_error"]}
        for row in results
        if row.get("infrastructure_error")
    ]
    return {
        "schema_id": "pine2ast.stage6.mutation.v2",
        "mutation_kind": "production_source",
        "source_root_hash": canonical_source_hash(base),
        "mutation_definitions": [asdict(mutation) for mutation in SOURCE_MUTATIONS],
        "mutants": len(results),
        "killed": sum(bool(row["killed"]) for row in results),
        "survivors": survivors,
        "infrastructure_errors": infrastructure_errors,
        "results": results,
    }


def main() -> int:
    report = run_source_mutation_gate(ROOT)
    reports = ROOT / "stage6_reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "mutation-gate.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if not report["survivors"] and not report["infrastructure_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
