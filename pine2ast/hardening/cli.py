from __future__ import annotations
import argparse
import json
from pathlib import Path
from .release_gate import run_stage4_gate
from .consumer_bundle import write_consumer_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pine2ast-stage4")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gate = sub.add_parser("gate")
    gate.add_argument("--root", default=".")
    gate.add_argument("--json")
    gate.add_argument("--fuzz-cases", type=int, default=2000)
    gate.add_argument("--performance-repeats", type=int, default=3)
    gate.add_argument("--coordinated", action="store_true")
    bundle = sub.add_parser("consumer-bundle")
    bundle.add_argument("source")
    bundle.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "gate":
        report = run_stage4_gate(
            args.root,
            fuzz_cases=args.fuzz_cases,
            performance_repeats=args.performance_repeats,
            coordinated=args.coordinated,
        )
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.json:
            Path(args.json).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0 if report["producer_status"] == "PASS" and not args.coordinated else 1
    source_path = Path(args.source)
    write_consumer_bundle(
        args.output, source_path.read_text(encoding="utf-8"), source_name=source_path.name
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
