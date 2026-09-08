from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from pine2ast.ast.base import ASTNode, Expression
from pine2ast.ast.nodes import Block, FunctionDeclaration, Literal, MethodDeclaration
from pine2ast.ast.visitors import walk
from pine2ast.lexer.token import SourceSpan
from pine2ast.versioning import PineVersionContext


def _valid_literal_value(node: Literal) -> bool:
    """Canonical lexer values, without casting malformed serialized values.

    parse_primary preserves Token.value; parse_once creates a bool literal.
    Signs are separate UnaryExpr nodes. Integer-looking float JSON values must
    retain their float representation, as the producer serializer already does.
    """
    types = {
        "int": int,
        "float": float,
        "bool": bool,
        "string": str,
        "color": str,
        "na": type(None),
    }
    if type(node.literal_type) is not str or type(node.value) is not types.get(node.literal_type):
        return False
    if node.literal_type == "float":
        return math.isfinite(node.value)
    if node.literal_type == "color":
        from pine2ast.lexer.lexer import _HEX_RE

        return _HEX_RE.fullmatch(node.value) is not None
    return True


@dataclass(slots=True)
class SchemaIssue:
    code: str
    message: str
    node_kind: str | None = None
    span: SourceSpan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_kind": self.node_kind,
            "span": self.span.to_dict() if self.span else None,
        }


@dataclass(slots=True)
class SchemaReport:
    ok: bool
    schema_version: str | None
    language: str | None
    pine_version: int | None
    version_context: dict[str, Any] | None
    node_count: int
    kind_counts: dict[str, int] = field(default_factory=dict)
    issues: list[SchemaIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_version": self.schema_version,
            "language": self.language,
            "pine_version": self.pine_version,
            "version_context": self.version_context,
            "node_count": self.node_count,
            "kind_counts": dict(sorted(self.kind_counts.items())),
            "issues": [item.to_dict() for item in self.issues],
        }


def validate_ast_schema(program: ASTNode) -> SchemaReport:
    issues: list[SchemaIssue] = []
    seen_ids: set[int] = set()
    kind_counts: dict[str, int] = {}
    schema_version = getattr(program, "schema_version", None)
    language = getattr(program, "language", None)
    context = getattr(program, "version_context", None)
    if schema_version not in {"2.0", "2.1"}:
        issues.append(
            SchemaIssue(
                "AST_SCHEMA_VERSION_INVALID",
                "Program.schema_version must be 2.0 or 2.1.",
                getattr(program, "kind", None),
                getattr(program, "span", None),
            )
        )
    if language != "pine":
        issues.append(
            SchemaIssue(
                "AST_LANGUAGE_INVALID",
                "Program.language must be 'pine'.",
                getattr(program, "kind", None),
                getattr(program, "span", None),
            )
        )
    if not isinstance(context, PineVersionContext):
        issues.append(
            SchemaIssue(
                "AST_VERSION_CONTEXT_INVALID",
                "Program.version_context must be PineVersionContext.",
                getattr(program, "kind", None),
                getattr(program, "span", None),
            )
        )
    node_count = 0
    has_receiver_qualifier = False
    for node in walk(program):
        node_count += 1
        if id(node) in seen_ids:
            issues.append(
                SchemaIssue(
                    "AST_SHARED_NODE",
                    "AST node object is referenced more than once.",
                    node.kind,
                    node.span,
                )
            )
            continue
        seen_ids.add(id(node))
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1
        if schema_version == "2.1" and isinstance(node, Literal) and not _valid_literal_value(node):
            issues.append(
                SchemaIssue(
                    "AST_LITERAL_VALUE_INVALID",
                    "Literal value must have the exact canonical type and shape for its tag.",
                    node.kind,
                    node.span,
                )
            )
        if isinstance(node, MethodDeclaration) and node.receiver_explicit_qualifier is not None:
            has_receiver_qualifier = True
            if (
                node.receiver_explicit_qualifier not in {"simple", "series"}
                or not isinstance(context, PineVersionContext)
                or context.pine_version not in {5, 6}
            ):
                issues.append(
                    SchemaIssue(
                        "AST_METHOD_RECEIVER_QUALIFIER",
                        "Explicit method receiver qualifiers require simple/series in Pine v5/v6.",
                        node.kind,
                        node.span,
                    )
                )
        span = getattr(node, "span", None)
        if not isinstance(span, SourceSpan):
            issues.append(
                SchemaIssue(
                    "AST_SPAN_MISSING", "Every AST node must carry SourceSpan.", node.kind, None
                )
            )
        elif not (
            span.start_offset <= span.end_offset
            and span.start_line >= 1
            and span.end_line >= span.start_line
            and span.start_col >= 1
            and span.end_col >= 1
        ):
            issues.append(
                SchemaIssue(
                    "AST_SPAN_INVALID", "AST node span has invalid coordinates.", node.kind, span
                )
            )
        if isinstance(node, (FunctionDeclaration, MethodDeclaration)) and not isinstance(
            node.body, (Block, Expression)
        ):
            issues.append(
                SchemaIssue(
                    "AST_DECLARATION_BODY_INVALID",
                    "Function/method body must be Block or Expression.",
                    node.kind,
                    span if isinstance(span, SourceSpan) else None,
                )
            )
    if schema_version != ("2.1" if has_receiver_qualifier else "2.0"):
        issues.append(
            SchemaIssue(
                "AST_RECEIVER_REVISION_MISMATCH",
                "AST 2.1 and explicit method receiver qualifiers must occur together.",
                getattr(program, "kind", None),
                getattr(program, "span", None),
            )
        )
    return SchemaReport(
        ok=not issues,
        schema_version=schema_version,
        language=language,
        pine_version=context.pine_version if isinstance(context, PineVersionContext) else None,
        version_context=context.to_dict() if isinstance(context, PineVersionContext) else None,
        node_count=node_count,
        kind_counts=kind_counts,
        issues=issues,
    )


__all__ = ["SchemaIssue", "SchemaReport", "validate_ast_schema"]
