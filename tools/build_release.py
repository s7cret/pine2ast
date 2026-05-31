#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import build_release_zip

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a versioned Pine2AST release archive")
    parser.add_argument("--version", required=True, help="Release id, e.g. v2_16_0")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out = root / f"pine2ast_interpipe_{args.version}.zip"
    manifest_path = root / f"RELEASE_MANIFEST_{args.version}.json"
    try:
        digest = build_release_zip.build_zip(root, out)
        manifest = build_release_zip.build_manifest(root, out, digest)
    except build_release_zip.ReleaseBuildError as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        return 2
    manifest["release"] = args.version
    manifest["archive_name"] = out.name
    manifest_path.write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(out)
    print(digest)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
