from __future__ import annotations

from pine2ast.semantic.version_semantics import apply_version_semantics

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, Mapping, Any

if TYPE_CHECKING:
    from pine2ast.libraries.qualifier_context import LibraryQualifierContext

from pine2ast import audit, security
from pine2ast._version import __version__
from pine2ast.ast.nodes import Program
from pine2ast.ast.serialize import ast_to_dict, ast_to_json
from pine2ast.ast.visitors import walk
from pine2ast.catalog import CatalogRepository
from pine2ast.config import DEFAULT_MAX_AST_NODES, DEFAULT_MAX_FILE_SIZE_BYTES, DEFAULT_MAX_TOKENS
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer import Lexer, Token
from pine2ast.lexer.token import SourceSpan
from pine2ast.layout import LayoutProcessor
from pine2ast.parser import Parser, ParserResult
from pine2ast.policy import PolicyBundle, policy_bundle_from_catalog
from pine2ast.semantic import SemanticAnalyzer, SemanticModel
from pine2ast.source import SourceNormalizer
from pine2ast.versioning import PineVersionContext, PineVersionResolver


@dataclass(slots=True)
class ParseOptions:
    expected_pine_version: int | None = None
    strictness: Literal["strict", "diagnostic"] = "strict"
    collect_tokens: bool = False
    collect_trivia: bool = True
    run_semantic: bool = True
    recover_errors: bool = True
    max_diagnostics: int = security.ABSOLUTE_MAX_DIAGNOSTICS
    source_name: str = "<memory>"
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_ast_nodes: int = DEFAULT_MAX_AST_NODES
    loop_max_iterations: int = security.DEFAULT_LOOP_MAX_ITERATIONS
    strict_builtin_namespaces: bool = True
    producer_commit: str | None = None
    created_at_utc_ms: int | None = None
    security_audit_hook: Optional[audit.SecurityAuditHook] = None
    library_context: LibraryQualifierContext | None = None

    def __post_init__(self) -> None:
        if self.strictness not in {"strict", "diagnostic"}:
            raise ValueError("strictness must be 'strict' or 'diagnostic'")
        if isinstance(self.max_diagnostics, bool) or self.max_diagnostics < 1:
            raise ValueError("max_diagnostics must be a positive integer")
        if self.created_at_utc_ms is not None and (
            isinstance(self.created_at_utc_ms, bool) or self.created_at_utc_ms < 0
        ):
            raise ValueError("created_at_utc_ms must be a nonnegative integer or None")

    def clamp_to_ceiling(self) -> "ParseOptions":
        return ParseOptions(
            expected_pine_version=self.expected_pine_version,
            strictness=self.strictness,
            collect_tokens=self.collect_tokens,
            collect_trivia=self.collect_trivia,
            run_semantic=self.run_semantic,
            recover_errors=self.recover_errors,
            max_diagnostics=min(self.max_diagnostics, security.ABSOLUTE_MAX_DIAGNOSTICS),
            source_name=self.source_name,
            max_file_size_bytes=min(
                self.max_file_size_bytes, security.ABSOLUTE_MAX_FILE_SIZE_BYTES
            ),
            max_tokens=min(self.max_tokens, security.ABSOLUTE_MAX_TOKENS),
            max_ast_nodes=min(self.max_ast_nodes, security.ABSOLUTE_MAX_AST_NODES),
            loop_max_iterations=min(
                self.loop_max_iterations, security.ABSOLUTE_MAX_LOOP_ITERATIONS
            ),
            strict_builtin_namespaces=self.strict_builtin_namespaces,
            producer_commit=self.producer_commit,
            created_at_utc_ms=self.created_at_utc_ms,
            security_audit_hook=self.security_audit_hook,
            library_context=self.library_context,
        )


@dataclass(slots=True, frozen=True)
class ParseResult:
    ast: Optional[Program]
    diagnostics: list[Diagnostic]
    tokens: Optional[list[Token]] = None
    semantic_model: Optional[SemanticModel] = None
    version_context: PineVersionContext | None = None
    ast_artifact: Optional[dict[str, object]] = None
    semantic_facts_artifact: Optional[dict[str, object]] = None
    source_manifest: Optional[dict[str, object]] = None
    frontend_artifact: Optional[dict[str, object]] = None
    support_profile: Optional[dict[str, object]] = None
    created_at_utc_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.ast is not None and not any(item.is_error for item in self.diagnostics)


def _dedupe_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    seen: set[tuple[str, int, int, str]] = set()
    for item in diagnostics:
        key = (item.code, item.span.start_offset, item.span.end_offset, item.message)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _limit_diagnostics(diagnostics: list[Diagnostic], limit: int) -> list[Diagnostic]:
    """Bound diagnostics without allowing warnings to hide real failures."""

    deduped = _dedupe_diagnostics(diagnostics)
    if len(deduped) <= limit:
        return deduped
    severity_rank = {
        Severity.FATAL: 0,
        Severity.ERROR: 1,
        Severity.WARNING: 2,
        Severity.INFO: 3,
    }
    ranked = sorted(
        enumerate(deduped),
        key=lambda pair: (severity_rank[pair[1].severity], pair[0]),
    )
    selected = {index for index, _item in ranked[:limit]}
    return [item for index, item in enumerate(deduped) if index in selected]


class ParsePipeline:
    def __init__(self, options: ParseOptions | None = None) -> None:
        self.options = (options or ParseOptions()).clamp_to_ceiling()
        self.audit_runner = audit.AuditHookRunner(self.options.security_audit_hook)
        self.safe_name = security.sanitize_source_name(self.options.source_name)
        self.catalog = CatalogRepository.default()
        self.version_resolver = PineVersionResolver(self.catalog.identity_tuple)

    def validate_input(self, code: str | bytes) -> ParseResult | None:
        options = self.options
        if options.source_name and len(options.source_name) > security.ABSOLUTE_MAX_SOURCE_NAME_LEN:
            diag = Diagnostic(
                Severity.FATAL,
                codes.SOURCE_NAME_TOO_LONG,
                f"source_name exceeds {security.ABSOLUTE_MAX_SOURCE_NAME_LEN} characters",
                SourceSpan.zero(),
            )
            self.audit_runner.emit(diag, source_name=self.safe_name)
            return ParseResult(None, [diag])
        if options.source_name and any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in options.source_name
        ):
            diag = Diagnostic(
                Severity.FATAL,
                codes.SOURCE_NAME_CONTROL_CHAR,
                "source_name contains control characters",
                SourceSpan.zero(),
            )
            self.audit_runner.emit(diag, source_name=self.safe_name)
            return ParseResult(None, [diag])
        raw_size = len(code) if isinstance(code, bytes) else len(code.encode("utf-8"))
        if raw_size > options.max_file_size_bytes:
            diag = Diagnostic(
                Severity.FATAL, codes.FILE_TOO_LARGE, "Input file is too large.", SourceSpan.zero()
            )
            self.audit_runner.emit(diag, source_name=self.safe_name)
            return ParseResult(None, [diag])
        text = code if isinstance(code, str) else code.decode("utf-8", errors="replace")
        overflows = security.find_overflowing_float_literals(text)
        if overflows:
            start, end, literal = overflows[0]
            diag = Diagnostic(
                Severity.FATAL,
                codes.FLOAT_OVERFLOW_LITERAL,
                f"Numeric literal overflows to infinity: {literal!r}",
                SourceSpan(start, end, 1, 1, 1, 1),
            )
            self.audit_runner.emit(diag, source_name=self.safe_name)
            return ParseResult(None, [diag])
        return None

    def normalize(self, code: str | bytes):
        return SourceNormalizer().normalize(code, source_name=self.safe_name)

    def resolve_version(self, normalized_text: str):
        return self.version_resolver.resolve(
            normalized_text,
            expected_pine_version=self.options.expected_pine_version,
        )

    def admitted_frontend(
        self, context: PineVersionContext
    ) -> tuple[Mapping[str, Any], PolicyBundle]:
        catalog = self.catalog.readonly_view(context.pine_version)
        policies = policy_bundle_from_catalog(context, catalog)
        return catalog, policies

    def lex_only(self, code: str | bytes) -> tuple[list[Token], list[Diagnostic]]:
        early = self.validate_input(code)
        if early is not None:
            return [], early.diagnostics
        normalized = self.normalize(code)
        diagnostics = list(normalized.diagnostics)
        resolution = self.resolve_version(normalized.text)
        diagnostics.extend(resolution.diagnostics)
        if resolution.context is None:
            return [], _dedupe_diagnostics(diagnostics)
        _, policies = self.admitted_frontend(resolution.context)
        lexed = Lexer(
            normalized.text,
            version_context=resolution.context,
            syntax_policy=policies.syntax,
            source_name=self.options.source_name,
        ).lex()
        diagnostics.extend(lexed.diagnostics)
        return lexed.tokens, _dedupe_diagnostics(diagnostics)

    def parse_only(
        self,
        tokens: list[Token],
        *,
        version_context: PineVersionContext,
        policies: PolicyBundle | None = None,
    ) -> ParserResult:
        _, admitted = self.admitted_frontend(version_context)
        bundle = policies or admitted
        bundle.validate_context(version_context)
        layout = LayoutProcessor().process(tokens)
        result = Parser(
            layout.tokens,
            version_context=version_context,
            syntax_policy=bundle.syntax,
            max_diagnostics=self.options.max_diagnostics,
        ).parse()
        result.diagnostics[:0] = layout.diagnostics
        return result

    def semantic_only(
        self,
        ast: Program,
        *,
        catalog: Mapping[str, Any] | None = None,
        policies: PolicyBundle | None = None,
    ) -> SemanticModel:
        admitted_catalog, admitted_policies = self.admitted_frontend(ast.version_context)
        actual_catalog = catalog or admitted_catalog
        actual_policies = policies or admitted_policies
        actual_policies.validate_context(ast.version_context)
        analyzer = SemanticAnalyzer(
            version_context=ast.version_context,
            catalog=actual_catalog,
            policy=actual_policies.semantic,
            max_diagnostics=self.options.max_diagnostics,
            strict_builtin_namespaces=self.options.strict_builtin_namespaces,
            loop_max_iterations=self.options.loop_max_iterations,
        )
        if self.options.library_context is not None:
            analyzer._projected_exported_functions = self.options.library_context.declaration_ids(
                ast
            )
        return analyzer.analyze(ast)

    def parse(self, code: str | bytes) -> ParseResult:
        if self.options.library_context is not None:
            from pine2ast.libraries.qualifier_context import LibraryQualifierContext

            library_context = self.options.library_context
            if type(library_context) is not LibraryQualifierContext:
                raise ValueError("library_context must be an admitted LibraryQualifierContext")
            text = code.decode("utf-8") if isinstance(code, bytes) else code
            if text != library_context.code:
                raise ValueError("library context source differs from parser input")
        early = self.validate_input(code)
        if early is not None:
            return early
        normalized = self.normalize(code)
        diagnostics = list(normalized.diagnostics)
        if any(item.severity is Severity.FATAL for item in diagnostics):
            return ParseResult(None, diagnostics)
        resolution = self.resolve_version(normalized.text)
        diagnostics.extend(resolution.diagnostics)
        context = resolution.context
        if context is None:
            return ParseResult(None, _dedupe_diagnostics(diagnostics))
        if not context.production_frontend_supported:
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    codes.FRONTEND_VERSION_NOT_IMPLEMENTED,
                    f"Pine v{context.pine_version} is identified exactly, but its production frontend is not implemented yet; v5/v6 are currently executable frontend targets.",
                    context.annotation_span or SourceSpan.zero(),
                )
            )
            return ParseResult(None, _dedupe_diagnostics(diagnostics), version_context=context)
        catalog, policies = self.admitted_frontend(context)
        lexed = Lexer(
            normalized.text,
            version_context=context,
            syntax_policy=policies.syntax,
            source_name=self.options.source_name,
        ).lex()
        diagnostics.extend(lexed.diagnostics)
        if len(lexed.tokens) > self.options.max_tokens:
            diagnostics.append(
                Diagnostic(
                    Severity.FATAL, codes.TOO_MANY_TOKENS, "Too many tokens.", SourceSpan.zero()
                )
            )
            return ParseResult(
                None,
                _dedupe_diagnostics(diagnostics),
                lexed.tokens if self.options.collect_tokens else None,
                version_context=context,
            )
        layout = LayoutProcessor().process(lexed.tokens)
        diagnostics.extend(layout.diagnostics)
        parsed = Parser(
            layout.tokens,
            version_context=context,
            syntax_policy=policies.syntax,
            max_diagnostics=self.options.max_diagnostics,
        ).parse()
        diagnostics.extend(parsed.diagnostics)
        ast = parsed.program
        semantic_model = None
        parser_gate_ok = ast is not None and not any(item.is_error for item in diagnostics)
        if ast is not None and self.options.run_semantic:
            semantic_model = self.semantic_only(ast, catalog=catalog, policies=policies)
            diagnostics.extend(semantic_model.diagnostics)
        if ast is not None:
            node_count = sum(1 for _ in walk(ast))
            if node_count > self.options.max_ast_nodes:
                diagnostics.append(
                    Diagnostic(
                        Severity.FATAL,
                        codes.TOO_MANY_AST_NODES,
                        "Too many AST nodes.",
                        ast.span,
                    )
                )
                ast = None

        diagnostics = _dedupe_diagnostics(diagnostics)
        if ast is None:
            return ParseResult(
                None,
                diagnostics,
                layout.tokens if self.options.collect_tokens else None,
                semantic_model,
                context,
            )

        # Version-exact checks are part of the frontend semantic gate.  Run them
        # before publishing gate metadata and before applying the final diagnostic
        # ceiling, otherwise an invalid program can be labelled semantic_gate=pass.
        ast.producer_metadata = {
            "contract": "pine.ast.v2",
            "producer": {"name": "pine2ast", "version": __version__},
            "schema_version": ast.schema_version,
            "version_context": context.to_dict(),
            "parser_gate": "pass" if parser_gate_ok else "fail",
            "semantic_gate": "not_run",
            "frontend_gate": "pending",
        }
        if self.options.library_context is not None:
            ast.producer_metadata["library_qualifier_context_ref"] = (
                self.options.library_context.to_dict()["content_hash"]
            )
        ast.diagnostics = diagnostics
        provisional = ParseResult(
            ast,
            diagnostics,
            layout.tokens if self.options.collect_tokens else None,
            semantic_model,
            context,
        )
        apply_version_semantics(code, provisional, options=self.options)

        final_diagnostics = _limit_diagnostics(
            provisional.diagnostics, self.options.max_diagnostics
        )
        # Keep the AST and ParseResult views identical and bounded.
        provisional.diagnostics[:] = final_diagnostics
        ast.diagnostics = provisional.diagnostics
        final_has_errors = any(item.is_error for item in final_diagnostics)
        ast.producer_metadata["semantic_gate"] = (
            "not_run" if not self.options.run_semantic else ("fail" if final_has_errors else "pass")
        )
        ast.producer_metadata["frontend_gate"] = "fail" if final_has_errors else "pass"
        return provisional


def parse_code(code: str | bytes, options: ParseOptions | None = None) -> ParseResult:
    pipeline = ParsePipeline(options)
    result = pipeline.parse(code)
    from pine2ast.frontend.artifact import attach_frontend_artifacts

    return attach_frontend_artifacts(
        result, source=code, options=pipeline.options, source_path=pipeline.options.source_name
    )


def parse_file(path: str, options: ParseOptions | None = None) -> ParseResult:
    requested = Path(path)
    options = options or ParseOptions(source_name=str(requested))
    if options.source_name == "<memory>":
        options.source_name = str(requested)
    try:
        resolved = security.safe_resolve_path(requested, must_exist=True)
    except (FileNotFoundError, ValueError) as exc:
        diag = Diagnostic(
            Severity.FATAL, codes.UNSAFE_PATH, f"Refusing path: {exc}", SourceSpan.zero()
        )
        audit.AuditHookRunner(options.security_audit_hook).emit(
            diag, source_name=security.sanitize_source_name(str(requested))
        )
        return ParseResult(None, [diag])
    return parse_code(resolved.read_bytes(), options)


def diagnostics_to_json(diagnostics: list[Diagnostic], *, indent: int = 2) -> str:
    return json.dumps([item.to_dict() for item in diagnostics], ensure_ascii=False, indent=indent)


__all__ = [
    "ParseOptions",
    "ParsePipeline",
    "ParseResult",
    "ast_to_dict",
    "ast_to_json",
    "diagnostics_to_json",
    "parse_code",
    "parse_file",
]
