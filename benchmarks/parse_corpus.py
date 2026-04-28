from __future__ import annotations

import argparse
from pathlib import Path

from pine2ast.benchmark import bench_corpus_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--repeat", type=int, default=20)
    ap.add_argument("--json", dest="json_path")
    ap.add_argument("--baseline")
    ap.add_argument("--no-semantic", action="store_true")
    ns = ap.parse_args()
    output = bench_corpus_json(
        ns.path, repeat=ns.repeat, baseline_path=ns.baseline, run_semantic=not ns.no_semantic
    )
    if ns.json_path:
        Path(ns.json_path).write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
