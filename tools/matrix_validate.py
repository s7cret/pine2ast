#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pine2ast.reference_catalog import ReferenceCatalogError, validate_matrix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Pine v6 parity matrix")
    parser.add_argument("--catalog", help="Catalog JSON path; defaults to bundled catalog")
    parser.add_argument("--matrix", help="Matrix JSON path; defaults to bundled matrix")
    args = parser.parse_args()
    try:
        validate_matrix(args.catalog, args.matrix)
    except ReferenceCatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("OK parity matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
