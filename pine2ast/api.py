from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pine2ast._version import __version__
from pine2ast.ast.nodes import Program
from pine2ast.ast.serialize import ast_to_dict as ast_to_dict, ast_to_json as ast_to_json
from pine2ast.ast.visitors import walk
from pine2ast.config import DEFAULT_MAX_AST_NODES, DEFAULT_MAX_FILE_SIZE_BYTES, DEFAULT_MAX_TOKENS
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer import Lexer, Token
from pine2ast.lexer.token import SourceSpan
from pine2ast.layout import LayoutProcessor
from pine2ast.parser import Parser
from pine2ast.semantic import SemanticAnalyzer, SemanticModel
from pine2ast.source import SourceNormalizer


def _producer_version() -> str:
    return __version__


@dataclass(slots=True)
class ParseOptions:
    version: int = 6
    strict_v6: bool = True
    collect_tokens: bool = False
    collect_trivia: bool = True
    run_semantic: bool = True
    recover_errors: bool = True
    max_diagnostics: int = 200
    source_name: str = "<memory>"
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_ast_nodes: int = DEFAULT_MAX_AST_NODES
    strict_builtin_namespaces: bool = False
    runtime_contract_profile: str | None = None


def runtime_contract_v1_4_options(**overrides: object) -> ParseOptions:
    """Return parse options for AST2Python/PineLib runtime_contract v1.4 consumers.

    Default parsing remains a compatibility mode. This profile is the fail-closed
    consumer mode: unknown builtin namespace members are errors and AST nodes that
    the v1.4 stack cannot lower are surfaced as blocking diagnostics.
    """

    options = ParseOptions(strict_builtin_namespaces=True, runtime_contract_profile="v1.4")
    for name, value in overrides.items():
        if not hasattr(options, name):
            raise TypeError(f"Unknown ParseOptions field: {name}")
        if name == "strict_v6" and value is not True:
            raise ValueError(
                "runtime_contract_v1_4 production profile forbids implicit version assumption"
            )
        setattr(options, name, value)
    return options


@dataclass(slots=True)
class ParseResult:
    ast: Optional[Program]
    diagnostics: list[Diagnostic]
    tokens: Optional[list[Token]] = None
    semantic_model: Optional[SemanticModel] = None

    @property
    def ok(self) -> bool:
        return self.ast is not None and not any(
            d.severity in {Severity.FATAL, Severity.ERROR} for d in self.diagnostics
        )


def _dedupe_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Remove duplicate diagnostics emitted by recovery + semantic fallback paths.

    Parser recovery may intentionally emit a primary diagnostic and later semantic
    validation can rediscover the same issue on the recovered AST. Keep the first
    diagnostic for stable ordering and suppress exact code/span/message duplicates.
    """
    result: list[Diagnostic] = []
    seen: set[tuple[str, int, int, str]] = set()
    for diag in diagnostics:
        span = diag.span
        key = (diag.code, span.start_offset, span.end_offset, diag.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(diag)
    return result


def parse_code(code: str | bytes, options: ParseOptions | None = None) -> ParseResult:
    options = options or ParseOptions()
    if isinstance(code, bytes) and len(code) > options.max_file_size_bytes:
        diag = Diagnostic(
            Severity.FATAL, codes.FILE_TOO_LARGE, "Input file is too large.", SourceSpan.zero()
        )
        return ParseResult(None, [diag])
    if isinstance(code, str) and len(code.encode("utf-8")) > options.max_file_size_bytes:
        diag = Diagnostic(
            Severity.FATAL, codes.FILE_TOO_LARGE, "Input file is too large.", SourceSpan.zero()
        )
        return ParseResult(None, [diag])

    normalized = SourceNormalizer().normalize(code, source_name=options.source_name)
    diagnostics = list(normalized.diagnostics)
    if any(d.severity is Severity.FATAL for d in diagnostics):
        return ParseResult(None, diagnostics)

    lexed = Lexer(normalized.text, source_name=options.source_name).lex()
    diagnostics.extend(lexed.diagnostics)
    if len(lexed.tokens) > options.max_tokens:
        diagnostics.append(
            Diagnostic(Severity.FATAL, codes.TOO_MANY_TOKENS, "Too many tokens.", SourceSpan.zero())
        )
        return ParseResult(None, diagnostics, lexed.tokens if options.collect_tokens else None)
    if any(d.severity is Severity.FATAL for d in diagnostics):
        return ParseResult(None, diagnostics, lexed.tokens if options.collect_tokens else None)

    layout = LayoutProcessor().process(lexed.tokens)
    diagnostics.extend(layout.diagnostics)

    parsed = Parser(
        layout.tokens, strict_v6=options.strict_v6, max_diagnostics=options.max_diagnostics
    ).parse()
    diagnostics.extend(parsed.diagnostics)
    semantic_model = None
    ast = parsed.program
    if ast is not None and options.run_semantic:
        semantic_model = SemanticAnalyzer(
            max_diagnostics=options.max_diagnostics,
            strict_builtin_namespaces=options.strict_builtin_namespaces,
        ).analyze(ast)
        diagnostics.extend(semantic_model.diagnostics)
    if ast is not None and options.runtime_contract_profile in {"v1.4", "runtime_contract_v1_4"}:
        from pine2ast.runtime_contract import unsupported_features_for_program

        for feature in unsupported_features_for_program(ast):
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    str(feature["code"]),
                    f"Not lowerable under runtime_contract v1.4: {feature['message']}",
                    ast.span.__class__(**feature["span"]),
                    hint="Use compatibility parse mode only for non-runtime consumers.",
                )
            )
    if ast is not None:
        ast_node_count = sum(1 for _ in walk(ast))
        if ast_node_count > options.max_ast_nodes:
            diagnostics.append(
                Diagnostic(
                    Severity.FATAL, codes.TOO_MANY_AST_NODES, "Too many AST nodes.", ast.span
                )
            )
            ast = None
        else:
            ast.diagnostics = diagnostics[: options.max_diagnostics]
    diagnostics = _dedupe_diagnostics(diagnostics)[: options.max_diagnostics]
    if ast is not None:
        ast.diagnostics = diagnostics
        profile = options.runtime_contract_profile
        gate_ok = not any(d.severity in {Severity.ERROR, Severity.FATAL} for d in diagnostics)
        ast.producer_metadata = {
            "contract": "pain.ast_contract.v1",
            "producer": {"name": "pine2ast", "version": _producer_version()},
            "schema_version": ast.schema_version,
            "pine_language_version": ast.language_version,
            "runtime_contract_profile": profile,
            "runtime_contract": "runtime_contract_v1_4"
            if profile in {"v1.4", "runtime_contract_v1_4"}
            else profile,
            "parser_gate": "pass" if gate_ok else "fail",
            "semantic_gate": "not_run" if not options.run_semantic else ("pass" if gate_ok else "fail"),
        }
    return ParseResult(
        ast, diagnostics, layout.tokens if options.collect_tokens else None, semantic_model
    )


def parse_file(path: str, options: ParseOptions | None = None) -> ParseResult:
    p = Path(path)
    options = options or ParseOptions(source_name=str(p))
    if options.source_name == "<memory>":
        options.source_name = str(p)
    return parse_code(p.read_bytes(), options)


def diagnostics_to_json(diagnostics: list[Diagnostic], *, indent: int = 2) -> str:
    return json.dumps([d.to_dict() for d in diagnostics], ensure_ascii=False, indent=indent)
