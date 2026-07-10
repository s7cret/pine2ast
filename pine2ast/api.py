from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pine2ast import audit, security
from pine2ast._version import __version__
from pine2ast.ast.nodes import Program
from pine2ast.ast.serialize import ast_to_dict as ast_to_dict, ast_to_json as ast_to_json
from pine2ast.ast.visitors import walk
from pine2ast.config import DEFAULT_MAX_AST_NODES, DEFAULT_MAX_FILE_SIZE_BYTES, DEFAULT_MAX_TOKENS
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.lexer import Lexer, Token
from pine2ast.lexer.token import SourceSpan
from pine2ast.layout import LayoutProcessor
from pine2ast.parser import Parser, ParserResult
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
    max_diagnostics: int = security.ABSOLUTE_MAX_DIAGNOSTICS
    source_name: str = "<memory>"
    # Stage 1: make the v5/v6 intent explicit. The legacy `strict_v6=False`
    # behaviour still acts as v6-compatibility parsing for v5 scripts unless the
    # caller opts into `version=5`, which selects the native v5 profile.
    compatibility_mode: bool = False
    # Resource ceilings. These are HARD-CLAMPED in `_resolve_options` to
    # `pine2ast.security.ABSOLUTE_MAX_*` so a caller cannot bypass the
    # DoS guards by passing a huge value. Callers can lower them per
    # request (e.g. "this server accepts 100 KiB scripts max").
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_ast_nodes: int = DEFAULT_MAX_AST_NODES
    # P2.1: per-script static loop bound. The runtime has its own
    # max_loops (=100_000); we use the same default here so a script
    # that compiles clean is also runtime-safe. Callers doing offline
    # backtest compilation can raise this up to ABSOLUTE_MAX.
    loop_max_iterations: int = security.DEFAULT_LOOP_MAX_ITERATIONS
    strict_builtin_namespaces: bool = False
    runtime_contract_profile: str | None = None
    # P2.2: optional hook for shipping security-tier rejections
    # (P2A1106-1113, P2A9001-9003, P2A9201) to a SIEM / audit log.
    # The hook receives a SecurityAuditEvent per security diagnostic.
    # See pine2ast.audit for the event shape and the
    # is_security_audit_code whitelist.
    security_audit_hook: Optional[audit.SecurityAuditHook] = None

    @property
    def language_profile(self) -> PineLanguageProfile:
        return pine_language_profile(
            self.version,
            strict=self.strict_v6,
            compatibility_mode=self.compatibility_mode,
        )

    def clamp_to_ceiling(self) -> "ParseOptions":
        """Return a copy of self with all resource fields clamped to the
        absolute ceiling. The field defaults are already inside the ceiling so
        this is a no-op for any normal caller."""
        return ParseOptions(
            version=self.version,
            strict_v6=self.strict_v6,
            collect_tokens=self.collect_tokens,
            collect_trivia=self.collect_trivia,
            run_semantic=self.run_semantic,
            recover_errors=self.recover_errors,
            max_diagnostics=min(self.max_diagnostics, security.ABSOLUTE_MAX_DIAGNOSTICS),
            source_name=self.source_name,
            compatibility_mode=self.compatibility_mode,
            max_file_size_bytes=min(
                self.max_file_size_bytes, security.ABSOLUTE_MAX_FILE_SIZE_BYTES
            ),
            max_tokens=min(self.max_tokens, security.ABSOLUTE_MAX_TOKENS),
            max_ast_nodes=min(self.max_ast_nodes, security.ABSOLUTE_MAX_AST_NODES),
            loop_max_iterations=min(
                self.loop_max_iterations, security.ABSOLUTE_MAX_LOOP_ITERATIONS
            ),
            strict_builtin_namespaces=self.strict_builtin_namespaces,
            runtime_contract_profile=self.runtime_contract_profile,
            security_audit_hook=self.security_audit_hook,
        )


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


class ParsePipeline:
    """Explicit frontend pipeline used by `parse_code()` and advanced callers.

    The public `parse_code()` helper is intentionally kept as a small facade for
    backwards compatibility. New integration code can call individual pipeline
    stages for lexer/parser/semantic smoke checks without spawning the CLI.
    """

    def __init__(self, options: ParseOptions | None = None) -> None:
        self.options = (options or ParseOptions()).clamp_to_ceiling()
        self.profile = self.options.language_profile
        self.audit_runner = audit.AuditHookRunner(self.options.security_audit_hook)
        self.safe_name = security.sanitize_source_name(self.options.source_name)

    def validate_input(self, code: str | bytes) -> ParseResult | None:
        options = self.options
        safe_name = self.safe_name
        if options.source_name and len(options.source_name) > security.ABSOLUTE_MAX_SOURCE_NAME_LEN:
            diag = Diagnostic(
                Severity.FATAL,
                codes.SOURCE_NAME_TOO_LONG,
                f"source_name exceeds {security.ABSOLUTE_MAX_SOURCE_NAME_LEN} characters",
                SourceSpan.zero(),
            )
            self.audit_runner.emit(diag, source_name=safe_name)
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
            self.audit_runner.emit(diag, source_name=safe_name)
            return ParseResult(None, [diag])
        if not security.is_safe_runtime_contract_profile(options.runtime_contract_profile):
            diag = Diagnostic(
                Severity.FATAL,
                codes.RUNTIME_CONTRACT_PROFILE_UNKNOWN,
                f"Unknown runtime_contract_profile: {options.runtime_contract_profile!r}",
                SourceSpan.zero(),
            )
            self.audit_runner.emit(diag, source_name=safe_name)
            return ParseResult(None, [diag])
        if isinstance(code, str):
            overflows = security.find_overflowing_float_literals(code)
        else:
            try:
                overflows = security.find_overflowing_float_literals(
                    code.decode("utf-8", errors="replace")
                )
            except Exception:  # noqa: BLE001 — bytes are best-effort decoded for the overflow check
                overflows = []
        if overflows:
            first_start, first_end, first_text = overflows[0]
            diag = Diagnostic(
                Severity.FATAL,
                codes.FLOAT_OVERFLOW_LITERAL,
                f"Numeric literal overflows to infinity: {first_text!r}",
                SourceSpan(
                    start_offset=first_start,
                    end_offset=first_end,
                    start_line=1,
                    start_col=1,
                    end_line=1,
                    end_col=1,
                ),
            )
            self.audit_runner.emit(diag, source_name=safe_name)
            return ParseResult(None, [diag])
        if isinstance(code, bytes) and len(code) > options.max_file_size_bytes:
            diag = Diagnostic(
                Severity.FATAL, codes.FILE_TOO_LARGE, "Input file is too large.", SourceSpan.zero()
            )
            self.audit_runner.emit(diag, source_name=safe_name)
            return ParseResult(None, [diag])
        if isinstance(code, str) and len(code.encode("utf-8")) > options.max_file_size_bytes:
            diag = Diagnostic(
                Severity.FATAL, codes.FILE_TOO_LARGE, "Input file is too large.", SourceSpan.zero()
            )
            self.audit_runner.emit(diag, source_name=safe_name)
            return ParseResult(None, [diag])
        return None

    def normalize(self, code: str | bytes):
        return SourceNormalizer().normalize(code, source_name=self.safe_name)

    def lex_only(self, code: str | bytes) -> tuple[list[Token], list[Diagnostic]]:
        early = self.validate_input(code)
        if early is not None:
            return [], early.diagnostics
        normalized = self.normalize(code)
        diagnostics = list(normalized.diagnostics)
        if any(d.severity is Severity.FATAL for d in diagnostics):
            return [], diagnostics
        lexed = Lexer(normalized.text, source_name=self.options.source_name).lex()
        diagnostics.extend(lexed.diagnostics)
        return lexed.tokens, diagnostics

    def parse_only(self, tokens: list[Token]) -> ParserResult:
        layout = LayoutProcessor().process(tokens)
        parsed = Parser(
            layout.tokens,
            strict_v6=self.options.strict_v6,
            max_diagnostics=self.options.max_diagnostics,
            target_version=self.profile.version,
            compatibility_mode=self.profile.compatibility_mode,
            language_profile=self.profile,
        ).parse()
        parsed.diagnostics[:0] = layout.diagnostics
        return parsed

    def semantic_only(self, ast: Program) -> SemanticModel:
        source_version = ast.version if ast.version in {5, 6} else self.profile.version
        return SemanticAnalyzer(
            max_diagnostics=self.options.max_diagnostics,
            strict_builtin_namespaces=self.options.strict_builtin_namespaces,
            pine_version=source_version,
            language_profile=pine_language_profile(
                source_version,
                strict=self.options.strict_v6,
                compatibility_mode=self.options.compatibility_mode,
            ),
            loop_max_iterations=self.options.loop_max_iterations,
        ).analyze(ast)

    def parse(self, code: str | bytes) -> ParseResult:
        options = self.options
        early = self.validate_input(code)
        if early is not None:
            return early

        normalized = self.normalize(code)
        diagnostics = list(normalized.diagnostics)
        if any(d.severity is Severity.FATAL for d in diagnostics):
            return ParseResult(None, diagnostics)

        lexed = Lexer(normalized.text, source_name=options.source_name).lex()
        diagnostics.extend(lexed.diagnostics)
        if len(lexed.tokens) > options.max_tokens:
            diagnostics.append(
                Diagnostic(
                    Severity.FATAL, codes.TOO_MANY_TOKENS, "Too many tokens.", SourceSpan.zero()
                )
            )
            return ParseResult(None, diagnostics, lexed.tokens if options.collect_tokens else None)
        if any(d.severity is Severity.FATAL for d in diagnostics):
            return ParseResult(None, diagnostics, lexed.tokens if options.collect_tokens else None)

        layout = LayoutProcessor().process(lexed.tokens)
        diagnostics.extend(layout.diagnostics)

        parsed = Parser(
            layout.tokens,
            strict_v6=options.strict_v6,
            max_diagnostics=options.max_diagnostics,
            target_version=self.profile.version,
            compatibility_mode=self.profile.compatibility_mode,
            language_profile=self.profile,
        ).parse()
        diagnostics.extend(parsed.diagnostics)
        semantic_model = None
        ast = parsed.program
        parser_gate_ok = False
        semantic_gate_ok = False

        # Legacy behaviour: default v6 strict parsing treats //@version=5 as an
        # error. Native v5 mode (`ParseOptions(version=5)`) does not.
        if ast is not None and ast.version == 5 and options.strict_v6 and self.profile.version != 5:
            for diag in diagnostics:
                if diag.code == codes.UNSUPPORTED_VERSION:
                    diag.severity = Severity.ERROR

        if ast is not None:
            parser_gate_ok = not any(
                diagnostic.severity in {Severity.ERROR, Severity.FATAL}
                for diagnostic in diagnostics
            )

        if ast is not None and options.run_semantic:
            semantic_model = self.semantic_only(ast)
            diagnostics.extend(semantic_model.diagnostics)
            semantic_gate_ok = parser_gate_ok and not any(
                diagnostic.severity in {Severity.ERROR, Severity.FATAL}
                for diagnostic in semantic_model.diagnostics
            )
        if ast is not None and options.runtime_contract_profile in {
            "v1.4",
            "runtime_contract_v1_4",
        }:
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
            ast.producer_metadata = {
                "contract": "pine.ast_contract.v1",
                "producer": {"name": "pine2ast", "version": _producer_version()},
                "schema_version": ast.schema_version,
                "pine_language_version": ast.language_version,
                "runtime_contract_profile": profile,
                "runtime_contract": (
                    "runtime_contract_v1_4"
                    if profile in {"v1.4", "runtime_contract_v1_4"}
                    else profile
                ),
                "parser_gate": "pass" if parser_gate_ok else "fail",
                "semantic_gate": (
                    "not_run"
                    if not options.run_semantic
                    else ("pass" if semantic_gate_ok else "fail")
                ),
            }
        return ParseResult(
            ast, diagnostics, layout.tokens if options.collect_tokens else None, semantic_model
        )


def parse_code(code: str | bytes, options: ParseOptions | None = None) -> ParseResult:
    return ParsePipeline(options).parse(code)


def parse_file(path: str, options: ParseOptions | None = None) -> ParseResult:
    p = Path(path)
    options = options or ParseOptions(source_name=str(p))
    if options.source_name == "<memory>":
        options.source_name = str(p)
    # P1.6: refuse to read through a symlink or escape a parent. The
    # caller can still pass any path; we just won't follow a chain of
    # symlinks to a target the caller never named explicitly.
    try:
        resolved = security.safe_resolve_path(p, must_exist=True)
    except (FileNotFoundError, ValueError) as exc:
        diag = Diagnostic(
            Severity.FATAL,
            codes.UNSAFE_PATH,
            f"Refusing path: {exc}",
            SourceSpan.zero(),
        )
        # P2.2: emit audit event for path-safety rejections.
        # The source_name here is the un-resolved path the caller
        # asked for (Pine doesn't see the resolved target because
        # we never read it). Sanitize it so a sensitive path isn't
        # echoed in the audit log either.
        audit.AuditHookRunner(options.security_audit_hook).emit(
            diag, source_name=security.sanitize_source_name(str(p))
        )
        return ParseResult(None, [diag])
    return parse_code(resolved.read_bytes(), options)


def diagnostics_to_json(diagnostics: list[Diagnostic], *, indent: int = 2) -> str:
    return json.dumps([d.to_dict() for d in diagnostics], ensure_ascii=False, indent=indent)
