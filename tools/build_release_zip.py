from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

EXCLUDE_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return path.is_file()


def build_zip(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(root.rglob("*")):
            if file.resolve() == out.resolve() or not should_include(file):
                continue
            zf.write(file, file.relative_to(root.parent))
    data = out.read_bytes()
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else root.parent / f"{root.name}.zip"
    digest = build_zip(root, out)
    print(out)
    print(digest)
