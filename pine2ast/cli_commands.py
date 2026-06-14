from __future__ import annotations

# mypy: ignore-errors

# ruff: noqa: F401

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
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.semantic.snapshot import build_semantic_snapshot_payload
from pine2ast.contracts import contract_check_file_payload
from pine2ast.openpine_contracts.schema import openpine_contract_schema
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
from pine2ast.release import build_release_manifest
from pine2ast.reference_catalog import (
    OfficialReferenceError,
    ReferenceCatalogError,
    export_catalog_markdown,
    fetch_official_reference_index,
    load_official_reference_index,
    official_reference_diff_payload,
    official_reference_gate_payload,
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


def run_cli_command(args) -> int:

    if args.cmd == "contract-schema":
        output = json.dumps(openpine_contract_schema(), ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0

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

    if args.cmd == "official-reference":
        try:
            if args.official_json:
                index = load_official_reference_index(args.official_json)
            else:
                index = fetch_official_reference_index(args.version, timeout=args.timeout)
            if args.action == "fetch":
                payload = index.to_dict()
            elif args.action == "diff":
                payload = official_reference_diff_payload(index)
            else:
                if not args.baseline:
                    raise OfficialReferenceError("official-reference gate requires --baseline")
                payload = official_reference_gate_payload(index, args.baseline)
        except OfficialReferenceError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 1 if args.action == "gate" and payload.get("status") == "fail" else 0

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

    if args.cmd == "release-report":
        report = build_release_manifest(
            args.root,
            min_v5_signature_ready_ratio=args.min_v5_signature_ready_ratio,
            min_v6_signature_ready_ratio=args.min_v6_signature_ready_ratio,
        )
        output = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return 0 if report.ok else 1

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

    if args.cmd == "contract-check":
        payload = contract_check_file_payload(
            args.path,
            options=_parse_options(args),
            include_openpine_contract=not getattr(args, "no_openpine_contract", False),
        )
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
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

    if args.cmd == "semantic-snapshot":
        result = parse_file(args.path, _parse_options(args))
        payload = build_semantic_snapshot_payload(
            result,
            source_path=str(args.path),
            include_node_facts=not getattr(args, "no_node_facts", False),
        )
        output = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        return _exit_code(result)

    if args.cmd == "inspect":
        result = parse_file(args.path, _parse_options(args))
        payload = build_inspect_payload(
            result,
            source_path=str(args.path),
            include_openpine_contract=getattr(args, "openpine_contract", False),
            include_semantic_snapshot=getattr(args, "semantic_snapshot", False),
        )
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
