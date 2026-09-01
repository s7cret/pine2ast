#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pine2ast.hardening.consumer_bundle import verify_consumer_bundle  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_consumer_bundle.py BUNDLE.json")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    verify_consumer_bundle(payload)
    print(payload["content_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
