"""Closed reconstruction of the canonical AST model for semantic admission.

Field names and types come only from trusted model dataclasses. Input cannot
select a Python class, import, callback or schema. One budget covers preflight,
decoding and every failed union alternative before semantic replay.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from functools import lru_cache
import math
import types
from typing import Any, Literal, Mapping, Union, get_args, get_origin, get_type_hints

from pine2ast.ast import nodes
from pine2ast.ast.base import ASTNode
from pine2ast.ast.types import TypeRef


class ASTDecodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ASTReplayLimits:
    max_bytes: int = 16 * 1024 * 1024
    max_depth: int = 128
    max_values: int = 1_000_000
    max_ast_nodes: int = 500_000
    max_container_items: int = 100_000
    max_string_length: int = 1024 * 1024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            ceiling = item.default
            if type(ceiling) is not int:
                raise ASTDecodeError(f"invalid default replay limit: {item.name}")
            if type(value) is not int or value < 1 or value > ceiling:
                raise ASTDecodeError(f"invalid or excessive replay limit: {item.name}")


class ASTAdmissionBudget:
    def __init__(self, limits: ASTReplayLimits | None = None) -> None:
        self.limits = limits or ASTReplayLimits()
        self.work = 0
        self.ast_nodes = 0

    def charge(self, count: int = 1) -> None:
        self.work += count
        if self.work > self.limits.max_values:
            raise ASTDecodeError("AST admission work limit exceeded")

    def preflight(self, value: object) -> None:
        """Bound plain JSON without first copying or serializing the input."""
        active: set[int] = set()
        stack = [(value, 0, False)]
        size = 0
        while stack:
            current, depth, closing = stack.pop()
            if closing:
                active.remove(id(current))
                continue
            self.charge()
            if depth > self.limits.max_depth:
                raise ASTDecodeError("AST admission depth limit exceeded")
            if type(current) is dict or type(current) is list:
                if id(current) in active:
                    raise ASTDecodeError("cyclic JSON input")
                if len(current) > self.limits.max_container_items:
                    raise ASTDecodeError("AST admission container limit exceeded")
                active.add(id(current))
                stack.append((current, depth, True))
                size += 2 + max(0, len(current) - 1)
                if type(current) is dict:
                    for key, item in current.items():
                        if type(key) is not str:
                            raise ASTDecodeError("JSON keys must be strings")
                        size += 1
                        stack.append((item, depth + 1, False))
                        stack.append((key, depth + 1, False))
                else:
                    stack.extend((item, depth + 1, False) for item in current)
            elif type(current) is str:
                if len(current) > self.limits.max_string_length:
                    raise ASTDecodeError("AST admission string limit exceeded")
                # The length guard above bounds this temporary UTF-8 buffer
                # to 4 MiB. No whole input is copied or JSON-canonicalized.
                # Native string operations avoid a traced Python allocation
                # per character while retaining the exact same JSON size.
                try:
                    size += 2 + len(current.encode("utf-8"))
                except UnicodeEncodeError as exc:
                    raise ASTDecodeError("unpaired Unicode surrogate") from exc
                size += current.count("\\") + current.count('"')
                if not current.isprintable():
                    for code in range(32):
                        size += current.count(chr(code)) * (1 if code in (8, 9, 10, 12, 13) else 5)
            elif current is None:
                size += 4
            elif type(current) is bool:
                size += 4 if current else 5
            elif type(current) in (int, float):
                if type(current) is float and not math.isfinite(current):
                    raise ASTDecodeError("nonfinite JSON number")
                try:
                    size += len(str(current))
                except ValueError as exc:
                    raise ASTDecodeError("JSON number limit exceeded") from exc
            else:
                raise ASTDecodeError("input must contain only plain JSON values")
            if size > self.limits.max_bytes:
                raise ASTDecodeError("AST admission byte limit exceeded")


# This registry is derived from trusted canonical definitions, not payload names.
_NODE_TYPES = {
    cls.__name__: cls
    for cls in vars(nodes).values()
    if isinstance(cls, type) and issubclass(cls, ASTNode) and is_dataclass(cls)
}
_NODE_TYPES["TypeRef"] = TypeRef


@lru_cache(maxsize=128)
def _model_fields(cls: type) -> tuple[dict[str, Any], dict[str, Any]]:
    return {f.name: f for f in fields(cls)}, get_type_hints(cls)


class _ShapeMismatch(Exception):
    pass


class _Decoder:
    def __init__(self, budget: ASTAdmissionBudget) -> None:
        self.budget = budget
        self.ast_identities: set[int] = set()

    def decode(self, value: object, expected: Any, depth: int = 0) -> Any:
        self.budget.charge()
        if depth > self.budget.limits.max_depth:
            raise ASTDecodeError("AST reconstruction depth limit exceeded")
        origin = get_origin(expected)
        if origin in (Union, types.UnionType):
            for alternative in get_args(expected):
                try:
                    return self.decode(value, alternative, depth)
                except _ShapeMismatch:
                    pass  # Failed alternatives share the same work budget.
            raise _ShapeMismatch("union shape mismatch")
        if expected is type(None):
            if value is not None:
                raise _ShapeMismatch("null required")
            return None
        if origin is Literal:
            if not any(type(value) is type(x) and value == x for x in get_args(expected)):
                raise _ShapeMismatch("literal value mismatch")
            return value
        if expected in (str, int, float, bool):
            if type(value) is not expected:
                raise _ShapeMismatch("primitive type mismatch")
            return value
        if isinstance(expected, type) and issubclass(expected, Enum):
            try:
                return expected(value)
            except (ValueError, TypeError) as exc:
                raise _ShapeMismatch("enum value mismatch") from exc
        if origin is list:
            if type(value) is not list:
                raise _ShapeMismatch("list required")
            return [self.decode(item, get_args(expected)[0], depth + 1) for item in value]
        if origin is dict or expected in (object, Any):
            if type(value) is dict:
                element = get_args(expected)[1] if origin is dict else object
                return {key: self.decode(item, element, depth + 1) for key, item in value.items()}
            if expected in (object, Any) and type(value) is list:
                return [self.decode(item, object, depth + 1) for item in value]
            if expected in (object, Any) and (
                value is None or type(value) in (str, int, float, bool)
            ):
                return value
            raise _ShapeMismatch("plain JSON mapping/value required")
        cls = expected
        if isinstance(expected, type) and issubclass(expected, ASTNode):
            if type(value) is not dict:
                raise _ShapeMismatch("AST object required")
            cls = _NODE_TYPES.get(value.get("kind"))
            if cls is None or not issubclass(cls, expected):
                raise _ShapeMismatch("AST kind mismatch")
        if isinstance(cls, type) and is_dataclass(cls):
            if type(value) is not dict:
                raise _ShapeMismatch("model object required")
            schema, hints = _model_fields(cls)
            is_ast = issubclass(cls, ASTNode)
            if set(value) - set(schema) - ({"kind"} if is_ast else set()):
                raise _ShapeMismatch("unknown canonical model field")
            kwargs = {}
            for name, item in schema.items():
                if name not in value:
                    if not item.metadata.get("omit_none"):
                        raise _ShapeMismatch("missing canonical model field")
                    continue
                if item.metadata.get("omit_none") and value[name] is None:
                    raise _ShapeMismatch("explicit null is not an omitted field")
                kwargs[name] = self.decode(value[name], hints[name], depth + 1)
            if is_ast:
                if id(value) in self.ast_identities:
                    raise ASTDecodeError("shared AST node identity")
                self.ast_identities.add(id(value))
                self.budget.ast_nodes += 1
                if self.budget.ast_nodes > self.budget.limits.max_ast_nodes:
                    raise ASTDecodeError("AST node limit exceeded")
            try:
                return cls(**kwargs)
            except (ValueError, TypeError) as exc:
                raise _ShapeMismatch(str(exc)) from exc
        raise _ShapeMismatch("unsupported canonical model type")


def decode_program(
    payload: Mapping[str, object], *, budget: ASTAdmissionBudget | None = None
) -> nodes.Program:
    """Decode only canonical model data; no parsing or semantic inference."""
    from pine2ast.ast.schema import validate_ast_schema
    from pine2ast.ast.serialize import ast_to_dict

    work = budget or ASTAdmissionBudget()
    work.preflight(payload)
    try:
        program = _Decoder(work).decode(payload, nodes.Program)
        report = validate_ast_schema(program)
        if not report.ok:
            raise ASTDecodeError("reconstructed AST schema is invalid")
        if ast_to_dict(program) != payload:
            raise ASTDecodeError("canonical AST reconstruction mismatch")
        return program
    except (_ShapeMismatch, RecursionError, TypeError, KeyError) as exc:
        raise ASTDecodeError(f"invalid canonical AST: {exc}") from exc
