from __future__ import annotations

from dataclasses import dataclass

from pine2ast.ast.nodes import (
    Argument,
    CallExpr,
    Identifier,
    Literal,
    MemberAccessExpr,
    Program,
    TupleExpr,
    VarDeclaration,
)
from pine2ast.ast.visitors import walk
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.type_infer import callee_name


@dataclass(slots=True)
class InputParameter:
    name: str
    title: str | None
    input_function: str
    default_value: object | None
    minval: object | None
    maxval: object | None
    step: object | None
    options: list[object] | None
    span: SourceSpan


@dataclass(slots=True)
class StrategyCall:
    name: str
    arguments: list[Argument]
    span: SourceSpan


def _const_value_expr(expr) -> object | None:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, MemberAccessExpr):
        return callee_name(expr)
    if isinstance(expr, Identifier):
        return expr.name
    return getattr(expr, "value", None)


def _literal_value(arg: Argument) -> object | None:
    return _const_value_expr(arg.value)


def _literal_sequence(arg: Argument | None) -> list[object] | None:
    if arg is None:
        return None
    if isinstance(arg.value, TupleExpr):
        return [_const_value_expr(item) for item in arg.value.elements]
    if isinstance(arg.value, CallExpr) and callee_name(arg.value.callee) == "array.from":
        return [_const_value_expr(item.value) for item in arg.value.arguments]
    return None


def _named(args: list[Argument], name: str) -> Argument | None:
    return next((a for a in args if a.name == name), None)


def extract_inputs(program: Program, semantic=None) -> list[InputParameter]:
    result: list[InputParameter] = []
    owner_names: dict[int, str] = {}
    for node in walk(program):
        if isinstance(node, VarDeclaration) and isinstance(node.initializer, CallExpr):
            owner_names[id(node.initializer)] = node.name
    for node in walk(program):
        if isinstance(node, CallExpr):
            name = callee_name(node.callee)
            if name.startswith("input."):
                default_arg = (
                    node.arguments[0]
                    if node.arguments and node.arguments[0].name is None
                    else _named(node.arguments, "defval")
                )
                title_arg = _named(node.arguments, "title")
                if title_arg is None and len(node.arguments) > 1 and node.arguments[1].name is None:
                    title_arg = node.arguments[1]
                title = (
                    title_arg.value.value
                    if title_arg and hasattr(title_arg.value, "value")
                    else None
                )
                minval_arg = _named(node.arguments, "minval")
                maxval_arg = _named(node.arguments, "maxval")
                step_arg = _named(node.arguments, "step")
                result.append(
                    InputParameter(
                        name=owner_names.get(id(node)) or title or name,
                        title=title,
                        input_function=name,
                        default_value=_literal_value(default_arg) if default_arg else None,
                        minval=_literal_value(minval_arg) if minval_arg else None,
                        maxval=_literal_value(maxval_arg) if maxval_arg else None,
                        step=_literal_value(step_arg) if step_arg else None,
                        options=_literal_sequence(_named(node.arguments, "options")),
                        span=node.span,
                    )
                )
    return result


def extract_strategy_calls(program: Program) -> list[StrategyCall]:
    result: list[StrategyCall] = []
    for node in walk(program):
        if isinstance(node, CallExpr):
            name = callee_name(node.callee)
            if name.startswith("strategy."):
                result.append(StrategyCall(name, node.arguments, node.span))
    return result


def extract_request_calls(program: Program) -> list[CallExpr]:
    return [
        node
        for node in walk(program)
        if isinstance(node, CallExpr) and callee_name(node.callee).startswith("request.")
    ]


def extract_plots(program: Program) -> list[CallExpr]:
    return [
        node
        for node in walk(program)
        if isinstance(node, CallExpr)
        and callee_name(node.callee) in {"plot", "plotshape", "plotchar", "hline"}
    ]


@dataclass(slots=True)
class GenericCall:
    name: str
    arguments: list[Argument]
    span: SourceSpan


@dataclass(slots=True)
class DependencyReport:
    imports: list[str]
    import_aliases: list[str]
    namespaces: list[str]
    builtin_calls: list[str]
    user_function_calls: list[str]
    method_calls: list[str]
    udt_constructors: list[str]
    external_calls: list[str]
    unknown_calls: list[str]


def extract_alertconditions(program: Program) -> list[GenericCall]:
    return [
        GenericCall(callee_name(node.callee), node.arguments, node.span)
        for node in walk(program)
        if isinstance(node, CallExpr) and callee_name(node.callee) == "alertcondition"
    ]


def extract_drawing_calls(program: Program) -> list[GenericCall]:
    drawing_names = {
        "label.new",
        "line.new",
        "box.new",
        "table.new",
        "polyline.new",
        "label.set_text",
        "label.set_xy",
        "line.set_xy1",
        "line.set_xy2",
        "box.set_bgcolor",
        "table.cell",
        "table.clear",
    }
    return [
        GenericCall(callee_name(node.callee), node.arguments, node.span)
        for node in walk(program)
        if isinstance(node, CallExpr) and callee_name(node.callee) in drawing_names
    ]


def extract_dependencies(program: Program, semantic=None) -> DependencyReport:
    from pine2ast.ast.nodes import (
        FunctionDeclaration,
        MethodDeclaration,
        TypeDeclaration,
        ImportDeclaration,
        GenericInstantiationExpr,
    )
    from pine2ast.semantic.builtin_registry import load_builtin_registry

    registry = load_builtin_registry()
    builtin_functions = set(registry.get("functions", {}))
    namespaces = set(registry.get("namespaces", {}))
    user_functions = {n.name for n in walk(program) if isinstance(n, FunctionDeclaration)}
    methods = {n.name for n in walk(program) if isinstance(n, MethodDeclaration)}
    udt_types = {n.name for n in walk(program) if isinstance(n, TypeDeclaration)}
    imports = [n.path for n in walk(program) if isinstance(n, ImportDeclaration)]
    aliases = [
        n.alias or n.library or n.owner or n.path
        for n in walk(program)
        if isinstance(n, ImportDeclaration)
    ]

    used_namespaces: set[str] = set()
    builtin_calls: set[str] = set()
    user_calls: set[str] = set()
    method_calls: set[str] = set()
    constructors: set[str] = set()
    external_calls: set[str] = set()
    unknown_calls: set[str] = set()

    for node in walk(program):
        if not isinstance(node, CallExpr):
            continue
        name = callee_name(node.callee)
        root = name.split(".", 1)[0].split("<", 1)[0]
        if root in namespaces:
            used_namespaces.add(root)
        if name in builtin_functions:
            builtin_calls.add(name)
            continue
        if name in user_functions:
            user_calls.add(name)
            continue
        if "." in name:
            member = name.rsplit(".", 1)[-1]
            if member in methods:
                method_calls.add(member)
                continue
            if member == "new" and root in udt_types:
                constructors.add(root)
                continue
            if root in aliases:
                external_calls.add(name)
                continue
        base_name = name
        if isinstance(node.callee, GenericInstantiationExpr):
            base_name = callee_name(node.callee.base)
        if base_name in builtin_functions:
            builtin_calls.add(name)
        else:
            unknown_calls.add(name)

    return DependencyReport(
        imports=sorted(imports),
        import_aliases=sorted(a for a in aliases if a),
        namespaces=sorted(used_namespaces),
        builtin_calls=sorted(builtin_calls),
        user_function_calls=sorted(user_calls),
        method_calls=sorted(method_calls),
        udt_constructors=sorted(constructors),
        external_calls=sorted(external_calls),
        unknown_calls=sorted(unknown_calls),
    )
