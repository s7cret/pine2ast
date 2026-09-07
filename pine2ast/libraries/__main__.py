"""Resolve a deliberately pinned offline lock into a reproducible virtual Pine file."""

from __future__ import annotations
import argparse
from pathlib import Path

from .linker import link_libraries
from .store import LibraryError, LibraryStore, MAX_SOURCE_BYTES, canonical


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pine2ast.libraries")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--expected-lock-hash", required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New output directory; never overwritten"
    )
    args = parser.parse_args(argv)
    try:
        with args.source.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise LibraryError("P2A_LIBRARY_LIMIT", "consumer source exceeds size limit")
        store = LibraryStore.from_directory(args.lock, expected_hash=args.expected_lock_hash)
        linked = link_libraries(data.decode("utf-8"), store, source_name=args.source.name)
        linked.verify()
        # No input file is modified; a prior result cannot be silently replaced.
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "linked.pine").write_text(linked.code, encoding="utf-8")
        (args.output / "linkage.json").write_bytes(canonical(linked.receipt()) + b"\n")
    except (LibraryError, OSError, UnicodeError) as exc:
        parser.exit(1, str(exc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
