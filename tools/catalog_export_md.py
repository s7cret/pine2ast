#!/usr/bin/env python3
from __future__ import annotations

import argparse

from pine2ast.reference_catalog import export_catalog_markdown, validate_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Pine v6 reference catalog as Markdown")
    parser.add_argument("output", nargs="?", default="docs/REFERENCE_CATALOG.md")
    args = parser.parse_args()
    validate_catalog()
    out = export_catalog_markdown(args.output)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
