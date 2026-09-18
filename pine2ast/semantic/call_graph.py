"""Reject user-call cycles by resolved declaration identity, not source spelling."""

from __future__ import annotations

from pine2ast.ast.nodes import CallExpr, FunctionDeclaration, MethodDeclaration
from pine2ast.ast.walk import iter_child_nodes
from pine2ast.diagnostics import Diagnostic, Severity, codes


def reject_recursive_calls(program, index, bindings, append_diagnostic) -> None:
    declarations = {
        f"user:{'method' if isinstance(n, MethodDeclaration) else 'function'}:{n.name}:{index.id_for(n)}": n
        for n in program.items
        if isinstance(n, (FunctionDeclaration, MethodDeclaration))
    }
    edges = {}
    for key, declaration in declarations.items():
        rows = []
        pending = [declaration.body]
        while pending:
            node = pending.pop()
            if isinstance(node, CallExpr):
                binding = bindings.get(id(node))
                if (
                    binding is not None
                    and binding.resolution_status == "RESOLVED"
                    and binding.symbol_id in declarations
                ):
                    rows.append((binding.symbol_id, node))
            pending.extend(iter_child_nodes(node))
        edges[key] = rows
    # Iterative DFS is linear in the admitted AST/call graph and cannot exceed
    # Python recursion depth on a long acyclic chain of independent overloads.
    color = {}
    for root in declarations:
        if root in color:
            continue
        color[root] = 1
        pending = [(root, iter(edges[root]))]
        while pending:
            key, children = pending[-1]
            try:
                target, call = next(children)
            except StopIteration:
                color[key] = 2
                pending.pop()
                continue
            if color.get(target) == 1:
                append_diagnostic(
                    Diagnostic(
                        Severity.ERROR,
                        codes.RECURSIVE_CALL,
                        "Recursive user-function or method call is not permitted: "
                        + declarations[target].name,
                        call.span,
                    )
                )
            elif target not in color:
                color[target] = 1
                pending.append((target, iter(edges[target])))
