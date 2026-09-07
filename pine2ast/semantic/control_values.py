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
