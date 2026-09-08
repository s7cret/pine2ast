"""Return-expression paths of structural values, excluding abrupt loop control.

A break/continue path does not manufacture a void value that conflicts with the
value produced by another branch. A real void function call still does.
"""

from __future__ import annotations

from pine2ast.ast.base import Expression
from pine2ast.ast.nodes import (
    Block,
    BreakStatement,
    ContinueStatement,
    ExpressionStatement,
    ForRangeStructure,
    ForInStructure,
    IfStructure,
    Reassignment,
    SwitchStructure,
    VarDeclaration,
    WhileStructure,
)


def returned_expressions(node) -> tuple[Expression, ...]:
    if isinstance(node, Block):
        return returned_expressions(node.statements[-1]) if node.statements else ()
    if isinstance(node, (BreakStatement, ContinueStatement)):
        return ()
    if isinstance(node, (ForRangeStructure, ForInStructure, WhileStructure)):
        return returned_expressions(node.body)
    if isinstance(node, IfStructure):
        blocks = [node.then_block, *(b.block for b in node.else_if_branches)]
        if node.else_block is not None:
            blocks.append(node.else_block)
        return tuple(expr for block in blocks for expr in returned_expressions(block))
    if isinstance(node, SwitchStructure):
        return tuple(expr for case in node.cases for expr in returned_expressions(case.body))
    if isinstance(node, ExpressionStatement):
        return returned_expressions(node.expression)
    if isinstance(node, VarDeclaration):
        return returned_expressions(node.initializer)
    if isinstance(node, Reassignment):
        return returned_expressions(node.value)
    return (node,) if isinstance(node, Expression) else ()


def _return_roots(node) -> tuple[Expression, ...]:
    """Unwrap a statement tail without erasing nested structures or loops."""
    if isinstance(node, Block):
        return _return_roots(node.statements[-1]) if node.statements else ()
    if isinstance(node, ExpressionStatement):
        return _return_roots(node.expression)
    if isinstance(node, VarDeclaration):
        return _return_roots(node.initializer)
    if isinstance(node, Reassignment):
        return _return_roots(node.value)
    return (node,) if isinstance(node, Expression) else ()


def structural_qualifier_sources(node: IfStructure | SwitchStructure) -> tuple[Expression, ...]:
    """Immediate value roots and guards for recursive qualifier/dependency joins.

    Type inference may merge flattened leaves. Qualifier inference must retain
    every nested guard and each loop node's own qualifier; flattening those nodes
    would turn changing control flow into a falsely simple result.
    """
    if isinstance(node, IfStructure):
        blocks: list[Block | Expression] = [
            node.then_block,
            *(branch.block for branch in node.else_if_branches),
        ]
        if node.else_block is not None:
            blocks.append(node.else_block)
        guards = [node.condition, *(branch.condition for branch in node.else_if_branches)]
    else:
        blocks = [case.body for case in node.cases]
        guards = [case.condition for case in node.cases if case.condition is not None]
        if node.expression is not None:
            guards.append(node.expression)
    return (*guards, *(value for block in blocks for value in _return_roots(block)))
