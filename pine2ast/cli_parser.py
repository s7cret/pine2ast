from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pine2ast")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse")
    p_parse.add_argument("path")
    p_parse.add_argument("--json", dest="json_path")
    p_parse.add_argument("--no-semantic", action="store_true")
    p_parse.add_argument("--tokens", action="store_true")
    p_parse.add_argument("--strict-builtin-namespaces", action="store_true")
    p_parse.add_argument("--runtime-contract-v1-4", action="store_true")

    p_tokens = sub.add_parser("tokens")
    p_tokens.add_argument("path")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("path")
    p_validate.add_argument("--strict-builtin-namespaces", action="store_true")
    p_validate.add_argument("--runtime-contract-v1-4", action="store_true")

    p_symbols = sub.add_parser("dump-symbols")
    p_symbols.add_argument("path")
    p_symbols.add_argument("--json", action="store_true")
    p_symbols.add_argument("--strict-builtin-namespaces", action="store_true")

    p_fixture = sub.add_parser("test-fixture")
    p_fixture.add_argument("path")
    p_fixture.add_argument("--strict-builtin-namespaces", action="store_true")

    p_bench = sub.add_parser("bench")
    p_bench.add_argument("path")
    p_bench.add_argument("--repeat", type=int, default=20)
    p_bench.add_argument("--json", dest="json_path")
    p_bench.add_argument("--baseline")
    p_bench.add_argument("--no-semantic", action="store_true")

    p_perf = sub.add_parser("perf-baseline")
    p_perf.add_argument("path")
    p_perf.add_argument("--repeat", type=int, default=20)
    p_perf.add_argument("--json", dest="json_path")
    p_perf.add_argument("--baseline")
    p_perf.add_argument("--no-semantic", action="store_true")

    p_corpus = sub.add_parser("validate-corpus")
    p_corpus.add_argument("path")
    p_corpus.add_argument("--json", dest="json_path")
    p_corpus.add_argument("--no-semantic", action="store_true")

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("path")
    p_inspect.add_argument("--json", dest="json_path")
    p_inspect.add_argument("--no-semantic", action="store_true")
    p_inspect.add_argument("--strict-builtin-namespaces", action="store_true")
    p_inspect.add_argument("--runtime-contract-v1-4", action="store_true")
    p_inspect.add_argument("--openpine-contract", action="store_true")
    p_inspect.add_argument("--semantic-snapshot", action="store_true")

    p_snapshot = sub.add_parser("semantic-snapshot")
    p_snapshot.add_argument("path")
    p_snapshot.add_argument("--json", dest="json_path")
    p_snapshot.add_argument("--strict-builtin-namespaces", action="store_true")
    p_snapshot.add_argument("--runtime-contract-v1-4", action="store_true")
    p_snapshot.add_argument("--no-semantic", action="store_true")
    p_snapshot.add_argument("--no-node-facts", action="store_true")

    p_contract_schema = sub.add_parser("contract-schema")
    p_contract_schema.add_argument("--json", dest="json_path")

    p_contract = sub.add_parser("contract-check")
    p_contract.add_argument("path")
    p_contract.add_argument("--json", dest="json_path")
    p_contract.add_argument("--no-semantic", action="store_true")
    p_contract.add_argument("--strict-builtin-namespaces", action="store_true")
    p_contract.add_argument("--runtime-contract-v1-4", action="store_true")
    p_contract.add_argument("--no-openpine-contract", action="store_true")

    p_schema = sub.add_parser("schema-check")
    p_schema.add_argument("path")
    p_schema.add_argument("--json", dest="json_path")
    p_schema.add_argument("--no-semantic", action="store_true")
    p_schema.add_argument("--strict-builtin-namespaces", action="store_true")
    p_schema.add_argument("--runtime-contract-v1-4", action="store_true")

    p_diag_report = sub.add_parser("diagnostics-report")
    p_diag_report.add_argument("path")
    p_diag_report.add_argument("--json", dest="json_path")
    p_diag_report.add_argument("--no-semantic", action="store_true")
    p_diag_report.add_argument("--strict-builtin-namespaces", action="store_true")
    p_diag_report.add_argument("--runtime-contract-v1-4", action="store_true")

    p_sarif = sub.add_parser("sarif")
    p_sarif.add_argument("path")
    p_sarif.add_argument("--json", dest="json_path")
    p_sarif.add_argument("--no-semantic", action="store_true")
    p_sarif.add_argument("--strict-builtin-namespaces", action="store_true")

    p_semantic_report = sub.add_parser("semantic-report")
    p_semantic_report.add_argument("path")
    p_semantic_report.add_argument("--json", dest="json_path")
    p_semantic_report.add_argument("--include-builtins", action="store_true")
    p_semantic_report.add_argument("--strict-builtin-namespaces", action="store_true")

    p_diag_diff = sub.add_parser("diagnostics-diff")
    p_diag_diff.add_argument("current_json")
    p_diag_diff.add_argument("baseline_json")

    p_quality = sub.add_parser("quality-gate")
    p_quality.add_argument("path")
    p_quality.add_argument("--json", dest="json_path")
    p_quality.add_argument("--no-semantic", action="store_true")
    p_quality.add_argument("--strict-builtin-namespaces", action="store_true")

    p_builtin_coverage = sub.add_parser("builtin-coverage")
    p_builtin_coverage.add_argument("--json", dest="json_path")

    p_release = sub.add_parser("release-report")
    p_release.add_argument("--root", default=".")
    p_release.add_argument("--json", dest="json_path")
    p_release.add_argument("--min-v5-signature-ready-ratio", type=float, default=1.0)
    p_release.add_argument("--min-v6-signature-ready-ratio", type=float, default=1.0)

    p_catalog = sub.add_parser("catalog")
    p_catalog.add_argument("action", choices=["validate", "export-md"])
    p_catalog.add_argument("output", nargs="?", default="docs/REFERENCE_CATALOG.md")

    p_matrix = sub.add_parser("matrix")
    p_matrix.add_argument("action", choices=["validate"])

    p_official = sub.add_parser("official-reference")
    p_official.add_argument("action", choices=["fetch", "diff", "gate"])
    p_official.add_argument("--version", type=int, choices=[5, 6], default=6)
    p_official.add_argument("--official-json")
    p_official.add_argument("--baseline")
    p_official.add_argument("--json", dest="json_path")
    p_official.add_argument("--timeout", type=float, default=20.0)

    p_golden = sub.add_parser("golden")
    p_golden.add_argument("path")
    p_golden.add_argument("--ast")
    p_golden.add_argument("--diagnostics")
    p_golden.add_argument("--ignore-spans", action="store_true")
    p_golden.add_argument("--compare", action="store_true")
    p_golden.add_argument("--no-semantic", action="store_true")
    p_golden.add_argument("--strict-builtin-namespaces", action="store_true")
    return parser
