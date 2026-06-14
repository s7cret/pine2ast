"""Deterministic source-archive helpers for Pine2AST releases.

The public package intentionally has no runtime dependencies, so this module keeps
release artifact checks dependency-free as well.  It does not replace `python -m
build`; it gives CI and maintainers a stable source-tree selection and a zip
builder that never includes caches or local test artifacts.
"""

from __future__ import annotations

import argparse
import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pine2ast._version import __version__

ARCHIVE_SCHEMA = "pine2ast.distribution_manifest.v1"
DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".release_gate_reports",
        ".ruff_cache",
        ".setuptools-build",
        "htmlcov",
        "__pycache__",
        "build",
        "dist",
        ".eggs",
    }
)
DEFAULT_EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})
DEFAULT_EXCLUDED_NAMES = frozenset({".coverage", "coverage.xml", "RELEASE_MANIFEST.json"})
REQUIRED_RELEASE_FILES = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
    "pine2ast/__init__.py",
    "pine2ast/_version.py",
    "docs/README.md",
)


@dataclass(frozen=True, slots=True)
class DistributionFinding:
    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class DistributionManifest:
    schema_version: str
    root: str
    package_version: str
    selected_file_count: int
    excluded_file_count: int
    findings: tuple[DistributionFinding, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "root": self.root,
            "package_version": self.package_version,
            "selected_file_count": self.selected_file_count,
            "excluded_file_count": self.excluded_file_count,
            "finding_count": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in DEFAULT_EXCLUDED_DIRS for part in rel.parts):
        return True
    if any(part.endswith((".egg-info", ".dist-info")) for part in rel.parts):
        return True
    if path.name in DEFAULT_EXCLUDED_NAMES:
        return True
    if path.suffix in DEFAULT_EXCLUDED_SUFFIXES:
        return True
    if path.suffix == ".log":
        return True
    if path.name.endswith(("_CI.json", "_FINAL.json")):
        return True
    return False


def iter_release_files(root: str | Path = ".") -> tuple[Path, ...]:
    """Return deterministic source files selected for a Pine2AST source archive."""

    root_path = Path(root).resolve()
    if not root_path.exists():
        return ()
    files: list[Path] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if _is_excluded(path, root_path):
            continue
        files.append(path)
    return tuple(files)


def build_distribution_manifest(root: str | Path = ".") -> DistributionManifest:
    root_path = Path(root).resolve()
    selected = iter_release_files(root_path)
    excluded = (
        [path for path in root_path.rglob("*") if path.is_file() and _is_excluded(path, root_path)]
        if root_path.exists()
        else []
    )
    selected_rel = {_relative(root_path, path) for path in selected}
    findings: list[DistributionFinding] = []
    if not root_path.exists():
        findings.append(
            DistributionFinding(str(root_path), "missing_root", "Distribution root does not exist")
        )
    for required in REQUIRED_RELEASE_FILES:
        if required not in selected_rel:
            findings.append(
                DistributionFinding(
                    required, "missing_required_file", "Required release file is not selected"
                )
            )
    for path in selected:
        rel = _relative(root_path, path)
        if "__pycache__" in path.parts or path.suffix in DEFAULT_EXCLUDED_SUFFIXES:
            findings.append(
                DistributionFinding(rel, "selected_cache_artifact", "Cache artifact was selected")
            )
        if path.name in DEFAULT_EXCLUDED_NAMES:
            findings.append(
                DistributionFinding(rel, "selected_local_artifact", "Local artifact was selected")
            )
    return DistributionManifest(
        schema_version=ARCHIVE_SCHEMA,
        root=str(root_path),
        package_version=__version__,
        selected_file_count=len(selected),
        excluded_file_count=len(excluded),
        findings=tuple(findings),
    )


def distribution_manifest_json(root: str | Path = ".", *, indent: int = 2) -> str:
    return json.dumps(
        build_distribution_manifest(root).to_dict(), ensure_ascii=False, indent=indent
    )


def _zip_info(archive_name: str, source: Path) -> ZipInfo:
    info = ZipInfo(archive_name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    mode = stat.S_IMODE(source.stat().st_mode) or 0o644
    info.external_attr = (mode & 0xFFFF) << 16
    info.compress_type = ZIP_DEFLATED
    return info


def create_source_zip(
    root: str | Path,
    output: str | Path,
    *,
    root_name: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic source zip from the selected release files."""

    root_path = Path(root).resolve()
    output_path = Path(output).resolve()
    archive_root = root_name or f"pine2ast-{__version__}"
    files = iter_release_files(root_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            rel = _relative(root_path, path)
            arcname = f"{archive_root}/{rel}"
            archive.writestr(_zip_info(arcname, path), path.read_bytes())
    return {
        "schema_version": "pine2ast.source_zip.v1",
        "ok": True,
        "output": str(output_path),
        "root_name": archive_root,
        "file_count": len(files),
        "package_version": __version__,
    }


def create_source_zip_json(
    root: str | Path, output: str | Path, *, root_name: str | None = None, indent: int = 2
) -> str:
    return json.dumps(
        create_source_zip(root, output, root_name=root_name), ensure_ascii=False, indent=indent
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pine2ast.distribution")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_manifest = sub.add_parser("manifest")
    p_manifest.add_argument("--root", default=".")
    p_manifest.add_argument("--json", dest="json_path")
    p_zip = sub.add_parser("build-zip")
    p_zip.add_argument("--root", default=".")
    p_zip.add_argument("--output", required=True)
    p_zip.add_argument("--root-name")
    p_zip.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)
    if args.cmd == "manifest":
        payload = distribution_manifest_json(args.root)
        if args.json_path:
            Path(args.json_path).write_text(payload + "\n", encoding="utf-8")
            print(args.json_path)
        else:
            print(payload)
        return 0 if json.loads(payload).get("ok") else 1
    if args.cmd == "build-zip":
        payload = create_source_zip_json(args.root, args.output, root_name=args.root_name)
        if args.json_path:
            Path(args.json_path).write_text(payload + "\n", encoding="utf-8")
            print(args.json_path)
        else:
            print(payload)
        return 0
    return 1


__all__ = [
    "DistributionFinding",
    "DistributionManifest",
    "build_distribution_manifest",
    "create_source_zip",
    "create_source_zip_json",
    "distribution_manifest_json",
    "iter_release_files",
]


if __name__ == "__main__":
    raise SystemExit(main())
