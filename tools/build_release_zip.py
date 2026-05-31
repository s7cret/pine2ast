from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

EXCLUDE_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "tmp",
    "temp",
    "dist",
    "build",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".pyd", ".so", ".zip", ".tar", ".gz", ".tgz"}
SECRET_NAME_FRAGMENTS = {"secret", "secrets", ".env", "id_rsa", "id_ed25519"}
REPRODUCIBLE_TS = (1980, 1, 1, 0, 0, 0)


class ReleaseBuildError(ValueError):
    """Raised when release inputs would produce an invalid archive."""


def should_include(path: Path, *, root: Path | None = None) -> bool:
    check_path = path.relative_to(root) if root is not None else path
    parts = set(check_path.parts)
    if parts & EXCLUDE_PARTS:
        return False
    lowered = path.name.lower()
    if any(fragment in lowered for fragment in SECRET_NAME_FRAGMENTS):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return path.is_file()


def _zip_info(root: Path, file: Path) -> zipfile.ZipInfo:
    rel = file.relative_to(root.parent).as_posix()
    info = zipfile.ZipInfo(rel, REPRODUCIBLE_TS)
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = file.stat().st_mode
    perms = 0o755 if mode & stat.S_IXUSR else 0o644
    info.external_attr = perms << 16
    return info


def build_zip(root: Path, out: Path) -> str:
    root = root.resolve()
    if not root.exists():
        raise ReleaseBuildError(f"release root does not exist: {root}")
    if not root.is_dir():
        raise ReleaseBuildError(f"release root must be a directory: {root}")

    out_resolved = out.resolve()
    files = [
        file
        for file in sorted(root.rglob("*"))
        if file.resolve() != out_resolved and should_include(file, root=root)
    ]
    if not files:
        raise ReleaseBuildError(f"release root contains no includable files: {root}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as zf:
        for file in files:
            zf.writestr(_zip_info(root, file), file.read_bytes())
    data = out.read_bytes()
    return hashlib.sha256(data).hexdigest()


def build_manifest(root: Path, out: Path, digest: str) -> dict[str, Any]:
    with zipfile.ZipFile(out) as zf:
        names = sorted(zf.namelist())
    if not names:
        raise ReleaseBuildError(f"release archive is empty: {out}")
    return {
        "schema_version": 1,
        "archive": str(out),
        "sha256": digest,
        "file_count": len(names),
        "excluded_policy": {
            "parts": sorted(EXCLUDE_PARTS),
            "suffixes": sorted(EXCLUDE_SUFFIXES),
            "secret_name_fragments": sorted(SECRET_NAME_FRAGMENTS),
        },
        "checks": {
            "no_pycache": not any(
                "__pycache__" in n or n.endswith((".pyc", ".pyo")) for n in names
            ),
            "no_temp_or_venv": not any(
                part in {"tmp", "temp", "venv", ".venv"} for n in names for part in Path(n).parts
            ),
            "no_secret_names": not any(
                any(fragment in Path(n).name.lower() for fragment in SECRET_NAME_FRAGMENTS)
                for n in names
            ),
        },
        "files": names,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a reproducible Pine2AST release ZIP")
    parser.add_argument("root", nargs="?", default=str(Path.cwd()))
    parser.add_argument("out", nargs="?")
    parser.add_argument("--manifest", help="Optional JSON manifest/checklist path")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = Path(args.out).resolve() if args.out else root.parent / f"{root.name}.zip"
    try:
        digest = build_zip(root, out)
    except ReleaseBuildError as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        return 2
    print(out)
    print(digest)
    if args.manifest:
        try:
            manifest = build_manifest(root, out, digest)
        except ReleaseBuildError as exc:
            print(f"release manifest failed: {exc}", file=sys.stderr)
            return 2
        Path(args.manifest).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
