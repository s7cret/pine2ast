from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pine2ast.diagnostics.diagnostic import Diagnostic, Severity


@dataclass(slots=True)
class DiagnosticReport:
    total: int
    by_severity: dict[str, int] = field(default_factory=dict)
    by_code: dict[str, int] = field(default_factory=dict)
    max_severity: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.by_severity.get(Severity.ERROR.value, 0) == 0
            and self.by_severity.get(Severity.FATAL.value, 0) == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total": self.total,
            "max_severity": self.max_severity,
            "by_severity": dict(sorted(self.by_severity.items())),
            "by_code": dict(sorted(self.by_code.items())),
        }


def summarize_diagnostics(diagnostics: list[Diagnostic]) -> DiagnosticReport:
    order = {
        Severity.INFO.value: 0,
        Severity.WARNING.value: 1,
        Severity.ERROR.value: 2,
        Severity.FATAL.value: 3,
    }
    by_severity: dict[str, int] = {}
    by_code: dict[str, int] = {}
    max_severity: str | None = None
    for diagnostic in diagnostics:
        sev = (
            diagnostic.severity.value
            if isinstance(diagnostic.severity, Severity)
            else str(diagnostic.severity)
        )
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_code[diagnostic.code] = by_code.get(diagnostic.code, 0) + 1
        if max_severity is None or order.get(sev, -1) > order.get(max_severity, -1):
            max_severity = sev
    return DiagnosticReport(len(diagnostics), by_severity, by_code, max_severity)


@dataclass(slots=True)
class DiagnosticDiff:
    current_total: int
    baseline_total: int
    added_by_code: dict[str, int] = field(default_factory=dict)
    removed_by_code: dict[str, int] = field(default_factory=dict)
    changed_by_code: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        # For CI/agent gates, new ERROR/FATAL diagnostics are bad; removing diagnostics is good.
        return not self.added_by_code and not self.changed_by_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "current_total": self.current_total,
            "baseline_total": self.baseline_total,
            "added_by_code": dict(sorted(self.added_by_code.items())),
            "removed_by_code": dict(sorted(self.removed_by_code.items())),
            "changed_by_code": dict(sorted(self.changed_by_code.items())),
        }


def diff_diagnostic_reports(
    current: DiagnosticReport | dict[str, Any], baseline: DiagnosticReport | dict[str, Any]
) -> DiagnosticDiff:
    """Compare two diagnostic summaries by code.

    Accepts either DiagnosticReport instances or dictionaries produced by ``to_dict()`` / CLI JSON.
    This keeps CI baselines stable without depending on exact diagnostic text or source spans.
    """
    cur = current.to_dict() if hasattr(current, "to_dict") else current
    base = baseline.to_dict() if hasattr(baseline, "to_dict") else baseline
    cur_codes = dict(cur.get("by_code", {}))
    base_codes = dict(base.get("by_code", {}))
    added: dict[str, int] = {}
    removed: dict[str, int] = {}
    changed: dict[str, dict[str, int]] = {}
    for code in sorted(set(cur_codes) | set(base_codes)):
        c = int(cur_codes.get(code, 0))
        b = int(base_codes.get(code, 0))
        if c > b:
            added[code] = c - b
        elif c < b:
            removed[code] = b - c
        if c != b:
            changed[code] = {"current": c, "baseline": b, "delta": c - b}
    return DiagnosticDiff(
        current_total=int(cur.get("total", 0)),
        baseline_total=int(base.get("total", 0)),
        added_by_code=added,
        removed_by_code=removed,
        changed_by_code=changed,
    )
