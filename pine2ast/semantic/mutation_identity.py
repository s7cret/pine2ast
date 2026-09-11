"""Associate writes with lexical declarations, never with global spellings.

This prepass only classifies mutation. The semantic analyzer still owns name,
type and assignment validation. It introduces neither evaluation nor coercion.
"""

from __future__ import annotations

from pine2ast.ast.nodes import (
    Block,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    Identifier,
    MemberAccessExpr,
    MethodDeclaration,
    Program,
    Reassignment,
    TupleDeclaration,
    VarDeclaration,
)
from pine2ast.ast.walk import iter_child_nodes


def reassigned_declarations(program: Program) -> frozenset[int]:
    """Return the identities of declarations written in their visible scope.

    Process declaration initializers before binding names. Function parameters,
    tuple targets and loop targets shadow outer names. Explicit stack traversal
    avoids recursion proportional to source size; scope frames are shared, not
    flattened copies of every visible declaration.
    """
    result: set[int] = set()
    # A None binding still shadows an outer variable (e.g. a parameter).
    scopes: tuple[dict, ...] = ({},)
    pending = [(program, scopes, False)]
    while pending:
        node, frames, bind = pending.pop()
        if bind:
            if isinstance(node, VarDeclaration):
                frames[-1][node.name] = node
            elif isinstance(node, TupleDeclaration):
                for target in node.targets:
                    if target.name != "_":
                        frames[-1][target.name] = target
            continue
        if isinstance(node, VarDeclaration):
            pending.append((node, frames, True))
            pending.append((node.initializer, frames, False))
            continue
        if isinstance(node, TupleDeclaration):
            pending.append((node, frames, True))
            pending.append((node.initializer, frames, False))
            continue
        if isinstance(node, (FunctionDeclaration, MethodDeclaration)):
            local = {p.name: None for p in node.parameters}
            if isinstance(node, MethodDeclaration) and node.receiver_name:
                local[node.receiver_name] = None
            pending.append((node.body, (*frames, local), False))
            # Defaults have their defining outer scope, not another function's locals.
            for p in reversed(node.parameters):
                if p.default_value is not None:
                    pending.append((p.default_value, frames, False))
            continue
        if isinstance(node, (ForRangeStructure, ForInStructure)):
            names = [node.variable] if isinstance(node, ForRangeStructure) else node.target.names
            local = (*frames, {name: None for name in names})
            for child in reversed(list(iter_child_nodes(node))):
                pending.append((child, local if child is node.body else frames, False))
            continue
        if isinstance(node, Reassignment):
            target = node.target
            while isinstance(target, MemberAccessExpr):
                target = target.object
            if isinstance(target, Identifier):
                for frame in reversed(frames):
                    if target.name in frame:
                        declaration = frame[target.name]
                        if declaration is not None:
                            result.add(id(declaration))
                        break
        nested = (*frames, {}) if isinstance(node, Block) else frames
        for child in reversed(list(iter_child_nodes(node))):
            pending.append((child, nested, False))
    return frozenset(result)
