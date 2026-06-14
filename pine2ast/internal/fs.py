from __future__ import annotations

import os
from pathlib import Path


def pine_files(root: str | Path) -> list[Path]:
    """Return `.pine` files under `root` in deterministic order."""

    path = Path(root)
    if path.suffix == ".pine":
        return [path]
    rows: list[Path] = []
    for dirpath, _, filenames in os.walk(path):
        for filename in filenames:
            if filename.endswith(".pine"):
                rows.append(Path(dirpath) / filename)
    return sorted(rows)
