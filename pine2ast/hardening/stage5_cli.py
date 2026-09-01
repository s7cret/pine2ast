from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import canonical_json
from .stage5_release_gate import run_all_version_consumer_gate, run_stage5_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pine2ast-stage5")
    sub = parser.add_subparsers(dest="command", required=True)
    gate = sub.add_parser("gate")
    gate.add_argument("--root", default=".")
    gate.add_argument("--fuzz-cases", type=int, default=2000)
    gate.add_argument("--performance-repeats", type=int, default=3)
    gate.add_argument("--no-consumer-mutations", action="store_true")
    gate.add_argument("--coordinated", action="store_true")
    gate.add_argument("--json")
    vectors = sub.add_parser("consumer-vectors")
    vectors.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "consumer-vectors":
        gate_result, bundles = run_all_version_consumer_gate(mutate=True)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        for version, bundle in bundles.items():
            (output / f"pine-v{version}-consumer-bundle.json").write_text(
                canonical_json(bundle) + "\n", encoding="utf-8"
            )
        report = gate_result.to_dict()
        (output / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if gate_result.ok else 1
    report = run_stage5_gate(
        args.root,
        fuzz_cases=args.fuzz_cases,
        performance_repeats=args.performance_repeats,
        mutate_consumers=not args.no_consumer_mutations,
        coordinated=args.coordinated,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["producer_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
