from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pine2ast.api import (
    ParseOptions,
    ast_to_json,
    diagnostics_to_json,
    parse_file,
    runtime_contract_v1_4_options,
)
from pine2ast.ast.nodes import DeclarationStatement, Literal
from pine2ast.semantic.extractors import (
    extract_alertconditions,
    extract_dependencies,
    extract_drawing_calls,
    extract_inputs,
    extract_plots,
    extract_request_calls,
    extract_strategy_calls,
)
from pine2ast.semantic.type_infer import callee_name
from pine2ast.benchmark import bench_corpus_json, perf_baseline_json
from pine2ast.corpus import validate_corpus_json
from pine2ast.testing.golden import compare_golden, generate_golden
from pine2ast.diagnostics import Severity, format_diagnostic
from pine2ast.ast.schema import validate_ast_schema
from pine2ast.diagnostics.reports import diff_diagnostic_reports, summarize_diagnostics
from pine2ast.quality import quality_gate_json
from pine2ast.diagnostics.sarif import diagnostics_to_sarif_json
from pine2ast.semantic.reports import semantic_report
from pine2ast.semantic.builtin_registry import builtin_registry_coverage_report
from pine2ast.reference_catalog import (
    ReferenceCatalogError,
    export_catalog_markdown,
    validate_catalog,
    validate_matrix,
)
from pine2ast import __version__


def _span_dict(span):
    return span.to_dict() if hasattr(span, "to_dict") else None


def _simple_call(node):
    return {
        "name": callee_name(node.callee),
        "arg_count": len(node.arguments),
        "span": _span_dict(node.span),
    }


def _dependency_dict(dep):
    return {
        "imports": dep.imports,
        "import_aliases": dep.import_aliases,
        "namespaces": dep.namespaces,
        "builtin_calls": dep.builtin_calls,
        "user_function_calls": dep.user_function_calls,
        "method_calls": dep.method_calls,
        "udt_constructors": dep.udt_constructors,
        "external_calls": dep.external_calls,
        "unknown_calls": dep.unknown_calls,
    }


def _input_dict(item):
    return {
        "name": item.name,
        "title": item.title,
        "input_function": item.input_function,
        "default_value": item.default_value,
        "minval": item.minval,
        "maxval": item.maxval,
        "step": item.step,
        "options": item.options,
        "span": _span_dict(item.span),
    }


def _script_dict(ast):
    if ast is None or not isinstance(ast.declaration, DeclarationStatement):
        return {"type": None, "title": None, "pine_version": None}
    title = None
    if ast.declaration.call.arguments:
        first_arg = ast.declaration.call.arguments[0]
        if first_arg.name is None and isinstance(first_arg.value, Literal):
            title = first_arg.value.value
    return {
        "type": ast.declaration.script_type,
        "title": title,
        "pine_version": ast.version or ast.language_version,
    }


def _unsupported_features(result) -> list[dict[str, object]]:
    # v1 keeps unsupported-feature reporting derived from diagnostics only; semantic
    # rules stay in the semantic layer and parser recovery remains unchanged.
    return [
        {
            "code": d.code,
            "severity": d.severity.value,
            "message": d.message,
            "span": _span_dict(d.span),
        }
        for d in result.diagnostics
        if d.code.startswith("P2A") and d.severity.value in {"ERROR", "FATAL"}
    ]


def _exit_code(result) -> int:
    if any(d.severity is Severity.FATAL for d in result.diagnostics):
        return 2
    if any(d.severity is Severity.ERROR for d in result.diagnostics):
        return 1
    return 0


def _parse_options(args, **overrides: object) -> ParseOptions:
    values = {
        "collect_tokens": getattr(args, "tokens", False),
        "run_semantic": not getattr(args, "no_semantic", False),
        "source_name": args.path,
        "strict_builtin_namespaces": getattr(args, "strict_builtin_namespaces", False),
    }
    values.update(overrides)
    if getattr(args, "runtime_contract_v1_4", False):
        return runtime_contract_v1_4_options(**values)
    return ParseOptions(**values)


def main(argv: list[str] | None = None) -> int:
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

    p_catalog = sub.add_parser("catalog")
    p_catalog.add_argument("action", choices=["validate", "export-md"])
    p_catalog.add_argument("output", nargs="?", default="docs/REFERENCE_CATALOG.md")

    p_matrix = sub.add_parser("matrix")
    p_matrix.add_argument("action", choices=["validate"])

    p_golden = sub.add_parser("golden")
    p_golden.add_argument("path")
    p_golden.add_argument("--ast")
    p_golden.add_argument("--diagnostics")
    p_golden.add_argument("--ignore-spans", action="store_true")
    p_golden.add_argument("--compare", action="store_true")
    p_golden.add_argument("--no-semantic", action="store_true")
    p_golden.add_argument("--strict-builtin-namespaces", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "catalog":
        try:
            if args.action == "validate":
                validate_catalog()
                print("OK reference catalog")
            elif args.action == "export-md":
                validate_catalog()
                print(export_catalog_markdown(args.output))
        except ReferenceCatalogError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.cmd == "matrix":
        try:
            validate_matrix()
        except ReferenceCatalogError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("OK parity matrix")
        return 0

    if args.cmd == "perf-baseline":
        output = perf_baseline_json(
            args.path,
            repeat=args.repeat,
            baseline_path=args.baseline,
            run_semantic=not args.no_semantic,
        )
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0

    if args.cmd == "builtin-coverage":
        output = json.dumps(builtin_registry_coverage_report(), ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0

    if args.cmd == "sarif":
        result = parse_file(
            args.path,
            ParseOptions(
                run_semantic=not args.no_semantic,
                source_name=args.path,
                strict_builtin_namespaces=getattr(args, "strict_builtin_namespaces", False),
            ),
        )
        output = diagnostics_to_sarif_json(
            result.diagnostics, source_name=args.path, tool_version=__version__
        )
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return _exit_code(result)

    if args.cmd == "semantic-report":
        result = parse_file(
            args.path,
            ParseOptions(
                run_semantic=True,
                source_name=args.path,
                strict_builtin_namespaces=getattr(args, "strict_builtin_namespaces", False),
            ),
        )
        payload = {
            "ok": result.ok,
            "diagnostics": [d.to_dict() for d in result.diagnostics],
            "semantic": semantic_report(
                result.semantic_model, include_builtins=args.include_builtins
            ).to_dict(),
        }
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return _exit_code(result)

    if args.cmd == "diagnostics-diff":
        current_payload = json.loads(Path(args.current_json).read_text(encoding="utf-8"))
        baseline_payload = json.loads(Path(args.baseline_json).read_text(encoding="utf-8"))
        current_summary = current_payload.get("summary", current_payload)
        baseline_summary = baseline_payload.get("summary", baseline_payload)
        diff = diff_diagnostic_reports(current_summary, baseline_summary)
        print(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2))
        return 0 if diff.ok else 1

    if args.cmd == "quality-gate":
        output = quality_gate_json(args.path, run_semantic=not args.no_semantic)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        payload = json.loads(output)
        return 0 if payload.get("ok") else 1

    if args.cmd == "schema-check":
        result = parse_file(args.path, _parse_options(args))
        schema_report = validate_ast_schema(result.ast) if result.ast else None
        payload = {
            "parse_ok": result.ok,
            "schema": schema_report.to_dict() if schema_report else None,
            "diagnostics": [d.to_dict() for d in result.diagnostics],
        }
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0 if schema_report is not None and schema_report.ok and result.ast is not None else 1

    if args.cmd == "diagnostics-report":
        result = parse_file(args.path, _parse_options(args))
        diagnostics_report = summarize_diagnostics(result.diagnostics)
        payload = {
            "ok": result.ok,
            "summary": diagnostics_report.to_dict(),
            "diagnostics": [d.to_dict() for d in result.diagnostics],
        }
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return _exit_code(result)

    if args.cmd == "inspect":
        result = parse_file(args.path, _parse_options(args))
        payload = {
            "schema_version": 1,
            "contract": "pine2ast.inspect.optimizer.v1",
            "producer": {
                "name": "pine2ast",
                "version": __version__,
                "contract": "pine2ast.inspect.optimizer.v1",
            },
            "tool": {"name": "pine2ast", "version": __version__},
            "source": {"path": str(args.path), "name": Path(args.path).name},
            "script": _script_dict(result.ast),
            "ok": result.ok,
            "unsupported_features": _unsupported_features(result),
            "diagnostics": [d.to_dict() for d in result.diagnostics],
            "inputs": (
                [_input_dict(i) for i in extract_inputs(result.ast, result.semantic_model)]
                if result.ast
                else []
            ),
            "strategy_calls": (
                [
                    {"name": c.name, "arg_count": len(c.arguments), "span": _span_dict(c.span)}
                    for c in extract_strategy_calls(result.ast)
                ]
                if result.ast
                else []
            ),
            "request_calls": (
                [_simple_call(c) for c in extract_request_calls(result.ast)] if result.ast else []
            ),
            "plots": [_simple_call(c) for c in extract_plots(result.ast)] if result.ast else [],
            "alerts": (
                [
                    {"name": c.name, "arg_count": len(c.arguments), "span": _span_dict(c.span)}
                    for c in extract_alertconditions(result.ast)
                ]
                if result.ast
                else []
            ),
            "drawings": (
                [
                    {"name": c.name, "arg_count": len(c.arguments), "span": _span_dict(c.span)}
                    for c in extract_drawing_calls(result.ast)
                ]
                if result.ast
                else []
            ),
            "dependencies": (
                _dependency_dict(extract_dependencies(result.ast, result.semantic_model))
                if result.ast
                else None
            ),
        }
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return _exit_code(result)

    if args.cmd == "golden":
        if args.compare:
            ok, message = compare_golden(
                args.path,
                ast_path=args.ast,
                ignore_spans=args.ignore_spans,
                run_semantic=not args.no_semantic,
            )
            print(message)
            return 0 if ok else 1
        info = generate_golden(
            args.path,
            ast_path=args.ast,
            diagnostics_path=args.diagnostics,
            ignore_spans=args.ignore_spans,
            run_semantic=not args.no_semantic,
        )
        print(info["ast_path"])
        print(info["diagnostics_path"])
        return 0 if info["ok"] else 1
    if args.cmd == "validate-corpus":
        output = validate_corpus_json(args.path, run_semantic=not args.no_semantic)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0
    if args.cmd == "bench":
        output = bench_corpus_json(
            args.path,
            repeat=args.repeat,
            baseline_path=args.baseline,
            run_semantic=not args.no_semantic,
        )
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0

    if args.cmd == "tokens":
        result = parse_file(
            args.path, ParseOptions(collect_tokens=True, run_semantic=False, source_name=args.path)
        )
        for tok in result.tokens or []:
            print(f"{tok.kind.value:<20} {tok.text!r} {tok.span.start_line}:{tok.span.start_col}")
        return _exit_code(result)

    result = parse_file(args.path, _parse_options(args))

    if args.cmd == "parse":
        if args.json_path:
            if result.ast is None:
                print(diagnostics_to_json(result.diagnostics), file=sys.stderr)
                return 1
            else:
                Path(args.json_path).write_text(ast_to_json(result.ast), encoding="utf-8")
                print(args.json_path)
                return 0
        else:
            if result.ast is not None:
                print(ast_to_json(result.ast))
                return 0
            else:
                return 1
    elif args.cmd == "validate":
        for d in result.diagnostics:
            print(format_diagnostic(d, args.path))
        if not result.diagnostics:
            print("OK")
    elif args.cmd == "dump-symbols":
        if result.semantic_model:
            rows = [
                {
                    "id": sym.id,
                    "kind": sym.kind.value,
                    "name": sym.name,
                    "type": sym.type,
                    "qualifier": sym.qualifier,
                    "scope_id": sym.scope_id,
                }
                for sym in result.semantic_model.symbols.values()
            ]
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                for sym in result.semantic_model.symbols.values():
                    print(
                        f"{sym.id:04d} {sym.kind.value:<13} {sym.name:<30} type={sym.type} qualifier={sym.qualifier}"
                    )
    elif args.cmd == "test-fixture":
        for d in result.diagnostics:
            print(format_diagnostic(d, args.path))
        print("OK" if result.ok else "FAILED")
    return _exit_code(result)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(code)
