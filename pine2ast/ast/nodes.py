from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pine2ast.ast.base import ASTNode, Declaration, Expression, Statement
from pine2ast.ast.types import TypeRef
from pine2ast.diagnostics.diagnostic import Diagnostic
from pine2ast.lexer.annotations import Annotation
from pine2ast.lexer.token import SourceSpan


@dataclass(slots=True)
class Program(ASTNode):
    span: SourceSpan
    version: int | None
    annotations: list[Annotation]
    declaration: "DeclarationStatement | None"
    items: list[Statement]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    schema_version: str = "1.0"
    language: str = "pine"
    language_version: int = 6


@dataclass(slots=True)
class Block(ASTNode):
    span: SourceSpan
    statements: list[Statement]


@dataclass(slots=True)
class DeclarationStatement(Declaration):
    span: SourceSpan
    script_type: Literal["indicator", "strategy", "library"]
    call: "CallExpr"


@dataclass(slots=True)
class ImportDeclaration(Declaration):
    span: SourceSpan
    path: str
    owner: str | None
    library: str | None
    version: str | None
    alias: str | None


@dataclass(slots=True)
class FieldDeclaration(ASTNode):
    span: SourceSpan
    name: str
    type_ref: TypeRef
    default_value: Expression | None = None


@dataclass(slots=True)
class TypeDeclaration(Declaration):
    span: SourceSpan
    name: str
    fields: list[FieldDeclaration]
    is_exported: bool = False


@dataclass(slots=True)
class EnumMember(ASTNode):
    span: SourceSpan
    name: str
    title: str | None = None


@dataclass(slots=True)
class EnumDeclaration(Declaration):
    span: SourceSpan
    name: str
    members: list[EnumMember]
    is_exported: bool = False


@dataclass(slots=True)
class Parameter(ASTNode):
    span: SourceSpan
    name: str
    type_ref: TypeRef | None = None
    explicit_qualifier: str | None = None
    default_value: Expression | None = None


@dataclass(slots=True)
class FunctionDeclaration(Declaration):
    span: SourceSpan
    name: str
    parameters: list[Parameter]
    body: Block | Expression
    is_exported: bool = False


@dataclass(slots=True)
class MethodDeclaration(Declaration):
    span: SourceSpan
    name: str
    receiver_type: TypeRef | None
    receiver_name: str | None
    parameters: list[Parameter]
    body: Block | Expression
    is_exported: bool = False


@dataclass(slots=True)
class VarDeclaration(Statement):
    span: SourceSpan
    name: str
    mode: Literal["var", "varip"] | None
    explicit_qualifier: Literal["const", "simple", "series"] | None
    type_ref: TypeRef | None
    initializer: Expression
    is_exported: bool = False


@dataclass(slots=True)
class TupleTarget(ASTNode):
    span: SourceSpan
    name: str


@dataclass(slots=True)
class TupleDeclaration(Statement):
    span: SourceSpan
    targets: list[TupleTarget]
    initializer: Expression


@dataclass(slots=True)
class Reassignment(Statement):
    span: SourceSpan
    target: Expression
    op: Literal[":=", "+=", "-=", "*=", "/=", "%="]
    value: Expression


@dataclass(slots=True)
class ExpressionStatement(Statement):
    span: SourceSpan
    expression: Expression


@dataclass(slots=True)
class BreakStatement(Statement):
    span: SourceSpan


@dataclass(slots=True)
class ContinueStatement(Statement):
    span: SourceSpan


@dataclass(slots=True)
class ElseIfBranch(ASTNode):
    span: SourceSpan
    condition: Expression
    block: Block


@dataclass(slots=True)
class IfStructure(Expression, Statement):
    span: SourceSpan
    condition: Expression
    then_block: Block
    else_if_branches: list[ElseIfBranch] = field(default_factory=list)
    else_block: Block | None = None


@dataclass(slots=True)
class SwitchCase(ASTNode):
    span: SourceSpan
    condition: Expression | None
    body: Block | Expression


@dataclass(slots=True)
class SwitchStructure(Expression, Statement):
    span: SourceSpan
    expression: Expression | None
    cases: list[SwitchCase]


@dataclass(slots=True)
class ForInTarget(ASTNode):
    span: SourceSpan
    names: list[str]


@dataclass(slots=True)
class ForRangeStructure(Expression, Statement):
    span: SourceSpan
    variable: str
    start: Expression
    end: Expression
    step: Expression | None
    body: Block


@dataclass(slots=True)
class ForInStructure(Expression, Statement):
    span: SourceSpan
    target: ForInTarget
    iterable: Expression
    body: Block


@dataclass(slots=True)
class WhileStructure(Expression, Statement):
    span: SourceSpan
    condition: Expression
    body: Block


@dataclass(slots=True)
class Identifier(Expression):
    span: SourceSpan
    name: str


@dataclass(slots=True)
class Literal(Expression):
    span: SourceSpan
    value: object
    literal_type: Literal["int", "float", "bool", "string", "color", "na"]




@dataclass(slots=True)
class TupleExpr(Expression):
    span: SourceSpan
    elements: list[Expression]


# Backward-compatible alias for legacy v1.18 hardening tests. Pine uses tuple/list-like
# bracket expressions in several contexts; v2.x keeps TupleExpr as the canonical JSON kind.
ArrayLiteralExpr = TupleExpr


@dataclass(slots=True)
class MemberAccessExpr(Expression):
    span: SourceSpan
    object: Expression
    member: str


@dataclass(slots=True)
class Argument(ASTNode):
    span: SourceSpan
    name: str | None
    value: Expression


@dataclass(slots=True)
class CallExpr(Expression):
    span: SourceSpan
    callee: Expression
    arguments: list[Argument]


@dataclass(slots=True)
class GenericInstantiationExpr(Expression):
    span: SourceSpan
    base: Expression
    type_args: list[TypeRef]


@dataclass(slots=True)
class HistoryRefExpr(Expression):
    span: SourceSpan
    base: Expression
    offset: Expression


@dataclass(slots=True)
class UnaryExpr(Expression):
    span: SourceSpan
    op: str
    operand: Expression


@dataclass(slots=True)
class BinaryExpr(Expression):
    span: SourceSpan
    op: str
    left: Expression
    right: Expression


@dataclass(slots=True)
class ConditionalExpr(Expression):
    span: SourceSpan
    condition: Expression
    if_true: Expression
    if_false: Expression
