"""Dependency-free validation for Pine2AST public integration contracts.

This is intentionally a structural validator, not a full JSON Schema runtime.  It
keeps the published frontend boundaries machine-checkable without adding runtime
dependencies to the package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from pine2ast.api import ParseOptions, parse_file
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.frontend.ids import FRONTEND_CONTRACT, SECTION_CONTRACTS

INSPECT_CONTRACT = "pine2ast.inspect.optimizer.v1"
OPENPINE_CONTRACT = FRONTEND_CONTRACT
AST_CONTRACT = "pine.ast_contract.v1"
SEMANTIC_SNAPSHOT_CONTRACT = "pine2ast.semantic_snapshot.v1"

OPENPINE_SECTION_CONTRACTS: Mapping[str, str] = SECTION_CONTRACTS


@dataclass(frozen=True, slots=True)
class ContractIssue:
    """One deterministic public-contract validation issue."""

    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class ContractValidationReport:
    """Validation result for one payload and its nested public contracts."""

    contract: str
    ok: bool
    issues: tuple[ContractIssue, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "ok": self.ok,
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_TYPE_CHECKS: Mapping[type, Any] = {
    bool: _is_bool,
    int: _is_int,
    str: lambda value: isinstance(value, str),
    list: lambda value: isinstance(value, list),
    dict: lambda value: isinstance(value, dict),
}


def _type_name(expected: type | tuple[type, ...]) -> str:
    if isinstance(expected, tuple):
        return "|".join(item.__name__ for item in expected)
    return expected.__name__


def _matches_type(value: Any, expected: type | tuple[type, ...]) -> bool:
    if isinstance(expected, tuple):
        return any(_matches_type(value, item) for item in expected)
    checker = _TYPE_CHECKS.get(expected)
    if checker is not None:
        return bool(checker(value))
    return isinstance(value, expected)


def _require_key(
    payload: Mapping[str, Any],
    key: str,
    expected: type | tuple[type, ...],
    path: str,
    issues: list[ContractIssue],
) -> Any:
    child_path = f"{path}.{key}" if path else key
    if key not in payload:
        issues.append(ContractIssue(child_path, "missing_key", f"Missing required key: {key}"))
        return None
    value = payload[key]
    if not _matches_type(value, expected):
        issues.append(
            ContractIssue(
                child_path,
                "wrong_type",
                f"Expected {_type_name(expected)}, got {type(value).__name__}",
            )
        )
        return None
    return value


def _require_literal(
    payload: Mapping[str, Any],
    key: str,
    expected: str,
    path: str,
    issues: list[ContractIssue],
) -> None:
    value = _require_key(payload, key, str, path, issues)
    if isinstance(value, str) and value != expected:
        issues.append(
            ContractIssue(
                f"{path}.{key}" if path else key,
                "wrong_literal",
                f"Expected {expected!r}, got {value!r}",
            )
        )


def _validate_producer(payload: Mapping[str, Any], path: str, issues: list[ContractIssue]) -> None:
    producer = _require_key(payload, "producer", dict, path, issues)
    if isinstance(producer, dict):
        _require_key(producer, "name", str, f"{path}.producer", issues)
        _require_key(producer, "version", str, f"{path}.producer", issues)


def _validate_source(payload: Mapping[str, Any], path: str, issues: list[ContractIssue]) -> None:
    source = _require_key(payload, "source", dict, path, issues)
    if isinstance(source, dict):
        _require_key(source, "path", str, f"{path}.source", issues)
        _require_key(source, "name", str, f"{path}.source", issues)


def _validate_diagnostics(
    payload: Mapping[str, Any], path: str, issues: list[ContractIssue]
) -> None:
    diagnostics = _require_key(payload, "diagnostics", list, path, issues)
    if not isinstance(diagnostics, list):
        return
    for index, diagnostic in enumerate(diagnostics):
        diag_path = f"{path}.diagnostics[{index}]"
        if not isinstance(diagnostic, dict):
            issues.append(ContractIssue(diag_path, "wrong_type", "Diagnostic must be an object"))
            continue
        _require_key(diagnostic, "code", str, diag_path, issues)
        _require_key(diagnostic, "message", str, diag_path, issues)
        _require_key(diagnostic, "severity", str, diag_path, issues)


def _validate_openpine_section(
    payload: Mapping[str, Any],
    key: str,
    expected_contract: str,
    path: str,
    issues: list[ContractIssue],
) -> None:
    section = _require_key(payload, key, (dict, type(None)), path, issues)
    if section is None:
        return
    if not isinstance(section, dict):
        return
    section_path = f"{path}.{key}"
    _require_literal(section, "contract", expected_contract, section_path, issues)
    _require_key(section, "profile", str, section_path, issues)


def _validate_openpine(payload: Mapping[str, Any], path: str, issues: list[ContractIssue]) -> None:
    _require_key(payload, "schema_version", int, path, issues)
    _require_literal(payload, "contract", OPENPINE_CONTRACT, path, issues)
    _validate_producer(payload, path, issues)
    _validate_source(payload, path, issues)
    _require_key(payload, "ok", bool, path, issues)
    _validate_diagnostics(payload, path, issues)
    for key, expected in OPENPINE_SECTION_CONTRACTS.items():
        _validate_openpine_section(payload, key, expected, path, issues)


def _validate_inspect(payload: Mapping[str, Any], path: str, issues: list[ContractIssue]) -> None:
    _require_key(payload, "schema_version", int, path, issues)
    _require_literal(payload, "contract", INSPECT_CONTRACT, path, issues)
    _validate_producer(payload, path, issues)
    _validate_source(payload, path, issues)
    _require_key(payload, "script", dict, path, issues)
    _require_key(payload, "ok", bool, path, issues)
    _validate_diagnostics(payload, path, issues)
    for key in (
        "unsupported_features",
        "inputs",
        "strategy_calls",
        "request_calls",
        "plots",
        "alerts",
        "drawings",
    ):
        _require_key(payload, key, list, path, issues)
    _require_key(payload, "dependencies", (dict, type(None)), path, issues)
    embedded = payload.get("openpine_contract")
    if embedded is not None:
        if isinstance(embedded, dict):
            _validate_openpine(embedded, f"{path}.openpine_contract", issues)
        else:
            issues.append(
                ContractIssue(
                    f"{path}.openpine_contract",
                    "wrong_type",
                    "Embedded OpenPine contract must be an object",
                )
            )
    snapshot = payload.get("semantic_snapshot")
    if snapshot is not None:
        if isinstance(snapshot, dict):
            _validate_semantic_snapshot(snapshot, f"{path}.semantic_snapshot", issues)
        else:
            issues.append(
                ContractIssue(
                    f"{path}.semantic_snapshot",
                    "wrong_type",
                    "Embedded semantic snapshot must be an object",
                )
            )


def _validate_semantic_snapshot(
    payload: Mapping[str, Any], path: str, issues: list[ContractIssue]
) -> None:
    _require_key(payload, "schema_version", int, path, issues)
    _require_literal(payload, "contract", SEMANTIC_SNAPSHOT_CONTRACT, path, issues)
    _validate_producer(payload, path, issues)
    _validate_source(payload, path, issues)
    _require_key(payload, "ok", bool, path, issues)
    _require_key(payload, "profile", dict, path, issues)
    _require_key(payload, "diagnostics", dict, path, issues)
    _require_key(payload, "counts", dict, path, issues)
    _require_key(payload, "passes", list, path, issues)
    _require_key(payload, "symbols", list, path, issues)
    _require_key(payload, "scopes", list, path, issues)
    _require_key(payload, "node_facts", list, path, issues)


def _validate_ast(payload: Mapping[str, Any], path: str, issues: list[ContractIssue]) -> None:
    _require_literal(payload, "kind", "Program", path, issues)
    _require_key(payload, "schema_version", str, path, issues)
    _require_key(payload, "language", str, path, issues)
    _require_key(payload, "version_context", dict, path, issues)
    _require_key(payload, "producer_metadata", dict, path, issues)


def _detect_contract(payload: Mapping[str, Any], expected_contract: str | None = None) -> str:
    if expected_contract:
        return expected_contract
    contract = payload.get("contract")
    if isinstance(contract, str):
        return contract
    if payload.get("kind") == "Program":
        return AST_CONTRACT
    return "unknown"


def validate_contract_payload(
    payload: Mapping[str, Any],
    *,
    expected_contract: str | None = None,
) -> ContractValidationReport:
    """Validate a public Pine2AST/OpenPine contract payload.

    The validator supports three public integration surfaces:
    `pine.ast_contract.v1`, `pine2ast.inspect.optimizer.v1`,
    `pine2ast.semantic_snapshot.v1`, and `openpine.frontend.v2`.
    Unknown contracts produce a failed report rather
    than silently succeeding.
    """

    contract = _detect_contract(payload, expected_contract)
    issues: list[ContractIssue] = []
    if contract == INSPECT_CONTRACT:
        _validate_inspect(payload, "$", issues)
    elif contract == OPENPINE_CONTRACT:
        _validate_openpine(payload, "$", issues)
    elif contract == SEMANTIC_SNAPSHOT_CONTRACT:
        _validate_semantic_snapshot(payload, "$", issues)
    elif contract == AST_CONTRACT:
        _validate_ast(payload, "$", issues)
    else:
        issues.append(ContractIssue("$", "unknown_contract", f"Unsupported contract: {contract}"))
    return ContractValidationReport(contract=contract, ok=not issues, issues=tuple(issues))


def contract_check_file_payload(
    path: str | Path,
    *,
    options: ParseOptions | None = None,
    include_openpine_contract: bool = True,
) -> dict[str, Any]:
    """Parse a Pine file and validate the generated inspect/OpenPine contract."""

    source_path = Path(path)
    result = parse_file(str(source_path), options or ParseOptions(source_name=str(source_path)))
    payload = build_inspect_payload(
        result,
        source_path=str(source_path),
        source_name=source_path.name,
        include_openpine_contract=include_openpine_contract,
    )
    report = validate_contract_payload(payload)
    return {
        "ok": result.ok and report.ok,
        "parse_ok": result.ok,
        "contract_ok": report.ok,
        "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
        "contract_report": report.to_dict(),
    }


def contract_check_json(path: str | Path, *, indent: int = 2, **kwargs: Any) -> str:
    return json.dumps(
        contract_check_file_payload(path, **kwargs), ensure_ascii=False, indent=indent
    )


__all__ = [
    "AST_CONTRACT",
    "INSPECT_CONTRACT",
    "OPENPINE_CONTRACT",
    "SEMANTIC_SNAPSHOT_CONTRACT",
    "OPENPINE_SECTION_CONTRACTS",
    "ContractIssue",
    "ContractValidationReport",
    "validate_contract_payload",
    "contract_check_file_payload",
    "contract_check_json",
]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m pine2ast.contracts.validation")
    parser.add_argument("path")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--no-openpine-contract", action="store_true")
    args = parser.parse_args(argv)
    payload = contract_check_file_payload(
        args.path,
        include_openpine_contract=not args.no_openpine_contract,
    )
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_path:
        Path(args.json_path).write_text(output + "\n", encoding="utf-8")
        print(args.json_path)
    else:
        print(output)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
