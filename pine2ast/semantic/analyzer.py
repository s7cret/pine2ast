from __future__ import annotations

from dataclasses import dataclass, field

from pine2ast.ast.base import ASTNode, Expression, Statement
from pine2ast.ast.nodes import (
    BinaryExpr,
    Block,
    BreakStatement,
    CallExpr,
    ConditionalExpr,
    ContinueStatement,
    DeclarationStatement,
    EnumDeclaration,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    ImportDeclaration,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Program,
    Reassignment,
    SwitchStructure,
    TupleDeclaration,
    TupleExpr,
    TypeDeclaration,
    FieldDeclaration,
    Parameter,
    UnaryExpr,
    VarDeclaration,
    WhileStructure,
)
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.builtin_registry import (
    KNOWN_DEFERRED_NAMESPACE_MEMBERS,
    KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS,
    load_builtin_registry,
)
from pine2ast.semantic.qualifier_infer import infer_qualifier
from pine2ast.semantic.scopes import Scope, ScopeKind
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_infer import callee_name, infer_type
from pine2ast.semantic.passes import (
    BuiltinValidationPass,
    DeclarationCardinalityPass,
    DeclarationIndexPass,
    QualifierInferencePass,
    ScopeSymbolPass,
    StrategyContextValidationPass,
    TypeInferencePass,
    UnsupportedFeatureExtractionPass,
)
from pine2ast.semantic.pipeline import AnalyzerPassPipeline, PassResult


@dataclass(slots=True)
class SemanticModel:
    symbols: dict[str, Symbol] = field(default_factory=dict)
    scopes: list[Scope] = field(default_factory=list)
    node_types: dict[int, str] = field(default_factory=dict)
    node_qualifiers: dict[int, str] = field(default_factory=dict)
    non_na_scopes: dict[int, set[str]] = field(default_factory=dict)
    # Scope-local flow facts for `not na(x)`, `not na(obj.field)`, and `if na(x) ... else`.
    # Values are stable source-level paths, not object references, so reports remain JSON-safe.
    non_na_paths: dict[int, set[str]] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class SemanticAnalyzer:
    def __init__(
        self, *, max_diagnostics: int = 200, strict_builtin_namespaces: bool = False
    ) -> None:
        self.registry = load_builtin_registry()
        self.model = SemanticModel()
        self.max_diagnostics = max_diagnostics
        self.strict_builtin_namespaces = strict_builtin_namespaces
        self.scope_stack: list[Scope] = []
        self.next_symbol_id = 1
        self.loop_depth = 0
        self.local_depth = 0
        self.function_depth = 0
        self._predeclared_nodes: set[int] = set()
        self._function_params: dict[str, list[Parameter]] = {}
        self._method_receivers: dict[str, str] = {}
        self._external_aliases: set[str] = set()
        self._udt_fields: dict[str, list[FieldDeclaration]] = {}
        self._enum_members: dict[str, set[str]] = {}
        self._symbol_history: dict[str, list[Symbol]] = {}
        self._script_type: str | None = None
        self.pass_results: tuple[PassResult, ...] = ()

    def analyze(self, program: Program) -> SemanticModel:
        self._push_scope(ScopeKind.GLOBAL)
        pipeline = AnalyzerPassPipeline(
            (
                DeclarationIndexPass(self),
                ScopeSymbolPass(self),
                TypeInferencePass(self),
                QualifierInferencePass(self),
                BuiltinValidationPass(self),
                StrategyContextValidationPass(self),
                UnsupportedFeatureExtractionPass(self),
                DeclarationCardinalityPass(self),
            )
        )
        self.pass_results = pipeline.run(
            program, diagnostics_count=lambda: len(self.model.diagnostics)
        )
        self._pop_scope()
        return self.model

    def _predeclare_globals(self, items: list[Statement]) -> None:
        for item in items:
            if isinstance(item, FunctionDeclaration):
                return_shape = self._body_return_shape(item.body) or "function"
                if (
                    self._define(item.name, SymbolKind.FUNCTION, item.span, return_shape, None)
                    is not None
                ):
                    self._predeclared_nodes.add(id(item))
                    self._function_params[item.name] = item.parameters
            elif isinstance(item, MethodDeclaration):
                return_shape = self._body_return_shape(item.body) or "method"
                if (
                    self._define(item.name, SymbolKind.METHOD, item.span, return_shape, None)
                    is not None
                ):
                    self._predeclared_nodes.add(id(item))
                    self._function_params[item.name] = item.parameters
                    if item.receiver_type is not None:
                        self._method_receivers[item.name] = item.receiver_type.name
            elif isinstance(item, TypeDeclaration):
                if self._define(item.name, SymbolKind.TYPE, item.span, "type", None) is not None:
                    self._predeclared_nodes.add(id(item))
            elif isinstance(item, EnumDeclaration):
                if self._define(item.name, SymbolKind.ENUM, item.span, "enum", None) is not None:
                    self._predeclared_nodes.add(id(item))
                members: set[str] = set()
                for m in item.members:
                    if m.name in members:
                        continue
                    members.add(m.name)
                    self._define(
                        f"{item.name}.{m.name}",
                        SymbolKind.ENUM_MEMBER,
                        m.span,
                        item.name,
                        "const",
                        allow_existing=True,
                    )
                self._enum_members[item.name] = members
            elif isinstance(item, ImportDeclaration):
                alias = item.alias or item.library or item.owner or item.path
                if (
                    self._define(alias, SymbolKind.IMPORT_ALIAS, item.span, "external", None)
                    is not None
                ):
                    self._external_aliases.add(alias)
                    self._predeclared_nodes.add(id(item))

    def _register_builtins(self) -> None:
        zero = SourceSpan.zero()
        for ns in self.registry.get("namespaces", {}):
            self._define(ns, SymbolKind.BUILTIN, zero, None, None, allow_existing=True)
        for name in self.registry.get("types", {}):
            self._define(name, SymbolKind.TYPE, zero, "type", None, allow_existing=True)
        for name, meta in self.registry.get("variables", {}).items():
            self._define(
                name,
                SymbolKind.BUILTIN,
                zero,
                meta.get("type"),
                meta.get("qualifier"),
                allow_existing=True,
            )
        for name in self.registry.get("functions", {}):
            root = name.split(".", 1)[0]
            self._define(root, SymbolKind.BUILTIN, zero, None, None, allow_existing=True)

    def _analyze_declaration_statement(self, node: DeclarationStatement) -> None:
        self._script_type = node.script_type
        self._visit_expr(node.call)
        for arg in node.call.arguments:
            if infer_qualifier(arg.value, self.model.symbols) not in {
                "const",
                "input",
            } and arg.name in {"title", "overlay", None}:
                self._diag(
                    Severity.ERROR,
                    codes.DECLARATION_ARGS_NOT_CONST,
                    "Declaration statement arguments must be const-compatible in Pine.",
                    arg.span,
                )

    def _visit_statement(self, node: Statement | ASTNode) -> None:
        if isinstance(node, DeclarationStatement):
            if self.local_depth > 0 or self.function_depth > 0:
                self._diag(
                    Severity.ERROR,
                    codes.DECLARATION_NOT_GLOBAL,
                    "indicator/strategy/library declaration must be in global scope.",
                    node.span,
                )
            self._analyze_declaration_statement(node)
            return
        if isinstance(node, VarDeclaration):
            self._validate_export_policy(node)
            init_type = infer_type(node.initializer, self.model.symbols)
            explicit_type = self._type_ref_name(node.type_ref) if node.type_ref else init_type
            if node.type_ref is not None:
                self._validate_type_ref(node.type_ref)
            if (
                explicit_type == "bool"
                and isinstance(node.initializer, Literal)
                and node.initializer.literal_type == "na"
            ):
                self._diag(
                    Severity.ERROR,
                    codes.BOOL_CANNOT_BE_NA,
                    "Pine v6 bool cannot be na.",
                    node.initializer.span,
                )
            self._visit_expr(node.initializer)
            if node.type_ref is not None and not self._is_assignable_type(explicit_type, init_type):
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Initializer for {node.name} expects {explicit_type}, got {init_type}.",
                    node.initializer.span,
                )
            init_qualifier = infer_qualifier(node.initializer, self.model.symbols)
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
                inferred_q = init_qualifier
                # A variable initialized from a literal is not an immutable const declaration in Pine.
                # Keep const only when the source explicitly declared `const`; otherwise default to
                # input for input.*() and series for normal mutable variables.
                qualifier = "input" if inferred_q == "input" else "series"
            self._define(node.name, SymbolKind.VARIABLE, node.span, explicit_type, qualifier)
            return
        if isinstance(node, TupleDeclaration):
            self._visit_expr(node.initializer)
            init_type = infer_type(node.initializer, self.model.symbols)
            element_types = self._tuple_element_types(init_type)
            init_qualifier = infer_qualifier(node.initializer, self.model.symbols)
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
            return
        if isinstance(node, Reassignment):
            self._visit_expr(node.value)
            value_type = infer_type(node.value, self.model.symbols)
            if isinstance(node.target, MemberAccessExpr):
                root_sym = self._resolve_assignable(node.target)
                field_type = self._member_field_type(node.target)
                owner_type = self._member_owner_type(node.target)
                if root_sym is None:
                    target_name = self._assignable_name(node.target) or "<expr>"
                    code = (
                        codes.REASSIGN_UNDECLARED if node.op == ":=" else codes.COMPOUND_UNDECLARED
                    )
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
            return
        if isinstance(
            node, (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure)
        ):
            self._visit_structure(node)
            return
        if isinstance(node, BreakStatement):
            if self.loop_depth == 0:
                self._diag(
                    Severity.ERROR,
                    codes.BREAK_CONTINUE_OUTSIDE_LOOP,
                    "break is allowed only inside loops.",
                    node.span,
                )
            return
        if isinstance(node, ContinueStatement):
            if self.loop_depth == 0:
                self._diag(
                    Severity.ERROR,
                    codes.BREAK_CONTINUE_OUTSIDE_LOOP,
                    "continue is allowed only inside loops.",
                    node.span,
                )
            return
        if isinstance(node, FunctionDeclaration):
            self._validate_export_policy(node)
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
                if p.type_ref is not None:
                    self._validate_type_ref(p.type_ref)
                if p.default_value is not None:
                    self._visit_expr(p.default_value)
                    expected = self._type_ref_name(p.type_ref) if p.type_ref else None
                    actual = infer_type(p.default_value, self.model.symbols)
                    if not self._is_assignable_type(expected, actual):
                        self._diag(
                            Severity.ERROR,
                            codes.TYPE_MISMATCH,
                            f"Default value for parameter {p.name} expects {expected}, got {actual}.",
                            p.default_value.span,
                        )
                    if p.explicit_qualifier is not None:
                        self._validate_qualifier_assignment(
                            p.explicit_qualifier,
                            infer_qualifier(p.default_value, self.model.symbols),
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
            sym = self._resolve(node.name)
            if sym is not None:
                sym.type = self._body_return_type(node.body)
            self._pop_scope()
            self.function_depth -= 1
            return
        if isinstance(node, MethodDeclaration):
            self._validate_export_policy(node)
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
                self._define(node.name, SymbolKind.METHOD, node.span, "method", None)
                self._function_params[node.name] = node.parameters
                if node.receiver_type is not None:
                    self._method_receivers[node.name] = node.receiver_type.name
            self._push_scope(ScopeKind.METHOD)
            if node.receiver_name:
                self._define(
                    node.receiver_name,
                    SymbolKind.VARIABLE,
                    node.span,
                    self._type_ref_name(node.receiver_type) if node.receiver_type else "unknown",
                    "series",
                )
            for p in node.parameters:
                if p.type_ref is not None:
                    self._validate_type_ref(p.type_ref)
                if p.default_value is not None:
                    self._visit_expr(p.default_value)
                    expected = self._type_ref_name(p.type_ref) if p.type_ref else None
                    actual = infer_type(p.default_value, self.model.symbols)
                    if not self._is_assignable_type(expected, actual):
                        self._diag(
                            Severity.ERROR,
                            codes.TYPE_MISMATCH,
                            f"Default value for parameter {p.name} expects {expected}, got {actual}.",
                            p.default_value.span,
                        )
                    if p.explicit_qualifier is not None:
                        self._validate_qualifier_assignment(
                            p.explicit_qualifier,
                            infer_qualifier(p.default_value, self.model.symbols),
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
            sym = self._resolve(node.name)
            if sym is not None:
                sym.type = self._body_return_type(node.body)
            self._pop_scope()
            return
        if isinstance(node, TypeDeclaration):
            self._validate_export_policy(node)
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
                    default_type = infer_type(field.default_value, self.model.symbols)
                    if not self._is_assignable_type(field_type, default_type):
                        self._diag(
                            Severity.ERROR,
                            codes.TYPE_MISMATCH,
                            f"Default value for field {field.name} expects {field_type}, got {default_type}.",
                            field.default_value.span,
                        )
            self._pop_scope()
            return
        if isinstance(node, EnumDeclaration):
            self._validate_export_policy(node)
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
            return
        if isinstance(node, ImportDeclaration):
            alias = node.alias or node.library or node.owner or node.path
            if id(node) not in self._predeclared_nodes:
                self._define(alias, SymbolKind.IMPORT_ALIAS, node.span, "external", None)
                self._external_aliases.add(alias)
            return
        if hasattr(node, "expression"):
            self._visit_expr(node.expression)  # type: ignore[attr-defined]

    def _body_return_type(self, body) -> str:
        if isinstance(body, Block):
            if not body.statements:
                return "void"
            last = body.statements[-1]
            if hasattr(last, "expression"):
                return infer_type(last.expression, self.model.symbols)
            if hasattr(last, "initializer"):
                return infer_type(last.initializer, self.model.symbols)
            if hasattr(last, "value"):
                return infer_type(last.value, self.model.symbols)
            return "void"
        return infer_type(body, self.model.symbols)

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
        if isinstance(expr, IfStructure):
            shapes: list[str | None] = []
            target = self._body_return_expr(expr.then_block)
            if target is not None:
                shapes.append(self._static_return_shape(target))
            for br in expr.else_if_branches:
                target = self._body_return_expr(br.block)
                if target is not None:
                    shapes.append(self._static_return_shape(target))
            if expr.else_block is not None:
                target = self._body_return_expr(expr.else_block)
                if target is not None:
                    shapes.append(self._static_return_shape(target))
            return self._merge_return_shapes(shapes)
        if isinstance(expr, SwitchStructure):
            switch_shapes: list[str | None] = []
            for case in expr.cases:
                target = (
                    self._body_return_expr(case.body) if isinstance(case.body, Block) else case.body
                )
                if target is not None:
                    switch_shapes.append(self._static_return_shape(target))
            return self._merge_return_shapes(switch_shapes)
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

    def _expr_path(self, expr: Expression) -> str | None:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            root = self._expr_path(expr.object)
            return f"{root}.{expr.member}" if root else None
        return None

    def _na_call_path(self, expr: Expression) -> str | None:
        if (
            isinstance(expr, CallExpr)
            and callee_name(expr.callee) == "na"
            and len(expr.arguments) == 1
        ):
            return self._expr_path(expr.arguments[0].value)
        return None

    def _non_na_paths_from_condition(self, expr: Expression, *, truthy: bool = True) -> set[str]:
        """Return source paths known to be non-na in the requested branch.

        v2.11 extends the v2.10 `if not na(x)` metadata with:
        - conjunction guards: `if not na(x) and x > 0`;
        - member paths: `if not na(obj.field)`;
        - else-branch narrowing: `if na(x) ... else ...`.

        These facts remain scope-local and report-only. They do not rewrite AST or
        leak into sibling/global scopes.
        """
        if isinstance(expr, UnaryExpr) and expr.op == "not":
            return self._non_na_paths_from_condition(expr.operand, truthy=not truthy)
        na_path = self._na_call_path(expr)
        if na_path:
            return set() if truthy else {na_path}
        if isinstance(expr, BinaryExpr) and expr.op == "and" and truthy:
            return self._non_na_paths_from_condition(
                expr.left, truthy=True
            ) | self._non_na_paths_from_condition(expr.right, truthy=True)
        return set()

    def _non_na_narrowing_from_condition(
        self, expr: Expression, *, truthy: bool = True
    ) -> set[str]:
        # Backward-compatible symbol-only view for existing callers/tests.
        return {
            path
            for path in self._non_na_paths_from_condition(expr, truthy=truthy)
            if "." not in path
        }

    def _validate_narrowing_condition(self, expr: Expression) -> None:
        """Report `na()` guards that cannot produce a stable flow fact.

        Flow-sensitive narrowing is intentionally path-based. `na(x)` and
        `na(obj.field)` are stable, but `na(1)`, `na(close + open)`, or other
        computed expressions cannot be represented as scope-local facts. Keeping
        this as INFO makes it visible to hardening reports without breaking real
        scripts that use `na()` as a pure boolean predicate.
        """
        if isinstance(expr, UnaryExpr) and expr.op == "not":
            self._validate_narrowing_condition(expr.operand)
            return
        if isinstance(expr, BinaryExpr) and expr.op in {"and", "or"}:
            self._validate_narrowing_condition(expr.left)
            self._validate_narrowing_condition(expr.right)
            return
        if (
            isinstance(expr, CallExpr)
            and callee_name(expr.callee) == "na"
            and len(expr.arguments) == 1
        ):
            if self._expr_path(expr.arguments[0].value) is None:
                self._diag(
                    Severity.INFO,
                    codes.UNSTABLE_NA_NARROWING,
                    "na() guard does not reference a stable symbol/member path, so no non-na narrowing fact is recorded.",
                    expr.arguments[0].span,
                )

    def _visit_structure(self, node: Statement) -> None:
        if isinstance(node, IfStructure):
            self._check_bool(node.condition)
            self._validate_narrowing_condition(node.condition)
            then_paths = self._non_na_paths_from_condition(node.condition, truthy=True)
            self._visit_block(
                node.then_block,
                non_na_symbols={path for path in then_paths if "." not in path},
                non_na_paths=then_paths,
            )
            for br in node.else_if_branches:
                self._check_bool(br.condition)
                self._validate_narrowing_condition(br.condition)
                branch_paths = self._non_na_paths_from_condition(br.condition, truthy=True)
                self._visit_block(
                    br.block,
                    non_na_symbols={path for path in branch_paths if "." not in path},
                    non_na_paths=branch_paths,
                )
            if node.else_block:
                else_paths = self._non_na_paths_from_condition(node.condition, truthy=False)
                self._visit_block(
                    node.else_block,
                    non_na_symbols={path for path in else_paths if "." not in path},
                    non_na_paths=else_paths,
                )
        elif isinstance(node, WhileStructure):
            self._check_bool(node.condition)
            self._validate_narrowing_condition(node.condition)
            self.loop_depth += 1
            self._visit_block(node.body, kind=ScopeKind.LOOP)
            self.loop_depth -= 1
        elif isinstance(node, ForRangeStructure):
            self._visit_expr(node.start)
            self._visit_expr(node.end)
            if node.step:
                self._visit_expr(node.step)
            for label, expr in (("start", node.start), ("end", node.end), ("step", node.step)):
                if expr is not None:
                    typ = infer_type(expr, self.model.symbols)
                    if typ not in {"int", "unknown"}:
                        self._diag(
                            Severity.ERROR,
                            codes.LOOP_RANGE_TYPE,
                            f"for range {label} expression must be int-like, got {typ}.",
                            expr.span,
                        )
            self.loop_depth += 1
            self.local_depth += 1
            self._push_scope(ScopeKind.LOOP)
            self._define(node.variable, SymbolKind.VARIABLE, node.span, "int", "series")
            for st in node.body.statements:
                self._visit_statement(st)
            self._pop_scope()
            self.local_depth -= 1
            self.loop_depth -= 1
        elif isinstance(node, ForInStructure):
            self._validate_for_in_target(node)
            self._visit_expr(node.iterable)
            iterable_type = infer_type(node.iterable, self.model.symbols)
            target_types = self._for_in_target_types(iterable_type, len(node.target.names))
            self.loop_depth += 1
            self.local_depth += 1
            self._push_scope(ScopeKind.LOOP)
            for index, name in enumerate(node.target.names):
                if name == "_":
                    continue
                typ = target_types[index] if index < len(target_types) else "unknown"
                self._define(name, SymbolKind.VARIABLE, node.target.span, typ, "series")
            for st in node.body.statements:
                self._visit_statement(st)
            self._pop_scope()
            self.local_depth -= 1
            self.loop_depth -= 1
        elif isinstance(node, SwitchStructure):
            switch_type = None
            if node.expression:
                self._visit_expr(node.expression)
                switch_type = infer_type(node.expression, self.model.symbols)
            for case in node.cases:
                if case.condition:
                    if node.expression is None:
                        self._check_bool(case.condition)
                    else:
                        self._visit_expr(case.condition)
                        case_type = infer_type(case.condition, self.model.symbols)
                        if not (
                            self._is_assignable_type(switch_type, case_type)
                            or self._is_assignable_type(case_type, switch_type)
                        ):
                            self._diag(
                                Severity.ERROR,
                                codes.SWITCH_CASE_TYPE,
                                f"switch case type {case_type} is not comparable with switch expression type {switch_type}.",
                                case.condition.span,
                            )
                self._visit_body(case.body)

    def _visit_expr(self, expr: Expression) -> None:
        self.model.node_types[id(expr)] = infer_type(expr, self.model.symbols)
        self.model.node_qualifiers[id(expr)] = infer_qualifier(expr, self.model.symbols)
        if isinstance(expr, Identifier):
            if self._resolve(expr.name) is None and not expr.name.startswith("<"):
                # Imported aliases are allowed to resolve member calls later; unknown identifiers remain errors.
                self._diag(
                    Severity.ERROR,
                    codes.UNDECLARED_VARIABLE,
                    f"Use of undeclared variable {expr.name}.",
                    expr.span,
                )
        elif isinstance(expr, Literal):
            return
        elif isinstance(expr, TupleExpr):
            for item in expr.elements:
                self._visit_expr(item)
        elif isinstance(expr, UnaryExpr):
            self._visit_expr(expr.operand)
            if expr.op == "not":
                operand_type = infer_type(expr.operand, self.model.symbols)
                if operand_type not in {"bool", "unknown"}:
                    self._diag(
                        Severity.ERROR,
                        codes.TYPE_MISMATCH,
                        f"Unary not requires bool operand, got {operand_type}.",
                        expr.span,
                    )
        elif isinstance(expr, BinaryExpr):
            self._visit_expr(expr.left)
            self._visit_expr(expr.right)
            self._validate_binary_expr(expr)
        elif isinstance(expr, ConditionalExpr):
            self._check_bool(expr.condition)
            self._validate_narrowing_condition(expr.condition)
            self._visit_expr(expr.if_true)
            self._visit_expr(expr.if_false)
            true_type = infer_type(expr.if_true, self.model.symbols)
            false_type = infer_type(expr.if_false, self.model.symbols)
            if not self._branch_types_compatible(true_type, false_type):
                self._diag(
                    Severity.ERROR,
                    codes.BRANCH_TYPE_MISMATCH,
                    f"Ternary branches must have compatible types, got {true_type} and {false_type}.",
                    expr.span,
                )
        elif isinstance(expr, MemberAccessExpr):
            # Only require root object if it is not a known namespace/import/builtin. Imported aliases are intentionally external/unresolved in v1.
            if isinstance(expr.object, Identifier):
                root = expr.object.name
                if self._resolve(root) is None and root not in self._external_aliases:
                    self._diag(
                        Severity.ERROR,
                        codes.UNDECLARED_VARIABLE,
                        f"Use of undeclared namespace/object {root}.",
                        expr.object.span,
                    )
            else:
                self._visit_expr(expr.object)
            self._validate_strategy_namespace_usage(callee_name(expr), expr.span, is_call=False)
            self._validate_member_access(expr)
        elif isinstance(expr, GenericInstantiationExpr):
            self._visit_expr(expr.base)
        elif isinstance(expr, CallExpr):
            name = callee_name(expr.callee)
            self._visit_callee(expr.callee)
            entry = self.registry.get("functions", {}).get(name)
            if entry and entry.get("forbidden_in_local_blocks") and self.local_depth > 0:
                self._diag(
                    Severity.ERROR,
                    codes.BUILTIN_FORBIDDEN_LOCAL,
                    f"{name}() is forbidden in local blocks in Pine.",
                    expr.span,
                )
            self._validate_strategy_call_script_type(name, expr)
            self._validate_strategy_namespace_usage(name, expr.span, is_call=True)
            self._validate_known_deferred_or_unsupported_builtin(name, entry, expr)
            self._validate_unknown_builtin_namespace_member(name, entry, expr)
            if (
                name.startswith("request.")
                and entry is None
                and not self._is_known_deferred_or_unsupported_builtin(name)
            ):
                self._diag(
                    Severity.ERROR,
                    codes.REQUEST_SIGNATURE,
                    f"Unknown request.* builtin {name}.",
                    expr.span,
                )
            self._validate_builtin_call(name, entry, expr)
            self._validate_collection_mutation_call(name, expr)
            self._validate_generic_constructor_call(name, expr)
            if entry is None:
                self._validate_udt_constructor_call(expr)
                self._validate_method_call(expr)
                self._validate_user_function_call(name, expr)
                self._validate_member_call_target(name, expr)
            seen_named: set[str] = set()
            named_seen = False
            for arg in expr.arguments:
                if arg.name:
                    named_seen = True
                    if arg.name in seen_named:
                        self._diag(
                            Severity.ERROR,
                            codes.DUPLICATE_NAMED_ARGUMENT,
                            f"Duplicate named argument {arg.name}.",
                            arg.span,
                        )
                    seen_named.add(arg.name)
                    if name.startswith("strategy.") and arg.name == "when":
                        self._diag(
                            Severity.ERROR,
                            codes.STRATEGY_WHEN_REMOVED,
                            "strategy.*(..., when=...) is not valid in Pine v6.",
                            arg.span,
                        )
                elif named_seen:
                    self._diag(
                        Severity.ERROR,
                        codes.POSITIONAL_AFTER_NAMED,
                        "Positional argument after named argument.",
                        arg.span,
                    )
                self._visit_expr(arg.value)
        elif isinstance(expr, HistoryRefExpr):
            if isinstance(expr.base, Literal):
                self._diag(
                    Severity.ERROR,
                    codes.HISTORY_ON_LITERAL,
                    "History reference cannot be applied to a literal.",
                    expr.span,
                )
            if isinstance(expr.base, HistoryRefExpr):
                self._diag(
                    Severity.ERROR,
                    codes.REPEATED_HISTORY,
                    "Repeated history reference x[1][2] is not allowed.",
                    expr.span,
                )
            if isinstance(expr.base, Identifier):
                sym = self._resolve(expr.base.name)
                if sym is not None and self._scope_kind(sym.scope_id) not in {
                    ScopeKind.GLOBAL,
                    None,
                }:
                    self._diag(
                        Severity.WARNING,
                        codes.HISTORY_LOCAL_SCOPE,
                        "History reference to a value declared in a local scope can be unsafe in Pine.",
                        expr.span,
                    )
            offset_type = infer_type(expr.offset, self.model.symbols)
            if offset_type not in {"int", "unknown"}:
                self._diag(
                    Severity.ERROR,
                    codes.HISTORY_OFFSET_NOT_INTEGER,
                    "History reference offset must be integer-like.",
                    expr.offset.span,
                )
            if self._is_static_negative_history_offset(expr.offset):
                self._diag(
                    Severity.ERROR,
                    codes.HISTORY_NEGATIVE_OFFSET,
                    "History reference offset cannot be negative in Pine.",
                    expr.offset.span,
                )
            self._visit_expr(expr.base)
            self._visit_expr(expr.offset)
        elif isinstance(
            expr, (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure)
        ):
            self._visit_structure(expr)

    def _check_bool(self, expr: Expression) -> None:
        self._visit_expr(expr)
        typ = infer_type(expr, self.model.symbols)
        if isinstance(expr, Literal) and expr.literal_type == "na":
            self._diag(
                Severity.ERROR,
                codes.NA_IN_BOOL_CONTEXT,
                "na is not allowed in bool context in Pine v6.",
                expr.span,
            )
        elif typ != "bool" and typ != "unknown":
            self._diag(
                Severity.ERROR,
                codes.NON_BOOL_CONDITION,
                "Non-bool expression used as condition in Pine v6.",
                expr.span,
            )

    def _validate_export_policy(self, node: ASTNode) -> None:
        if getattr(node, "is_exported", False) and self._script_type != "library":
            self._diag(
                Severity.ERROR,
                codes.EXPORT_NOT_LIBRARY,
                "export declarations are allowed only in library() scripts.",
                node.span,
            )

    def _validate_for_in_target(self, node: ForInStructure) -> None:
        non_blank = [name for name in node.target.names if name != "_"]
        seen: set[str] = set()
        for name in non_blank:
            if name in seen:
                self._diag(
                    Severity.ERROR,
                    codes.REDECLARATION,
                    f"Duplicate for-in target {name}.",
                    node.target.span,
                )
                break
            seen.add(name)
        if len(node.target.names) not in {1, 2}:
            self._diag(
                Severity.ERROR,
                codes.FOR_IN_TARGET_ARITY,
                "for-in destructuring supports one value target or [index, value].",
                node.target.span,
            )

    def _is_static_negative_history_offset(self, expr: Expression) -> bool:
        return (
            isinstance(expr, UnaryExpr)
            and expr.op == "-"
            and isinstance(expr.operand, Literal)
            and expr.operand.literal_type == "int"
        )

    def _strategy_constant_members(self) -> set[str]:
        return {
            "strategy.long",
            "strategy.short",
            "strategy.cash",
            "strategy.percent_of_equity",
        }

    def _strategy_state_members(self) -> set[str]:
        return {
            "strategy.closedtrades",
            "strategy.equity",
            "strategy.losstrades",
            "strategy.netprofit",
            "strategy.openprofit",
            "strategy.opentrades",
            "strategy.position_avg_price",
            "strategy.position_size",
            "strategy.wintrades",
        }

    def _validate_strategy_namespace_usage(
        self, name: str, span: SourceSpan, *, is_call: bool
    ) -> None:
        if not name.startswith("strategy."):
            return
        if name in self._strategy_constant_members():
            return
        is_state_member = name in self._strategy_state_members()
        is_readonly_trade_member = name.startswith("strategy.closedtrades.") or name.startswith(
            "strategy.opentrades."
        )
        if (is_state_member or is_readonly_trade_member) and self._script_type not in {
            None,
            "strategy",
        }:
            self._diag(
                Severity.ERROR,
                codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE,
                f"{name} is available only in strategy() scripts; strategy constants remain allowed in libraries.",
                span,
            )

    def _builtin_namespace_root(self, name: str) -> str | None:
        if "." not in name:
            return None
        root = name.split(".", 1)[0]
        sym = self._resolve(root)
        if sym is not None and sym.kind is SymbolKind.BUILTIN:
            return root
        return None

    def _is_known_deferred_or_unsupported_builtin(self, name: str) -> bool:
        if "." not in name:
            return False
        namespace, member = name.split(".", 1)
        return member in KNOWN_DEFERRED_NAMESPACE_MEMBERS.get(
            namespace, set()
        ) or member in KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS.get(namespace, set())

    def _validate_known_deferred_or_unsupported_builtin(
        self, name: str, entry: dict | None, expr: CallExpr
    ) -> None:
        if entry is not None or "." not in name:
            return
        namespace, member = name.split(".", 1)
        if member in KNOWN_DEFERRED_NAMESPACE_MEMBERS.get(namespace, set()):
            self._diag(
                Severity.INFO,
                codes.UNSUPPORTED_FEATURE,
                f"Builtin {name} is deliberately deferred in the v3.1 registry snapshot.",
                expr.span,
            )
        if member in KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS.get(namespace, set()):
            self._diag(
                Severity.ERROR,
                codes.UNSUPPORTED_FEATURE,
                f"Builtin {name} is intentionally unsupported by this parser/semantic layer.",
                expr.span,
            )

    def _validate_unknown_builtin_namespace_member(
        self, name: str, entry: dict | None, expr: CallExpr
    ) -> None:
        if entry is not None or name.startswith("<"):
            return
        root = self._builtin_namespace_root(name)
        if (
            root is None
            or root in self._external_aliases
            or self._is_known_deferred_or_unsupported_builtin(name)
        ):
            return
        # Registry coverage is intentionally incomplete, so unknown members from known namespaces
        # are surfaced as INFO instead of ERROR. `request.*` remains an ERROR in the dedicated
        # request validator below because that namespace affects data access semantics.
        if root == "request":
            return
        severity = Severity.ERROR if self.strict_builtin_namespaces else Severity.INFO
        self._diag(
            severity,
            codes.UNKNOWN_BUILTIN_MEMBER,
            f"Builtin namespace member {name} is not present in the current registry snapshot.",
            expr.span,
        )

    def _validate_strategy_call_script_type(self, name: str, expr: CallExpr) -> None:
        strategy_order_calls = {
            "strategy.entry",
            "strategy.exit",
            "strategy.close",
            "strategy.close_all",
            "strategy.order",
            "strategy.cancel",
            "strategy.cancel_all",
            "strategy.risk.allow_entry_in",
            "strategy.risk.max_drawdown",
            "strategy.risk.max_intraday_loss",
            "strategy.risk.max_cons_loss_days",
            "strategy.risk.max_intraday_filled_orders",
        }
        if name in strategy_order_calls and self._script_type not in {None, "strategy"}:
            self._diag(
                Severity.ERROR,
                codes.STRATEGY_CALL_WRONG_SCRIPT_TYPE,
                f"{name}() is allowed only in strategy() scripts.",
                expr.span,
            )

    def _qualifier_rank(self, qualifier: str | None) -> int:
        order = {"const": 0, "input": 1, "simple": 2, "series": 3, None: 3}
        return order.get(qualifier, 3)

    def _validate_qualifier_assignment(
        self, expected_max: str | None, actual: str | None, span: SourceSpan, context: str
    ) -> None:
        if expected_max is None:
            return
        if self._qualifier_rank(actual) > self._qualifier_rank(expected_max):
            self._diag(
                Severity.ERROR,
                codes.QUALIFIER_MISMATCH,
                f"{context} requires {expected_max} or weaker qualifier, got {actual or 'unknown'}.",
                span,
            )

    def _branch_types_compatible(self, left: str | None, right: str | None) -> bool:
        if left in {None, "unknown", "na"} or right in {None, "unknown", "na"}:
            return True
        return self._is_assignable_type(left, right) or self._is_assignable_type(right, left)

    def _validate_binary_expr(self, expr: BinaryExpr) -> None:
        left_type = infer_type(expr.left, self.model.symbols)
        right_type = infer_type(expr.right, self.model.symbols)
        numeric = {"int", "float", "unknown", "na"}
        if expr.op in {"-", "*", "/", "%"}:
            if left_type not in numeric or right_type not in numeric:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires numeric operands, got {left_type} and {right_type}.",
                    expr.span,
                )
        elif expr.op == "+":
            string_concat = left_type == right_type == "string"
            numeric_add = left_type in numeric and right_type in numeric
            if not (string_concat or numeric_add):
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator + requires numeric operands or string concatenation, got {left_type} and {right_type}.",
                    expr.span,
                )
        elif expr.op in {"and", "or"}:
            if left_type not in {"bool", "unknown"} or right_type not in {"bool", "unknown"}:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires bool operands, got {left_type} and {right_type}.",
                    expr.span,
                )
        elif expr.op in {"<", "<=", ">", ">="}:
            comparable = (left_type in numeric and right_type in numeric) or (
                left_type == right_type == "string"
            )
            if not comparable:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires comparable operands, got {left_type} and {right_type}.",
                    expr.span,
                )

    def _type_ref_name(self, type_ref) -> str:
        if type_ref is None:
            return "unknown"
        args = getattr(type_ref, "template_args", None) or []
        if not args:
            return type_ref.name
        return type_ref.name + "<" + ",".join(self._type_ref_name(arg) for arg in args) + ">"

    def _for_in_target_types(self, iterable_type: str, target_count: int) -> list[str]:
        # Infer target types for Pine `for ... in ...` over common collections.
        if iterable_type.startswith("array<") and iterable_type.endswith(">"):
            element = iterable_type[len("array<") : -1].strip() or "unknown"
            return ["int", element] if target_count == 2 else [element]
        if iterable_type.startswith("matrix<") and iterable_type.endswith(">"):
            element = iterable_type[len("matrix<") : -1].strip() or "unknown"
            return ["int", element] if target_count == 2 else [element]
        if iterable_type.startswith("map<") and iterable_type.endswith(">"):
            parts = self._split_type_args(iterable_type[len("map<") : -1])
            if target_count == 2 and len(parts) >= 2:
                return [parts[0], parts[1]]
            return ["tuple<" + ",".join(parts[:2]) + ">" if parts else "unknown"]
        if iterable_type.startswith("tuple<") and iterable_type.endswith(">"):
            return self._split_type_args(iterable_type[len("tuple<") : -1])
        return ["unknown"] * target_count

    def _split_type_args(self, inner: str) -> list[str]:
        result: list[str] = []
        depth = 0
        start = 0
        for idx, ch in enumerate(inner):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            elif ch == "," and depth == 0:
                result.append(inner[start:idx].strip() or "unknown")
                start = idx + 1
        tail = inner[start:].strip()
        if tail:
            result.append(tail)
        return result

    def _validate_type_ref(self, type_ref) -> None:
        base = type_ref.name
        # Builtin templates such as array<float> are declared by their base name. Dotted builtins
        # such as chart.point are also registered as types in builtins_v6.json.
        if self._resolve(base) is None and base not in {"int", "float", "bool", "string", "color"}:
            self._diag(
                Severity.ERROR,
                getattr(codes, "UNKNOWN_TYPE", codes.METHOD_RECEIVER_TYPE_NOT_FOUND),
                f"Unknown type {base}.",
                type_ref.span,
            )
        for arg in getattr(type_ref, "template_args", []) or []:
            self._validate_type_ref(arg)

    def _tuple_element_types(self, typ: str) -> list[str]:
        if not typ.startswith("tuple<") or not typ.endswith(">"):
            return []
        inner = typ[len("tuple<") : -1]
        result: list[str] = []
        depth = 0
        start = 0
        for idx, ch in enumerate(inner):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            elif ch == "," and depth == 0:
                result.append(inner[start:idx].strip() or "unknown")
                start = idx + 1
        tail = inner[start:].strip()
        if tail:
            result.append(tail)
        return result

    def _generic_type_parts(self, typ: str | None) -> tuple[str | None, list[str]]:
        if not typ:
            return None, []
        if "<" not in typ or not typ.endswith(">"):
            return typ, []
        base, inner = typ.split("<", 1)
        return base.strip(), self._split_type_args(inner[:-1])

    def _is_assignable_type(self, expected: str | None, actual: str | None) -> bool:
        if not expected or expected in {"any", "unknown"}:
            return True
        if not actual or actual in {"unknown", "na"}:
            return True
        if actual == "any":
            return True
        if expected == actual:
            return True
        enum_like_types = {
            "display",
            "line.style",
            "label.style",
            "box.style",
            "table.position",
            "barmerge.gaps",
            "barmerge.lookahead",
            "dividends.field",
            "earnings.field",
            "splits.field",
            "strategy.risk.type",
            "strategy.direction",
            "strategy.order_type",
            "extend",
        }
        if expected in enum_like_types and actual == expected:
            return True
        # Enum display values (display.data_window, etc.) are stored as integers internally.
        # Allow int parameters to accept enum-like display values.
        if expected == "int" and actual in enum_like_types:
            return True
        if expected == "float" and actual == "int":
            return True
        if expected.startswith("series<") and expected.endswith(">"):
            # Allow series<any> to be assigned where series<T> is expected
            if actual.startswith("series<") and actual.endswith(">"):
                inner_actual = actual[len("series<") : -1]
                if inner_actual == "any":
                    return True
            return self._is_assignable_type(expected[len("series<") : -1], actual)
        exp_base, exp_args = self._generic_type_parts(expected)
        act_base, act_args = self._generic_type_parts(actual)
        if exp_base in {"array", "map", "matrix"}:
            if exp_base == "array" and act_base == "tuple":
                # Pine input options are often written as inline tuple/list syntax. Treat a
                # tuple<T...> as array<T> compatible when all elements match the array element type.
                if not exp_args or exp_args[0] in {"any", "unknown"}:
                    return True
                return all(self._is_assignable_type(exp_args[0], a) for a in act_args)
            if act_base != exp_base:
                return False
            if not exp_args:
                return True
            if not act_args:
                return True
            if len(exp_args) != len(act_args):
                return False
            return all(self._is_assignable_type(e, a) for e, a in zip(exp_args, act_args))
        if expected.endswith("_direction") and actual.startswith("strategy."):
            return True
        return False

    def _validate_argument_type(self, callee: str, arg, param: dict | None) -> None:
        if not param:
            return
        expected = param.get("type")
        if not expected or expected in {"any", "array"}:
            return
        actual = infer_type(arg.value, self.model.symbols)
        if callee == "line.new" and (param.get("name") in {"x1", "y1"}) and actual == "chart.point":
            # Pine v6 has an overload line.new(first_point, second_point, ...). The registry
            # remains a single signature snapshot, so accept chart.point for the first two
            # positional slots without weakening x/y validation for numeric overloads.
            return
        # Allow plain "any" from user functions/input/source in oracle probes; downstream
        # lowerers/runtime preserve Pine's na/value behavior for the actual operation.
        if actual == "any":
            return
        # Allow series<any> arguments where series<T> is expected (e.g. input.source -> ta.sma)
        if actual.startswith("series<") and actual.endswith(">"):
            inner = actual[len("series<"):-1]
            if inner == "any":
                return
        if not self._is_assignable_type(expected, actual):
            pname = param.get("name") or "<positional>"
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_TYPE,
                f"Argument {pname} for {callee} expects {expected}, got {actual}.",
                arg.span,
            )

    def _collection_value_type(
        self, collection_type: str | None, *, key: bool = False
    ) -> str | None:
        if not collection_type:
            return None
        base, args = self._generic_type_parts(collection_type)
        if base in {"array", "matrix"} and args:
            return args[0]
        if base == "map" and len(args) >= 2:
            return args[0] if key else args[1]
        return None

    def _diag_collection_value(
        self, name: str, expected: str | None, actual: str, span: SourceSpan
    ) -> None:
        if expected and not self._is_assignable_type(expected, actual):
            self._diag(
                Severity.ERROR,
                codes.COLLECTION_ELEMENT_TYPE,
                f"Collection mutation {name} expects element/value type {expected}, got {actual}.",
                span,
            )

    def _validate_collection_mutation_call(self, name: str, expr: CallExpr) -> None:
        # Validate common collection mutators beyond the incomplete builtin registry. Pine collections
        # are often the bridge from AST to optimizer state, so catching wrong element types early is useful.
        args = expr.arguments
        if name in {"array.push", "array.unshift"} and len(args) >= 2:
            expected = self._collection_value_type(infer_type(args[0].value, self.model.symbols))
            actual = infer_type(args[1].value, self.model.symbols)
            self._diag_collection_value(name, expected, actual, args[1].span)
            return
        if name == "array.set" and len(args) >= 3:
            expected = self._collection_value_type(infer_type(args[0].value, self.model.symbols))
            actual = infer_type(args[2].value, self.model.symbols)
            self._diag_collection_value(name, expected, actual, args[2].span)
            return
        if name == "matrix.set" and len(args) >= 4:
            expected = self._collection_value_type(infer_type(args[0].value, self.model.symbols))
            actual = infer_type(args[3].value, self.model.symbols)
            self._diag_collection_value(name, expected, actual, args[3].span)
            return
        if name == "map.put" and len(args) >= 3:
            map_type = infer_type(args[0].value, self.model.symbols)
            expected_key = self._collection_value_type(map_type, key=True)
            expected_value = self._collection_value_type(map_type, key=False)
            self._diag_collection_value(
                name + " key",
                expected_key,
                infer_type(args[1].value, self.model.symbols),
                args[1].span,
            )
            self._diag_collection_value(
                name + " value",
                expected_value,
                infer_type(args[2].value, self.model.symbols),
                args[2].span,
            )
            return
        if name == "map.get" and len(args) >= 2:
            map_type = infer_type(args[0].value, self.model.symbols)
            expected_key = self._collection_value_type(map_type, key=True)
            self._diag_collection_value(
                name + " key",
                expected_key,
                infer_type(args[1].value, self.model.symbols),
                args[1].span,
            )
            return
        # Method forms: values.push(v), values.set(i, v), dict.put(k, v), matrix.set(r, c, v).
        if isinstance(expr.callee, MemberAccessExpr):
            receiver_type = infer_type(expr.callee.object, self.model.symbols)
            member = expr.callee.member
            if member in {"push", "unshift"} and len(args) >= 1:
                self._diag_collection_value(
                    name,
                    self._collection_value_type(receiver_type),
                    infer_type(args[0].value, self.model.symbols),
                    args[0].span,
                )
            elif member == "set" and receiver_type.startswith("array<") and len(args) >= 2:
                self._diag_collection_value(
                    name,
                    self._collection_value_type(receiver_type),
                    infer_type(args[1].value, self.model.symbols),
                    args[1].span,
                )
            elif member == "set" and receiver_type.startswith("matrix<") and len(args) >= 3:
                self._diag_collection_value(
                    name,
                    self._collection_value_type(receiver_type),
                    infer_type(args[2].value, self.model.symbols),
                    args[2].span,
                )
            elif member == "put" and receiver_type.startswith("map<") and len(args) >= 2:
                self._diag_collection_value(
                    name + " key",
                    self._collection_value_type(receiver_type, key=True),
                    infer_type(args[0].value, self.model.symbols),
                    args[0].span,
                )
                self._diag_collection_value(
                    name + " value",
                    self._collection_value_type(receiver_type, key=False),
                    infer_type(args[1].value, self.model.symbols),
                    args[1].span,
                )
            elif member == "get" and receiver_type.startswith("map<") and len(args) >= 1:
                self._diag_collection_value(
                    name + " key",
                    self._collection_value_type(receiver_type, key=True),
                    infer_type(args[0].value, self.model.symbols),
                    args[0].span,
                )

    def _validate_generic_constructor_call(self, name: str, expr: CallExpr) -> None:
        # array.new<float>(size, initial), matrix.new<float>(rows, cols, initial), map.new<string,float>()
        if not isinstance(expr.callee, GenericInstantiationExpr) or not expr.callee.type_args:
            return
        base = callee_name(expr.callee.base)
        type_args = [self._type_ref_name(t) for t in expr.callee.type_args]
        if base == "array.new" and len(expr.arguments) >= 2:
            expected = type_args[0]
            actual = infer_type(expr.arguments[1].value, self.model.symbols)
            self._diag_collection_value(name, expected, actual, expr.arguments[1].span)
        elif base == "matrix.new" and len(expr.arguments) >= 3:
            expected = type_args[0]
            actual = infer_type(expr.arguments[2].value, self.model.symbols)
            self._diag_collection_value(name, expected, actual, expr.arguments[2].span)

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
        supplied = set(field_names[: len(positional)]) | {n for n in named if n in field_names}
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
                actual = infer_type(arg.value, self.model.symbols)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Field {field_names[idx]} for {type_name}.new() expects {expected}, got {actual}.",
                        arg.span,
                    )
        for arg in expr.arguments:
            if arg.name and arg.name in field_names:
                field = fields[field_names.index(arg.name)]
                expected = (
                    self._type_ref_name(field.type_ref)
                    if getattr(field, "type_ref", None) is not None
                    else None
                )
                actual = infer_type(arg.value, self.model.symbols)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Field {arg.name} for {type_name}.new() expects {expected}, got {actual}.",
                        arg.span,
                    )

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
        if receiver_type.startswith("array<"):
            return member in {
                "get",
                "set",
                "push",
                "unshift",
                "pop",
                "shift",
                "first",
                "last",
                "size",
                "clear",
                "includes",
                "indexof",
            }
        if receiver_type.startswith("map<"):
            return member in {"get", "put", "remove", "contains", "keys", "values", "size", "clear"}
        if receiver_type.startswith("matrix<"):
            return member in {
                "get",
                "set",
                "rows",
                "columns",
                "add_row",
                "add_col",
                "remove_row",
                "remove_col",
            }
        return False

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

        receiver_type = infer_type(receiver_expr, self.model.symbols)
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
        actual = infer_type(expr.callee.object, self.model.symbols)
        if actual not in {receiver_type, "unknown"}:
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_TYPE,
                f"Method {method_name} expects receiver {receiver_type}, got {actual}.",
                expr.callee.span,
            )
        params = self._function_params.get(method_name, [])
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
                actual = infer_type(arg.value, self.model.symbols)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Argument {params[idx].name} for {name} expects {expected}, got {actual}.",
                        arg.span,
                    )
        by_name = {p.name: p for p in params}
        for arg in args:
            if arg.name and arg.name in by_name and by_name[arg.name].type_ref is not None:
                expected = self._type_ref_name(by_name[arg.name].type_ref)
                actual = infer_type(arg.value, self.model.symbols)
                if not self._is_assignable_type(expected, actual):
                    self._diag(
                        Severity.ERROR,
                        codes.ARGUMENT_TYPE,
                        f"Argument {arg.name} for {name} expects {expected}, got {actual}.",
                        arg.span,
                    )

    def _validate_builtin_call(self, name: str, entry: dict | None, expr: CallExpr) -> None:
        if not entry:
            return
        params = entry.get("parameters") or []
        if not params:
            return
        active_params = [p for p in params if not p.get("removed_in")]
        known = {p.get("name") for p in active_params if p.get("name")}
        removed = {p.get("name"): p for p in params if p.get("name") and p.get("removed_in")}
        required = [p for p in active_params if p.get("required")]
        positional = [a for a in expr.arguments if a.name is None]
        positional_count = len(positional)
        named = {a.name for a in expr.arguments if a.name}
        if positional_count > len(active_params) and not entry.get("allow_extra_positional"):
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Too many positional arguments for builtin {name}.",
                expr.span,
            )
        for arg_index, arg in enumerate(expr.arguments):
            param = None
            if arg.name:
                if arg.name in removed:
                    code = removed[arg.name].get("diagnostic_code") or codes.UNKNOWN_PARAMETER
                    self._diag(
                        Severity.ERROR,
                        code,
                        f"Parameter {arg.name} was removed or is not valid for {name} in Pine v6.",
                        arg.span,
                    )
                    continue
                elif known and arg.name not in known:
                    self._diag(
                        Severity.ERROR,
                        codes.UNKNOWN_PARAMETER,
                        f"Unknown parameter {arg.name} for builtin {name}.",
                        arg.span,
                    )
                    continue
                param = next((p for p in active_params if p.get("name") == arg.name), None)
            elif arg_index < len(active_params):
                param = active_params[arg_index]
            self._validate_argument_qualifier(name, arg, param)
            self._validate_argument_type(name, arg, param)
        positional_param_names = [
            p.get("name") for p in active_params[:positional_count] if p.get("name")
        ]
        for arg in expr.arguments:
            if arg.name and arg.name in positional_param_names:
                self._diag(
                    Severity.ERROR,
                    codes.DUPLICATE_NAMED_ARGUMENT,
                    f"Parameter {arg.name} for builtin {name} is supplied both positionally and by name.",
                    arg.span,
                )
        supplied = set(positional_param_names) | (named & known)
        missing_required = [p.get("name") for p in required if p.get("name") not in supplied]
        if missing_required:
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Missing required parameter(s) for {name}: {', '.join(missing_required)}.",
                expr.span,
            )

    def _validate_argument_qualifier(self, callee: str, arg, param: dict | None) -> None:
        if not param:
            return
        max_q = param.get("qualifier_max")
        if not max_q:
            return
        order = {"const": 0, "input": 1, "simple": 2, "series": 3}
        q = infer_qualifier(arg.value, self.model.symbols)
        if order.get(q, 3) > order.get(max_q, 3):
            pname = param.get("name") or "<positional>"
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_QUALIFIER,
                f"Argument {pname} for {callee} requires {max_q} or weaker qualifier, got {q}.",
                arg.span,
            )

    def _member_owner_type(self, expr: MemberAccessExpr) -> str | None:
        if isinstance(expr.object, Identifier):
            sym = self._resolve(expr.object.name)
            return sym.type if sym is not None else None
        if isinstance(expr.object, MemberAccessExpr):
            return infer_type(expr.object, self.model.symbols)
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

    def _visit_callee(self, expr: Expression) -> None:
        # Validate the root of a call without treating every member segment as a standalone variable.
        if isinstance(expr, Identifier):
            if self._resolve(expr.name) is None and not expr.name.startswith("<"):
                self._diag(
                    Severity.ERROR,
                    codes.UNDECLARED_VARIABLE,
                    f"Use of undeclared function {expr.name}.",
                    expr.span,
                )
            return
        if isinstance(expr, GenericInstantiationExpr):
            self._visit_callee(expr.base)
            return
        if isinstance(expr, MemberAccessExpr):
            if isinstance(expr.object, Identifier):
                root = expr.object.name
                if self._resolve(root) is None and root not in self._external_aliases:
                    self._diag(
                        Severity.ERROR,
                        codes.UNDECLARED_VARIABLE,
                        f"Use of undeclared namespace/object {root}.",
                        expr.object.span,
                    )
            else:
                self._visit_expr(expr.object)

    def _resolve_assignable(self, expr: Expression) -> Symbol | None:
        if isinstance(expr, Identifier):
            return self._resolve(expr.name)
        if isinstance(expr, MemberAccessExpr):
            root = self._member_root(expr)
            sym = self._resolve(root) if root else None
            if sym is None and root in self._external_aliases:
                return Symbol(
                    -1,
                    root,
                    SymbolKind.IMPORT_ALIAS,
                    expr.span,
                    "external",
                    None,
                    self.scope_stack[-1].id,
                )
            return sym
        return None

    def _member_root(self, expr: Expression) -> str | None:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            return self._member_root(expr.object)
        return None

    def _assignable_name(self, expr: Expression) -> str | None:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            root = self._member_root(expr)
            return root + ".<member>" if root else None
        return None

    def _define(
        self,
        name: str,
        kind: SymbolKind,
        span: SourceSpan,
        typ: str | None,
        qualifier: str | None,
        *,
        allow_existing: bool = False,
    ) -> Symbol | None:
        scope = self.scope_stack[-1]
        if name in scope.symbols and not allow_existing:
            self._diag(
                Severity.ERROR,
                codes.REDECLARATION,
                f"Symbol {name} is already declared in this scope.",
                span,
            )
            return None
        previous = self.model.symbols.get(name)
        sym = Symbol(self.next_symbol_id, name, kind, span, typ, qualifier, scope.id)
        self.next_symbol_id += 1
        scope.symbols[name] = sym.id
        if previous is not None and previous.id != sym.id:
            self._symbol_history.setdefault(name, []).append(previous)
        self.model.symbols[name] = sym
        return sym

    def _resolve(self, name: str | None) -> Symbol | None:
        if not name:
            return None
        for scope in reversed(self.scope_stack):
            if name in scope.symbols:
                sid = scope.symbols[name]
                for sym in self.model.symbols.values():
                    if sym.id == sid:
                        return sym
        resolved = self.model.symbols.get(name)
        if resolved is None:
            return None
        kind = self._scope_kind(resolved.scope_id)
        if kind in {ScopeKind.GLOBAL, ScopeKind.TYPE_DECL, ScopeKind.ENUM_DECL}:
            return resolved
        if resolved.kind in {
            SymbolKind.BUILTIN,
            SymbolKind.TYPE,
            SymbolKind.ENUM,
            SymbolKind.ENUM_MEMBER,
            SymbolKind.IMPORT_ALIAS,
            SymbolKind.FUNCTION,
            SymbolKind.METHOD,
        }:
            return resolved
        return None

    def _push_scope(
        self,
        kind: ScopeKind,
        *,
        non_na_symbols: set[str] | None = None,
        non_na_paths: set[str] | None = None,
    ) -> Scope:
        parent_id = self.scope_stack[-1].id if self.scope_stack else None
        scope = Scope(len(self.model.scopes) + 1, kind, parent_id)
        paths = set(non_na_paths or set()) | set(non_na_symbols or set())
        if paths:
            scope.non_na_symbols.update({path for path in paths if "." not in path})
            self.model.non_na_scopes[scope.id] = set(scope.non_na_symbols)
            self.model.non_na_paths[scope.id] = set(paths)
        self.model.scopes.append(scope)
        self.scope_stack.append(scope)
        return scope

    def _pop_scope(self) -> None:
        scope = self.scope_stack.pop()
        # Keep exported/global and qualified type/member symbols visible, but make local-only
        # variables disappear after their block/function scope. When a local declaration shadows
        # an outer symbol with the same name, restore the outer symbol instead of leaving the
        # shadow in the public SemanticModel.symbols view.
        for name, sid in list(scope.symbols.items()):
            current = self.model.symbols.get(name)
            if current is None or current.id != sid:
                continue
            keep = scope.kind is ScopeKind.GLOBAL or (
                scope.kind is ScopeKind.TYPE_DECL and "." in name
            )
            if keep:
                continue
            history = self._symbol_history.get(name)
            if history:
                self.model.symbols[name] = history.pop()
                if not history:
                    self._symbol_history.pop(name, None)
            # If there is no shadowed symbol to restore, keep the local symbol in
            # SemanticModel.symbols for compatibility/introspection. Name resolution
            # below deliberately ignores out-of-scope local symbols, so this does not
            # leak locals into later semantic checks.

    def _has_diag(self, code: str, span: SourceSpan) -> bool:
        return any(
            diag.code == code
            and diag.span.start_offset == span.start_offset
            and diag.span.end_offset == span.end_offset
            for diag in self.model.diagnostics
        )

    def _diag(self, severity: Severity, code: str, message: str, span: SourceSpan) -> None:
        if len(self.model.diagnostics) < self.max_diagnostics:
            self.model.diagnostics.append(Diagnostic(severity, code, message, span))
