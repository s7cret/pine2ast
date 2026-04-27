from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceMap:
    source_name: str = "<memory>"
