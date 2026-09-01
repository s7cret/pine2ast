"""Small oracle runner for Pine2AST compatibility fixtures.

The project already has many pytest fixtures.  This module adds a JSON-friendly
runner for Release 4.0 parity work so OpenPine can keep a shared corpus of scripts
with expected frontend outcomes without coupling every case to pytest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import Severity


@dataclass(frozen=True, slots=True)
class OracleCase:
    id: str
    source: str
    expect_ok: bool = True
    expected_error_codes: tuple[str, ...] = ()
    version: int = 6
    description: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OracleCase":
        return cls(
            id=str(payload["id"]),
            source=str(payload["source"]),
            expect_ok=bool(payload.get("expect_ok", True)),
            expected_error_codes=tuple(
                str(code) for code in payload.get("expected_error_codes", ())
            ),
            version=5 if int(payload.get("version", 6)) == 5 else 6,
            description=(
                str(payload["description"]) if payload.get("description") is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "expect_ok": self.expect_ok,
            "expected_error_codes": list(self.expected_error_codes),
            "description": self.description,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class OracleCaseResult:
    case: OracleCase
    ok: bool
    actual_ok: bool
    error_codes: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def missing_expected_codes(self) -> tuple[str, ...]:
        actual = set(self.error_codes)
        return tuple(code for code in self.case.expected_error_codes if code not in actual)

    @property
    def unexpected_ok_mismatch(self) -> bool:
        return self.actual_ok != self.case.expect_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "ok": self.ok,
            "expected_ok": self.case.expect_ok,
            "actual_ok": self.actual_ok,
            "error_codes": list(self.error_codes),
            "expected_error_codes": list(self.case.expected_error_codes),
            "missing_expected_codes": list(self.missing_expected_codes),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class OracleReport:
    schema_version: str
    results: tuple[OracleCaseResult, ...]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    @property
    def case_count(self) -> int:
        return len(self.results)

    @property
    def failure_count(self) -> int:
        return sum(1 for result in self.results if not result.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "case_count": self.case_count,
            "failure_count": self.failure_count,
            "results": [result.to_dict() for result in self.results],
        }


def _error_codes(result) -> tuple[str, ...]:
    return tuple(
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity in {Severity.ERROR, Severity.FATAL}
    )


def run_oracle_cases(cases: Iterable[OracleCase]) -> OracleReport:
    rows: list[OracleCaseResult] = []
    for case in cases:
        parsed = parse_code(
            case.source,
            ParseOptions(expected_pine_version=case.version, source_name=f"oracle:{case.id}"),
        )
        codes = _error_codes(parsed)
        missing = tuple(code for code in case.expected_error_codes if code not in set(codes))
        ok = parsed.ok == case.expect_ok and not missing
        rows.append(
            OracleCaseResult(
                case=case,
                ok=ok,
                actual_ok=parsed.ok,
                error_codes=codes,
                diagnostics=tuple(d.to_dict() for d in parsed.diagnostics),
            )
        )
    return OracleReport("pine2ast.oracle_report.v1", tuple(rows))


def load_oracle_manifest(path: str | Path) -> tuple[OracleCase, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload if isinstance(payload, list) else [])
    return tuple(OracleCase.from_dict(item) for item in raw_cases)


def oracle_report_json(cases: Iterable[OracleCase], *, indent: int = 2) -> str:
    return json.dumps(run_oracle_cases(cases).to_dict(), ensure_ascii=False, indent=indent)


__all__ = [
    "OracleCase",
    "OracleCaseResult",
    "OracleReport",
    "load_oracle_manifest",
    "oracle_report_json",
    "run_oracle_cases",
]
