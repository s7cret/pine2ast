from __future__ import annotations


from pine2ast.ast.base import Expression
from pine2ast.ast.nodes import (
    Block,
    ConditionalExpr,
    DeclarationStatement,
    EnumDeclaration,
    FunctionDeclaration,
    IfStructure,
    ForRangeStructure,
    ForInStructure,
    WhileStructure,
    ImportDeclaration,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Reassignment,
    SwitchStructure,
    TupleDeclaration,
    TupleExpr,
    TypeDeclaration,
    VarDeclaration,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.scopes import ScopeKind
from pine2ast.semantic.symbols import SymbolKind
from pine2ast.semantic.passes.export_policy import validate_export_policy
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.semantic.analyzer_contract import AnalyzerMixinHost


class AnalyzerStatementMixin(AnalyzerMixinHost):
    """Implementation mixin split out of :mod:`pine2ast.semantic.analyzer`."""

    _script_type: str | None

    def _analyze_declaration_statement(self, node: DeclarationStatement) -> None:
        self._script_type = node.script_type
        self._visit_expr(node.call)
        for arg in node.call.arguments:
            if self._infer_qualifier(arg.value) not in {
                "const",
                "input",
            } and arg.name in {"title", "overlay", None}:
                self._diag(
                    Severity.ERROR,
                    codes.DECLARATION_ARGS_NOT_CONST,
                    "Declaration statement arguments must be const-compatible in Pine.",
                    arg.span,
                )

    def _s_declaration_statement(self, node: DeclarationStatement) -> None:
        if self.local_depth > 0 or self.function_depth > 0:
            self._diag(
                Severity.ERROR,
                codes.DECLARATION_NOT_GLOBAL,
                "indicator/strategy/library declaration must be in global scope.",
                node.span,
            )
        self._analyze_declaration_statement(node)

    def _s_var_declaration(self, node: VarDeclaration) -> None:
        validate_export_policy(self, node)
        init_type = self._infer_type(node.initializer)
        if init_type == "void":
            self._diag(
                Severity.ERROR,
                codes.TYPE_MISMATCH,
                "A void statement or function cannot initialize a variable.",
                node.initializer.span,
            )
        explicit_type = self._type_ref_name(node.type_ref) if node.type_ref else init_type
        if (
            node.type_ref is None
            and isinstance(node.initializer, Literal)
            and node.initializer.literal_type == "na"
            and self.policy.requires_explicit_na_type
        ):
            self._diag(
                Severity.ERROR,
                codes.NA_DECLARATION_TYPE_REQUIRED,
                (
                    f"Pine v{self.version_context.pine_version} requires an explicit "
                    "type when a variable is initialized with na."
                ),
                node.span,
            )
        if node.type_ref is not None:
            self._validate_type_ref(node.type_ref)
        self._visit_expr(node.initializer)
        self._validate_bool_cannot_be_na(explicit_type, node.initializer)
        if node.type_ref is not None and not self._is_assignable_type(explicit_type, init_type):
            self._diag(
                Severity.ERROR,
                codes.TYPE_MISMATCH,
                f"Initializer for {node.name} expects {explicit_type}, got {init_type}.",
                node.initializer.span,
            )
        init_qualifier = self._infer_qualifier(node.initializer)
        qualifier: str
        if node.explicit_qualifier:
            qualifier = node.explicit_qualifier
            self._validate_qualifier_assignment(
                node.explicit_qualifier,
                init_qualifier,
                node.initializer.span,
                f"Initializer for {node.name}",
            )
        else:
            if init_qualifier == "input":
                qualifier = "input"
            elif init_qualifier in {"const", "simple"} and not self._is_reassigned_declaration(node):
                qualifier = init_qualifier
            else:
                qualifier = "series"
        if id(node) in self._predeclared_nodes:
            symbol = self._resolve(node.name)
            if symbol is None:
                raise RuntimeError("predeclared Pine variable disappeared before analysis")
            symbol.type = explicit_type
            symbol.qualifier = qualifier
            symbol.declared_at = node.span
        else:
            self._define(node.name, SymbolKind.VARIABLE, node.span, explicit_type, qualifier)

    def _s_tuple_declaration(self, node: TupleDeclaration) -> None:
        self._visit_expr(node.initializer)
        init_type = self._infer_type(node.initializer)
        element_types = self._tuple_element_types(init_type)
        init_qualifier = self._infer_qualifier(node.initializer)
        if not element_types:
            self._diag(
                Severity.ERROR,
                codes.TYPE_MISMATCH,
                f"Tuple declaration initializer must return a tuple, got {init_type}.",
                node.initializer.span,
            )
        elif len(node.targets) != len(element_types):
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Tuple declaration target count {len(node.targets)} does not match initializer arity {len(element_types)}.",
                node.span,
            )
        for index, target in enumerate(node.targets):
            if target.name != "_":
                target_type = element_types[index] if index < len(element_types) else "unknown"
                self._define(
                    target.name,
                    SymbolKind.VARIABLE,
                    target.span,
                    target_type,
                    init_qualifier if init_qualifier == "input" else "series",
                )

    def _s_reassignment(self, node: Reassignment) -> None:
        self._visit_expr(node.value)
        value_type = self._infer_type(node.value)
        if isinstance(node.target, MemberAccessExpr):
            root_sym = self._resolve_assignable(node.target)
            field_type = self._member_field_type(node.target)
            owner_type = self._member_owner_type(node.target)
            if root_sym is None:
                target_name = self._assignable_name(node.target) or "<expr>"
                code = codes.REASSIGN_UNDECLARED if node.op == ":=" else codes.COMPOUND_UNDECLARED
                self._diag(
                    Severity.ERROR,
                    code,
                    f"Reassignment to undeclared variable {target_name}.",
                    node.span,
                )
                return
            if root_sym.qualifier == "const":
                self._diag(
                    Severity.ERROR,
                    codes.CONST_REASSIGNMENT,
                    f"Cannot reassign const symbol {root_sym.name}.",
                    node.span,
                )
                return
            if owner_type in self._udt_fields and field_type is None:
                self._diag(
                    Severity.ERROR,
                    codes.UNKNOWN_FIELD,
                    f"Unknown field {node.target.member} for type {owner_type}.",
                    node.target.span,
                )
                return
            if field_type is not None:
                if node.op in {"+=", "-=", "*=", "/=", "%="} and field_type not in {
                    "int",
                    "float",
                    "unknown",
                    None,
                }:
                    self._diag(
                        Severity.ERROR,
                        codes.TYPE_MISMATCH,
                        f"Compound assignment {node.op} requires numeric field, got {field_type}.",
                        node.span,
                    )
                elif not self._is_assignable_type(field_type, value_type):
                    self._diag(
                        Severity.ERROR,
                        codes.TYPE_MISMATCH,
                        f"Cannot assign {value_type} to field {node.target.member} of type {field_type}.",
                        node.value.span,
                    )
                self._validate_bool_cannot_be_na(field_type, node.value)
                return
        sym = self._resolve_assignable(node.target)
        if sym is None:
            target_name = self._assignable_name(node.target) or "<expr>"
            code = codes.REASSIGN_UNDECLARED if node.op == ":=" else codes.COMPOUND_UNDECLARED
            self._diag(
                Severity.ERROR,
                code,
                f"Reassignment to undeclared variable {target_name}.",
                node.span,
            )
        elif sym.qualifier == "const":
            self._diag(
                Severity.ERROR,
                codes.CONST_REASSIGNMENT,
                f"Cannot reassign const symbol {sym.name}.",
                node.span,
            )
        else:
            if node.op in {"+=", "-=", "*=", "/=", "%="} and sym.type not in {
                "int",
                "float",
                "unknown",
                None,
            }:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Compound assignment {node.op} requires numeric target, got {sym.type}.",
                    node.span,
                )
            elif not self._is_assignable_type(sym.type, value_type):
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Cannot assign {value_type} to {sym.name} of type {sym.type}.",
                    node.value.span,
                )
            self._validate_bool_cannot_be_na(sym.type, node.value)

    def _s_function_declaration(self, node: FunctionDeclaration) -> None:
        validate_export_policy(self, node)
        if self.local_depth > 0 or self.function_depth > 0:
            self._diag(
                Severity.ERROR,
                codes.NESTED_FUNCTION,
                "Function definitions are allowed only in global scope.",
                node.span,
            )
        if id(node) not in self._predeclared_nodes:
            self._define(node.name, SymbolKind.FUNCTION, node.span, "function", None)
            self._function_params[node.name] = node.parameters
        self.function_depth += 1
        self._push_scope(ScopeKind.FUNCTION)
        for p in node.parameters:
            qualifier = parameter_qualifier(p, self.model)
            if p.type_ref is not None:
                self._validate_type_ref(p.type_ref)
            if p.default_value is not None:
                self._visit_expr(p.default_value)
                expected = self._type_ref_name(p.type_ref) if p.type_ref else None
                actual = self._infer_type(p.default_value)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.TYPE_MISMATCH,
                        f"Default value for parameter {p.name} expects {expected}, got {actual}.",
                        p.default_value.span,
                    )
                self._validate_bool_cannot_be_na(expected, p.default_value)
                if qualifier is not None:
                    self._validate_qualifier_assignment(
                        qualifier,
                        self._infer_qualifier(p.default_value),
                        p.default_value.span,
                        f"Default value for parameter {p.name}",
                    )
            self._define(
                p.name,
                SymbolKind.VARIABLE,
                p.span,
                self._type_ref_name(p.type_ref) if p.type_ref else "unknown",
                qualifier,
            )
        self._visit_body(node.body)
        owner = self.model.function_candidates
        candidate = owner.by_node.get(id(node)) if owner is not None else None
        sym = self.model.symbols.get(candidate.symbol_key) if candidate is not None else self._resolve(node.name)
        if sym is not None:
            sym.type = self._body_return_type(node.body)
        self._pop_scope()
        self.function_depth -= 1

    def _s_method_declaration(self, node: MethodDeclaration) -> None:
        validate_export_policy(self, node)
        if self.local_depth > 0 or self.function_depth > 0:
            self._diag(
                Severity.ERROR,
                codes.NESTED_FUNCTION,
                "Method definitions are allowed only in global scope.",
                node.span,
            )
        if node.receiver_type is None or node.receiver_name is None:
            self._diag(
                Severity.ERROR,
                codes.METHOD_RECEIVER_REQUIRED,
                "Method receiver must have explicit type.",
                node.span,
            )
        elif self._resolve(node.receiver_type.name) is None:
            self._diag(
                Severity.ERROR,
                codes.METHOD_RECEIVER_TYPE_NOT_FOUND,
                f"Method receiver type {node.receiver_type.name} is not declared.",
                node.receiver_type.span,
            )
        if id(node) not in self._predeclared_nodes:
            self._define(
                node.name,
                SymbolKind.METHOD,
                node.span,
                "method",
                None,
                allow_existing=True,
            )
            if node.receiver_type is not None:
                rt = self._type_ref_name(node.receiver_type)
                method_key = (rt, node.name)
                self._user_method_params.setdefault(method_key, node.parameters)
                existing = self._method_receivers.get(node.name)
                if isinstance(existing, set):
                    existing.add(rt)
                elif isinstance(existing, str):
                    self._method_receivers[node.name] = {existing, rt}
                else:
                    self._method_receivers[node.name] = rt
        self._push_scope(ScopeKind.METHOD)
        if node.receiver_name:
            self._define(
                node.receiver_name,
                SymbolKind.VARIABLE,
                node.span,
                self._type_ref_name(node.receiver_type) if node.receiver_type else "unknown",
                (
                    self.model.method_candidates.receiver_qualifier(node)
                    if self.model.method_candidates is not None
                    else node.receiver_explicit_qualifier or "series"
                ),
            )
        for p in node.parameters:
            if p.type_ref is not None:
                self._validate_type_ref(p.type_ref)
            if p.default_value is not None:
                self._visit_expr(p.default_value)
                expected = self._type_ref_name(p.type_ref) if p.type_ref else None
                actual = self._infer_type(p.default_value)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.TYPE_MISMATCH,
                        f"Default value for parameter {p.name} expects {expected}, got {actual}.",
                        p.default_value.span,
                    )
                self._validate_bool_cannot_be_na(expected, p.default_value)
                if p.explicit_qualifier is not None:
                    self._validate_qualifier_assignment(
                        p.explicit_qualifier,
                        self._infer_qualifier(p.default_value),
                        p.default_value.span,
                        f"Default value for parameter {p.name}",
                    )
            self._define(
                p.name,
                SymbolKind.VARIABLE,
                p.span,
                self._type_ref_name(p.type_ref) if p.type_ref else "unknown",
                p.explicit_qualifier,
            )
        self._visit_body(node.body)
        receiver_type = self._type_ref_name(node.receiver_type) if node.receiver_type else ""
        owner = self.model.method_candidates
        candidate = owner.by_node.get(id(node)) if owner is not None else None
        sym = self._resolve(
            candidate.symbol_key if candidate is not None else f"{receiver_type}.{node.name}"
        )
        if sym is not None:
            sym.type = self._body_return_type(node.body)
        self._pop_scope()

    def _s_type_declaration(self, node: TypeDeclaration) -> None:
        validate_export_policy(self, node)
        if id(node) not in self._predeclared_nodes:
            self._define(node.name, SymbolKind.TYPE, node.span, "type", None)
        self._udt_fields[node.name] = node.fields
        seen_fields: set[str] = set()
        for field in node.fields:
            if field.name in seen_fields:
                self._diag(
                    Severity.ERROR,
                    codes.REDECLARATION,
                    f"Duplicate field {field.name} in type {node.name}.",
                    field.span,
                )
            seen_fields.add(field.name)
        self._push_scope(ScopeKind.TYPE_DECL)
        for field in node.fields:
            self._validate_type_ref(field.type_ref)
            field_type = self._type_ref_name(field.type_ref)
            self._define(field.name, SymbolKind.FIELD, field.span, field_type, "series")
            self._define(
                f"{node.name}.{field.name}",
                SymbolKind.FIELD,
                field.span,
                field_type,
                "series",
                allow_existing=True,
            )
            if field.default_value is not None:
                self._visit_expr(field.default_value)
                default_type = self._infer_type(field.default_value)
                if not self._is_assignable_type(field_type, default_type):
                    self._diag(
                        Severity.ERROR,
                        codes.TYPE_MISMATCH,
                        f"Default value for field {field.name} expects {field_type}, got {default_type}.",
                        field.default_value.span,
                    )
                self._validate_bool_cannot_be_na(field_type, field.default_value)
        self._pop_scope()

    def _s_enum_declaration(self, node: EnumDeclaration) -> None:
        validate_export_policy(self, node)
        if id(node) not in self._predeclared_nodes:
            self._define(node.name, SymbolKind.ENUM, node.span, "enum", None)
        seen_members: set[str] = set()
        for m in node.members:
            if m.name in seen_members:
                self._diag(
                    Severity.ERROR,
                    codes.REDECLARATION,
                    f"Duplicate enum member {m.name} in enum {node.name}.",
                    m.span,
                )
                continue
            seen_members.add(m.name)
            self._define(
                f"{node.name}.{m.name}",
                SymbolKind.ENUM_MEMBER,
                m.span,
                node.name,
                "const",
                allow_existing=True,
            )
        self._enum_members[node.name] = seen_members

    def _s_import_declaration(self, node: ImportDeclaration) -> None:
        alias = node.alias or node.library or node.owner or node.path
        if id(node) not in self._predeclared_nodes:
            self._define(alias, SymbolKind.IMPORT_ALIAS, node.span, "external", None)
            self._external_aliases.add(alias)

    def _body_return_type(self, body) -> str:
        if isinstance(body, Block):
            if not body.statements:
                return "void"
            last = body.statements[-1]
            if isinstance(
                last,
                (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure),
            ):
                return self._infer_type(last)
            if hasattr(last, "expression"):
                return self._infer_type(last.expression)
            if hasattr(last, "initializer"):
                return self._infer_type(last.initializer)
            if hasattr(last, "value"):
                return self._infer_type(last.value)
            return "void"
        return self._infer_type(body)

    def _body_return_shape(self, body) -> str | None:
        """Best-effort return shape usable during global predeclaration.

        The shape pass is deliberately syntax-only: it preserves tuple arity and
        obvious scalar return types for forward function calls before local symbols
        are available. Exact types are refined later by `_body_return_type()`.
        """
        target = self._body_return_expr(body)
        if target is None:
            return "void" if isinstance(body, Block) else None
        return self._static_return_shape(target)

    def _body_return_expr(self, body):
        if isinstance(body, Block):
            if not body.statements:
                return None
            last = body.statements[-1]
            if isinstance(
                last,
                (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure),
            ):
                return last
            return (
                getattr(last, "expression", None)
                or getattr(last, "initializer", None)
                or getattr(last, "value", None)
            )
        return body

    def _static_return_shape(self, expr) -> str | None:
        if isinstance(expr, TupleExpr):
            return (
                "tuple<"
                + ",".join(self._static_return_shape(item) or "unknown" for item in expr.elements)
                + ">"
            )
        if isinstance(expr, Literal):
            return expr.literal_type
        if isinstance(expr, ConditionalExpr):
            left = self._static_return_shape(expr.if_true)
            right = self._static_return_shape(expr.if_false)
            return self._merge_return_shapes([left, right])
        if isinstance(
            expr, (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure)
        ):
            from pine2ast.semantic.control_values import returned_expressions

            return self._merge_return_shapes(
                [self._static_return_shape(value) for value in returned_expressions(expr)]
            )
        return None

    def _merge_return_shapes(self, shapes: list[str | None]) -> str | None:
        known = [shape for shape in shapes if shape]
        if not known:
            return None
        if all(shape == known[0] for shape in known):
            return known[0]
        if set(known) <= {"int", "float"}:
            return "float"
        if all(shape.startswith("tuple<") and shape.endswith(">") for shape in known):
            split = [self._split_type_args(shape[len("tuple<") : -1]) for shape in known]
            if split and all(len(parts) == len(split[0]) for parts in split):
                merged = [
                    self._merge_return_shapes([parts[i] for parts in split]) or "unknown"
                    for i in range(len(split[0]))
                ]
                return "tuple<" + ",".join(merged) + ">"
        return None

    def _visit_body(self, body: Block | Expression) -> None:
        if isinstance(body, Block):
            self._visit_block(body)
        else:
            self._visit_expr(body)

    def _visit_block(
        self,
        block: Block,
        *,
        kind: ScopeKind = ScopeKind.LOCAL_BLOCK,
        non_na_symbols: set[str] | None = None,
        non_na_paths: set[str] | None = None,
    ) -> None:
        self.local_depth += 1
        self._push_scope(kind, non_na_symbols=non_na_symbols, non_na_paths=non_na_paths)
        for st in block.statements:
            self._visit_statement(st)
        self._pop_scope()
        self.local_depth -= 1
