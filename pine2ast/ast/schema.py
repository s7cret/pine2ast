from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pine2ast.ast.base import ASTNode
from pine2ast.ast.visitors import walk
from pine2ast.lexer.token import SourceSpan


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
            "span": self.span.to_dict() if self.span is not None else None,
        }


@dataclass(slots=True)
class SchemaReport:
    ok: bool
    schema_version: str | None
    language: str | None
    language_version: int | None
    node_count: int
    kind_counts: dict[str, int] = field(default_factory=dict)
    issues: list[SchemaIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_version": self.schema_version,
            "language": self.language,
            "language_version": self.language_version,
            "node_count": self.node_count,
            "kind_counts": dict(sorted(self.kind_counts.items())),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _span_order_valid(span: SourceSpan) -> bool:
    return (
        span.start_offset <= span.end_offset
        and span.start_line >= 1
        and span.end_line >= span.start_line
        and span.start_col >= 1
        and span.end_col >= 1
    )


def validate_ast_schema(program: ASTNode) -> SchemaReport:
    """Validate Pine2AST's stable JSON-facing AST contract.

    This is intentionally structural, not semantic: it checks that every AST node has
    a kind/span, that spans are sane, and that the Program-level schema metadata is
    present for downstream AST2Python/optimizer consumers.
    """
    issues: list[SchemaIssue] = []
    seen_ids: set[int] = set()
    kind_counts: dict[str, int] = {}
    node_count = 0

    schema_version = getattr(program, "schema_version", None)
    language = getattr(program, "language", None)
    language_version = getattr(program, "language_version", None)

    if schema_version is None:
        issues.append(
            SchemaIssue(
                "AST_SCHEMA_VERSION_MISSING",
                "Program.schema_version is required.",
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
    if language_version != 6:
        issues.append(
            SchemaIssue(
                "AST_LANGUAGE_VERSION_INVALID",
                "Program.language_version must be 6 for this package version.",
                getattr(program, "kind", None),
                getattr(program, "span", None),
            )
        )

    for node in walk(program):
        node_count += 1
        obj_id = id(node)
        if obj_id in seen_ids:
            issues.append(
                SchemaIssue(
                    "AST_SHARED_NODE",
                    "AST node object is referenced more than once.",
                    node.kind,
                    node.span,
                )
            )
            continue
        seen_ids.add(obj_id)
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1
        span = getattr(node, "span", None)
        if not isinstance(span, SourceSpan):
            issues.append(
                SchemaIssue(
                    "AST_SPAN_MISSING", "Every AST node must carry SourceSpan.", node.kind, None
                )
            )
        elif not _span_order_valid(span):
            issues.append(
                SchemaIssue(
                    "AST_SPAN_INVALID",
                    "AST node span has invalid ordering or coordinates.",
                    node.kind,
                    span,
                )
            )

    return SchemaReport(
        ok=not issues,
        schema_version=schema_version,
        language=language,
        language_version=language_version,
        node_count=node_count,
        kind_counts=kind_counts,
        issues=issues,
    )
