from __future__ import annotations


from pine2ast.ast.nodes import (
    Identifier,
    MemberAccessExpr,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.scopes import ScopeKind
from pine2ast.semantic.symbols import SymbolKind
from pine2ast.semantic.analyzer_contract import AnalyzerMixinHost


class AnalyzerMemberValidationMixin(AnalyzerMixinHost):
    """Focused semantic validation mixin extracted for Pine2AST 4.0."""

    def _member_owner_type(self, expr: MemberAccessExpr) -> str | None:
        if isinstance(expr.object, Identifier):
            sym = self._resolve(expr.object.name)
            return sym.type if sym is not None else None
        if isinstance(expr.object, MemberAccessExpr):
            return self._infer_type(expr.object)
        return None

    def _member_field_type(self, expr: MemberAccessExpr) -> str | None:
        owner_type = self._member_owner_type(expr)
        if not owner_type:
            return None
        sym = self._resolve(f"{owner_type}.{expr.member}")
        return sym.type if sym is not None else None

    def _validate_member_access(self, expr: MemberAccessExpr) -> None:
        if isinstance(expr.object, Identifier):
            owner_sym = self._resolve(expr.object.name)
            if owner_sym is not None and owner_sym.kind is SymbolKind.ENUM:
                if f"{expr.object.name}.{expr.member}" not in self.model.symbols:
                    self._diag(
                        Severity.ERROR,
                        codes.UNKNOWN_FIELD,
                        f"Unknown enum member {expr.member} for enum {expr.object.name}.",
                        expr.span,
                    )
                return
        owner_type = self._member_owner_type(expr)
        if owner_type not in self._udt_fields:
            return
        if self._member_field_type(expr) is None:
            self._diag(
                Severity.ERROR,
                codes.UNKNOWN_FIELD,
                f"Unknown field {expr.member} for type {owner_type}.",
                expr.span,
            )

    def _scope_kind(self, scope_id: int | None) -> ScopeKind | None:
        if scope_id is None:
            return None
        for scope in self.model.scopes:
            if scope.id == scope_id:
                return scope.kind
        return None
