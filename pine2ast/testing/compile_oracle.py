from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CompileOracleMetadata:
    version: int = 6
    checked_at: str | None = None
    status: str = "unknown"
    notes: str | None = None
