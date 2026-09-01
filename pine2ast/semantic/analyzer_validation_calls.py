from __future__ import annotations


from pine2ast.ast.base import Expression
from pine2ast.ast.nodes import (
    CallExpr,
    Identifier,
    MemberAccessExpr,
    FieldDeclaration,
    Parameter,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.symbols import SymbolKind
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.semantic.collection_signatures import (
    is_collection_method,
)
from pine2ast.semantic.analyzer_contract import AnalyzerMixinHost


class AnalyzerCallValidationMixin(AnalyzerMixinHost):
    """Focused semantic validation mixin extracted for Pine2AST 4.0."""

    def _validate_udt_constructor_call(self, expr: CallExpr) -> None:
        if not isinstance(expr.callee, MemberAccessExpr) or expr.callee.member != "new":
            return
        if not isinstance(expr.callee.object, Identifier):
            return
        type_name = expr.callee.object.name
        type_sym = self._resolve(type_name)
        if type_sym is None or type_sym.kind is not SymbolKind.TYPE:
            return
        fields = self._udt_fields.get(type_name)
        if fields is None:
            fields = [
                FieldDeclaration(sym.declared_at, sym.name.split(".", 1)[1], type_ref=None)  # type: ignore[arg-type]
                for sym in self.model.symbols.values()
                if sym.kind is SymbolKind.FIELD and sym.name.startswith(f"{type_name}.")
            ]
        field_names = [f.name for f in fields]
        required = [f.name for f in fields if getattr(f, "default_value", None) is None]
        positional = [a for a in expr.arguments if a.name is None]
        named = {a.name for a in expr.arguments if a.name}
        for arg in expr.arguments:
            if arg.name and arg.name not in field_names:
                self._diag(
                    Severity.ERROR,
                    codes.UNKNOWN_PARAMETER,
                    f"Unknown field {arg.name} for UDT constructor {type_name}.new().",
                    arg.span,
                )
        if len(positional) > len(field_names):
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Too many positional arguments for {type_name}.new().",
                expr.span,
            )
        positional_field_names = field_names[: len(positional)]
        for arg in expr.arguments:
            if arg.name and arg.name in positional_field_names:
                self._diag(
                    Severity.ERROR,
                    codes.DUPLICATE_NAMED_ARGUMENT,
                    f"Field {arg.name} for {type_name}.new() is supplied both positionally and by name.",
                    arg.span,
                )
        supplied = set(positional_field_names) | {n for n in named if n in field_names}
        missing = [name for name in required if name not in supplied]
        if missing:
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Missing required field(s) for {type_name}.new(): {', '.join(missing)}.",
                expr.span,
            )
        for idx, arg in enumerate(positional):
            if idx < len(fields):
                expected = (
                    self._type_ref_name(fields[idx].type_ref)
                    if getattr(fields[idx], "type_ref", None) is not None
                    else None
                )
                actual = self._infer_type(arg.value)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Field {field_names[idx]} for {type_name}.new() expects {expected}, got {actual}.",
                        arg.span,
                    )
                self._validate_bool_cannot_be_na(expected, arg.value)
        for arg in expr.arguments:
            if arg.name and arg.name in field_names:
                field = fields[field_names.index(arg.name)]
                expected = (
                    self._type_ref_name(field.type_ref)
                    if getattr(field, "type_ref", None) is not None
                    else None
                )
                actual = self._infer_type(arg.value)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Field {arg.name} for {type_name}.new() expects {expected}, got {actual}.",
                        arg.span,
                    )
                self._validate_bool_cannot_be_na(expected, arg.value)

    def _is_builtin_namespace_root(self, expr: Expression) -> bool:
        if isinstance(expr, Identifier):
            sym = self._resolve(expr.name)
            return (
                sym is not None
                and sym.kind is SymbolKind.BUILTIN
                and sym.type in {None, "namespace"}
            )
        return False

    def _is_external_alias_root(self, expr: Expression) -> bool:
        if isinstance(expr, Identifier):
            return expr.name in self._external_aliases
        if isinstance(expr, MemberAccessExpr):
            return self._is_external_alias_root(expr.object)
        return False

    def _is_collection_method(self, receiver_type: str | None, member: str) -> bool:
        if not receiver_type:
            return False
        if receiver_type == "footprint":
            return member in {"buy_volume", "sell_volume", "delta"}
        return is_collection_method(receiver_type, member)

    def _validate_member_call_target(self, name: str, expr: CallExpr) -> None:
        if not isinstance(expr.callee, MemberAccessExpr):
            return
        if self.registry.get("functions", {}).get(name):
            return
        member = expr.callee.member
        receiver_expr = expr.callee.object
        if isinstance(receiver_expr, Identifier) and member == "new":
            sym = self._resolve(receiver_expr.name)
            if sym is not None and sym.kind is SymbolKind.TYPE:
                return
        if self._is_external_alias_root(receiver_expr) or self._is_builtin_namespace_root(
            receiver_expr
        ):
            return

        receiver_type = self._infer_type(receiver_expr)
        field_type = self._member_field_type(expr.callee)
        if field_type is not None:
            self._diag(
                Severity.ERROR,
                codes.TYPE_MISMATCH,
                f"Field {member} of type {receiver_type} is not callable.",
                expr.callee.span,
            )
            return
        if member in self._method_receivers:
            return
        if self._is_collection_method(receiver_type, member):
            return
        if receiver_type in self._udt_fields:
            self._diag(
                Severity.ERROR,
                codes.UNKNOWN_FIELD,
                f"Unknown method or field {member} for type {receiver_type}.",
                expr.callee.span,
            )
            return
        if receiver_type and receiver_type not in {"unknown", "external", "function", "method"}:
            self._diag(
                Severity.ERROR,
                codes.UNKNOWN_FIELD,
                f"Unknown method {member} for type {receiver_type}.",
                expr.callee.span,
            )

    def _validate_method_call(self, expr: CallExpr) -> None:
        if not isinstance(expr.callee, MemberAccessExpr):
            return
        method_name = expr.callee.member
        receiver_type = self._method_receivers.get(method_name)
        if receiver_type is None:
            return
        actual = self._infer_type(expr.callee.object)
        valid_receivers = receiver_type if isinstance(receiver_type, set) else {receiver_type}

        def _receiver_matches(candidate: str, valid_set: set[str]) -> bool:
            # Exact match always wins.
            if candidate in valid_set:
                return True
            # Generic container receiver (e.g. receiver_type='array') matches
            # any typed variant ('array<float>', 'array<int>', ...).
            for vr in valid_set:
                if vr and not vr.endswith("<") and not vr.endswith("<>"):
                    if candidate.startswith(vr + "<"):
                        return True
            return False

        if not _receiver_matches(actual, valid_receivers) and actual != "unknown":
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_TYPE,
                f"Method {method_name} expects receiver {sorted(valid_receivers)}, got {actual}.",
                expr.callee.span,
            )
            return
        if self._is_collection_method(actual, method_name):
            # Collection receivers are generic (array<T>, matrix<T>, map<K,V>),
            # so method-form validation is delegated to CollectionValidationPass
            # where receiver-specialized parameter types are available. Registry
            # entries remain machine-readable for coverage/OpenPine metadata.
            return
        # Look up params in this order:
        #  1. User-defined methods (UDT method declarations).
        #  2. Builtin methods with full signature in the registry.
        # Builtin methods registered as _signature_pending are skipped
        # here — codegen/runtime layers own their parameter validation.
        params: list[Parameter] | None = self._user_method_params.get((actual, method_name))
        if params is None:
            for (receiver, name), candidate_params in self._user_method_params.items():
                if name == method_name and _receiver_matches(actual, {receiver}):
                    params = candidate_params
                    break
        if params is None and method_name in self._builtin_method_params:
            if actual in self._builtin_method_params[method_name]:
                params = self._builtin_method_params[method_name][actual]
            else:
                for key in self._builtin_method_params[method_name]:
                    if not key.endswith("<") and not key.endswith("<>"):
                        if actual.startswith(key + "<"):
                            params = self._builtin_method_params[method_name][key]
                            break
        if params is None:
            return
        self._validate_param_call(method_name, params, expr.arguments, expr.span, kind="method")

    def _validate_user_function_call(self, name: str, expr: CallExpr) -> None:
        params = self._function_params.get(name)
        if params is None:
            return
        self._validate_param_call(name, params, expr.arguments, expr.span, kind="function")

    def _validate_param_call(
        self, name: str, params: list[Parameter], args: list, span: SourceSpan, *, kind: str
    ) -> None:
        known = {p.name for p in params}
        required = [p.name for p in params if p.default_value is None]
        positional = [a for a in args if a.name is None]
        named = {a.name for a in args if a.name}
        for arg in args:
            if arg.name and arg.name not in known:
                self._diag(
                    Severity.ERROR,
                    codes.UNKNOWN_PARAMETER,
                    f"Unknown parameter {arg.name} for {kind} {name}.",
                    arg.span,
                )
        if len(positional) > len(params):
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Too many positional arguments for {kind} {name}.",
                span,
            )
        positional_param_names = [p.name for p in params[: len(positional)]]
        for arg in args:
            if arg.name and arg.name in positional_param_names:
                self._diag(
                    Severity.ERROR,
                    codes.DUPLICATE_NAMED_ARGUMENT,
                    f"Parameter {arg.name} for {kind} {name} is supplied both positionally and by name.",
                    arg.span,
                )
        supplied = set(positional_param_names) | (named & known)
        missing = [param for param in required if param not in supplied]
        if missing:
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Missing required parameter(s) for {name}: {', '.join(missing)}.",
                span,
            )
        for idx, arg in enumerate(positional):
            if idx < len(params) and params[idx].type_ref is not None:
                expected = self._type_ref_name(params[idx].type_ref)
                actual = self._infer_type(arg.value)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Argument {params[idx].name} for {name} expects {expected}, got {actual}.",
                        arg.span,
                    )
                self._validate_bool_cannot_be_na(expected, arg.value)
        by_name = {p.name: p for p in params}
        for arg in args:
            if arg.name and arg.name in by_name and by_name[arg.name].type_ref is not None:
                expected = self._type_ref_name(by_name[arg.name].type_ref)
                actual = self._infer_type(arg.value)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Argument {arg.name} for {name} expects {expected}, got {actual}.",
                        arg.span,
                    )
                self._validate_bool_cannot_be_na(expected, arg.value)

    def _validate_builtin_call(self, name: str, entry: dict | None, expr: CallExpr) -> None:
        if not entry:
            return
        resolution = SignatureResolver(version_context=self.version_context).resolve_builtin(
            name,
            entry,
            expr.arguments,
            expr.span,
            kind="builtin",
            symbols=self.model.symbols,
            validate_types=True,
            validate_qualifiers=True,
        )
        for issue in resolution.issues:
            self._diag(issue.severity, issue.code, issue.message, issue.span)
        for resolved in resolution.resolved_arguments:
            arg = resolved.argument
            if arg is None:
                raise RuntimeError("source argument resolution is missing its AST argument")
            param = resolved.parameter
            if param and param.get("unsupported"):
                self._diag(
                    Severity.ERROR,
                    param.get("unsupported_diagnostic_code") or codes.UNSUPPORTED_FEATURE,
                    f"Parameter {param.get('name')} for builtin {name} is intentionally unsupported by this parser/semantic layer.",
                    arg.span,
                )

    def _param_removed_in_current_version(self, param: dict) -> bool:
        removed_in = param.get("removed_in")
        return bool(removed_in and self.version_context.pine_version >= int(removed_in))

    def _validate_argument_qualifier(self, callee: str, arg, param: dict | None) -> None:
        if not param:
            return
        max_q = param.get("qualifier_max")
        if not max_q:
            return
        order = {"const": 0, "input": 1, "simple": 2, "series": 3}
        q = self._infer_qualifier(arg.value)
        if order.get(q, 3) > order.get(max_q, 3):
            pname = param.get("name") or "<positional>"
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_QUALIFIER,
                f"Argument {pname} for {callee} requires {max_q} or weaker qualifier, got {q}.",
                arg.span,
            )
