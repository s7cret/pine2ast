from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PENDING_STATUS = "pending_external_oracle"
PASS_STATUS = "pass"
EXPECTED_FAIL_STATUS = "fail_expected"
ALLOWED_STATUSES = {PASS_STATUS, EXPECTED_FAIL_STATUS, PENDING_STATUS}


@dataclass(slots=True)
class CompileOracleMetadata:
    version: int = 6
    checked_at: str | None = None
    status: str = "unknown"
    notes: str | None = None


@dataclass(slots=True)
class CompileOracleEntryReport:
    metadata_file: str
    fixture: str
    tradingview_status: str
    pine2ast_status: str | None
    expected: str | None
    checked_at: str | None
    ok: bool
    pending: bool
    message: str | None = None


@dataclass(slots=True)
class CompileOracleReport:
    schema_version: int
    path: str
    metadata_count: int
    fixture_count: int
    ok_count: int
    pending_count: int
    invalid_count: int
    ok: bool
    entries: list[CompileOracleEntryReport]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: metadata root must be an object")
    return data


def build_compile_oracle_report(path: str | Path) -> CompileOracleReport:
    root = Path(path)
    metadata_files = sorted(root.rglob("metadata.json"))
    entries: list[CompileOracleEntryReport] = []

    for metadata_file in metadata_files:
        rel_metadata = metadata_file.relative_to(root).as_posix()
        try:
            data = _load_json(metadata_file)
        except Exception as exc:  # pragma: no cover - defensive CLI path
            entries.append(
                CompileOracleEntryReport(
                    metadata_file=rel_metadata,
                    fixture="<metadata>",
                    tradingview_status="invalid_metadata",
                    pine2ast_status=None,
                    expected=None,
                    checked_at=None,
                    ok=False,
                    pending=False,
                    message=str(exc),
                )
            )
            continue

        checked_at = data.get("checked_at") if isinstance(data.get("checked_at"), str) else None
        for item in _as_list(data.get("policy")):
            if not isinstance(item, dict):
                entries.append(
                    CompileOracleEntryReport(
                        metadata_file=rel_metadata,
                        fixture="<invalid-entry>",
                        tradingview_status="invalid_metadata",
                        pine2ast_status=None,
                        expected=None,
                        checked_at=checked_at,
                        ok=False,
                        pending=False,
                        message="policy entry must be an object",
                    )
                )
                continue

            fixture = item.get("fixture") if isinstance(item.get("fixture"), str) else "<missing>"
            status = item.get("tradingview_status")
            status_text = status if isinstance(status, str) else "missing"
            pending = status_text == PENDING_STATUS
            status_allowed = status_text in ALLOWED_STATUSES
            fixture_exists = (metadata_file.parent / fixture).is_file()
            ok = status_text in {PASS_STATUS, EXPECTED_FAIL_STATUS} and fixture_exists
            message_parts: list[str] = []
            if not fixture_exists:
                message_parts.append("fixture file is missing")
            if not status_allowed:
                message_parts.append(f"unsupported tradingview_status={status_text!r}")
            if pending:
                message_parts.append("external TradingView oracle is pending")

            entries.append(
                CompileOracleEntryReport(
                    metadata_file=rel_metadata,
                    fixture=fixture,
                    tradingview_status=status_text,
                    pine2ast_status=(
                        item.get("pine2ast_status")
                        if isinstance(item.get("pine2ast_status"), str)
                        else None
                    ),
                    expected=(
                        item.get("expected") if isinstance(item.get("expected"), str) else None
                    ),
                    checked_at=checked_at,
                    ok=ok,
                    pending=pending,
                    message="; ".join(message_parts) or None,
                )
            )

    pending_count = sum(1 for entry in entries if entry.pending)
    invalid_count = sum(1 for entry in entries if not entry.ok and not entry.pending)
    ok_count = sum(1 for entry in entries if entry.ok)
    return CompileOracleReport(
        schema_version=1,
        path=str(root),
        metadata_count=len(metadata_files),
        fixture_count=len(entries),
        ok_count=ok_count,
        pending_count=pending_count,
        invalid_count=invalid_count,
        ok=pending_count == 0 and invalid_count == 0,
        entries=entries,
    )


def report_to_dict(report: CompileOracleReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "path": report.path,
        "metadata_count": report.metadata_count,
        "fixture_count": report.fixture_count,
        "ok_count": report.ok_count,
        "pending_count": report.pending_count,
        "invalid_count": report.invalid_count,
        "ok": report.ok,
        "entries": [
            {
                "metadata_file": entry.metadata_file,
                "fixture": entry.fixture,
                "tradingview_status": entry.tradingview_status,
                "pine2ast_status": entry.pine2ast_status,
                "expected": entry.expected,
                "checked_at": entry.checked_at,
                "ok": entry.ok,
                "pending": entry.pending,
                "message": entry.message,
            }
            for entry in report.entries
        ],
    }
