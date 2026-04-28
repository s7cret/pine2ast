#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Pine2AST release manifest checks")
    parser.add_argument("manifest")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = Path(data["archive"])
    if not archive.is_file():
        print(f"archive missing: {archive}")
        return 2
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != data.get("sha256"):
        print(f"sha256 mismatch: {digest} != {data.get('sha256')}")
        return 2
    with zipfile.ZipFile(archive) as zf:
        names = sorted(zf.namelist())
    if len(names) != data.get("file_count"):
        print(f"file_count mismatch: {len(names)} != {data.get('file_count')}")
        return 2
    checks = data.get("checks", {})
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print("failed checks: " + ", ".join(failed))
        return 1
    print(
        json.dumps(
            {"ok": True, "archive": archive.name, "sha256": digest, "file_count": len(names)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
