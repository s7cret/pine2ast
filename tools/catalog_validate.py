#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from pine2ast.reference_catalog import ReferenceCatalogError, validate_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Pine v6 reference catalog")
    parser.add_argument("--catalog", help="Catalog JSON path; defaults to bundled catalog")
    args = parser.parse_args()
    try:
        validate_catalog(args.catalog)
    except ReferenceCatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("OK reference catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
