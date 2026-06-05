from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, TypedDict, cast

from pine2ast.api import ParseOptions, ast_to_dict, parse_file
from pine2ast.diagnostics import Severity
from pine2ast.testing.ast_compare import strip_spans


class GoldenGenerationResult(TypedDict):
    ast_path: Path
    diagnostics_path: Path
    ok: bool
    diagnostic_count: int


class InvalidDiagnosticContract(TypedDict, total=False):
    fixture: str
    expected_codes: list[str]
    expected_min_severity: str
    notes: str


def _normalize(value: Any, *, ignore_spans: bool) -> Any:
    return strip_spans(value) if ignore_spans else value


def diagnostics_to_contract_payload(
    diagnostics: Iterable[Any], *, ignore_spans: bool = False
) -> list[dict[str, Any]]:
    payload = [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in diagnostics]
    return _normalize(payload, ignore_spans=ignore_spans)


def generate_golden(
    source_path: str | Path,
    *,
    ast_path: str | Path | None = None,
    diagnostics_path: str | Path | None = None,
    ignore_spans: bool = False,
    run_semantic: bool = True,
    indent: int = 2,
) -> GoldenGenerationResult:
    """Parse a Pine fixture and write stable golden AST/diagnostics JSON files."""
    src = Path(source_path)
    ast_out = Path(ast_path) if ast_path else src.with_suffix(".ast.json")
    diag_out = Path(diagnostics_path) if diagnostics_path else src.with_suffix(".diagnostics.json")
    result = parse_file(str(src), ParseOptions(source_name=str(src), run_semantic=run_semantic))
    ast_payload = (
        None
        if result.ast is None
        else _normalize(ast_to_dict(result.ast), ignore_spans=ignore_spans)
    )
    diag_payload = diagnostics_to_contract_payload(result.diagnostics, ignore_spans=ignore_spans)
    ast_out.parent.mkdir(parents=True, exist_ok=True)
    diag_out.parent.mkdir(parents=True, exist_ok=True)
    ast_out.write_text(
        json.dumps(ast_payload, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8"
    )
    diag_out.write_text(
        json.dumps(diag_payload, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8"
    )
    return {
        "ast_path": ast_out,
        "diagnostics_path": diag_out,
        "ok": result.ok,
        "diagnostic_count": len(result.diagnostics),
    }


def compare_golden(
    source_path: str | Path,
    *,
    ast_path: str | Path | None = None,
    ignore_spans: bool = False,
    run_semantic: bool = True,
) -> tuple[bool, str]:
    src = Path(source_path)
    ast_file = Path(ast_path) if ast_path else src.with_suffix(".ast.json")
    if not ast_file.exists():
        return False, f"Golden AST does not exist: {ast_file}"
    result = parse_file(str(src), ParseOptions(source_name=str(src), run_semantic=run_semantic))
    actual = (
        None
        if result.ast is None
        else _normalize(ast_to_dict(result.ast), ignore_spans=ignore_spans)
    )
    expected = _normalize(
        json.loads(ast_file.read_text(encoding="utf-8")), ignore_spans=ignore_spans
    )
    if actual == expected:
        return True, "OK"
    return False, "Golden AST mismatch"


def compare_diagnostics(
    source_path: str | Path,
    *,
    diagnostics_path: str | Path,
    ignore_spans: bool = False,
    run_semantic: bool = True,
) -> tuple[bool, str]:
    """Compare exact diagnostics payload for curated valid fixtures."""
    src = Path(source_path)
    expected_file = Path(diagnostics_path)
    if not expected_file.exists():
        return False, f"Golden diagnostics does not exist: {expected_file}"
    result = parse_file(str(src), ParseOptions(source_name=str(src), run_semantic=run_semantic))
    actual = diagnostics_to_contract_payload(result.diagnostics, ignore_spans=ignore_spans)
    expected = _normalize(
        json.loads(expected_file.read_text(encoding="utf-8")), ignore_spans=ignore_spans
    )
    if actual == expected:
        return True, "OK"
    return False, "Golden diagnostics mismatch"


def validate_invalid_diagnostic_contract(
    source_path: str | Path,
    *,
    diagnostics_path: str | Path | None = None,
    run_semantic: bool = True,
) -> tuple[bool, str]:
    """Validate an invalid fixture against its expected diagnostic-code contract.

    The contract requires every expected diagnostic code to be emitted. Additional
    parser-recovery diagnostics are allowed, because recovery can legitimately
    surface secondary syntax errors after the primary one.
    """
    src = Path(source_path)
    contract_path = (
        Path(diagnostics_path) if diagnostics_path else src.with_suffix(".diagnostics.json")
    )
    if not contract_path.exists():
        return False, f"Diagnostic contract does not exist: {contract_path}"
    raw_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(raw_contract, dict):
        return False, "Diagnostic contract root must be an object"
    contract = cast(InvalidDiagnosticContract, raw_contract)
    expected_codes = list(contract.get("expected_codes", []))
    if not expected_codes:
        return False, "Diagnostic contract has no expected_codes"
    result = parse_file(str(src), ParseOptions(source_name=str(src), run_semantic=run_semantic))
    actual_codes = [diag.code for diag in result.diagnostics]
    missing = [code for code in expected_codes if code not in actual_codes]
    expected_min_severity = contract.get("expected_min_severity", "ERROR")
    require_error = expected_min_severity in {Severity.ERROR.value, Severity.FATAL.value}
    if require_error and result.ok:
        return False, "Invalid fixture parsed without ERROR/FATAL diagnostics"
    if missing:
        return False, "Missing expected diagnostic codes: " + ", ".join(missing)
    severities = {diag.severity for diag in result.diagnostics if diag.code in expected_codes}
    accepted_severities = {
        "FATAL": {Severity.FATAL},
        "ERROR": {Severity.FATAL, Severity.ERROR},
        "WARNING": {Severity.FATAL, Severity.ERROR, Severity.WARNING},
        "INFO": {Severity.FATAL, Severity.ERROR, Severity.WARNING, Severity.INFO},
    }.get(expected_min_severity)
    if accepted_severities is None:
        return False, f"Unsupported expected_min_severity: {expected_min_severity}"
    if not any(sev in accepted_severities for sev in severities):
        return False, "Expected diagnostics were emitted below ERROR severity"
    return True, "OK"
