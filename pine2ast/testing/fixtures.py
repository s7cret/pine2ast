from __future__ import annotations

from pathlib import Path


def read_fixture(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")
