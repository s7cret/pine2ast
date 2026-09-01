from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import Argument, CallExpr, Identifier, Literal, MemberAccessExpr
from pine2ast.frontend import collections as collection_frontend
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.collection_signatures import (
    CollectionArgumentBinding,
    CollectionCallResolution,
    CollectionParameterSpec,
)

SPAN = SourceSpan(0, 1, 1, 1, 1, 2)


def _identifier(name: str) -> Identifier:
    return Identifier(SPAN, name)


def _literal(value: object, literal_type: str) -> Literal:
    return Literal(SPAN, value, literal_type)  # type: ignore[arg-type]


def _arg(value: Any, name: str | None = None) -> Argument:
    return Argument(SPAN, name, value)


def _function_call(kind: str, operation: str, *args: Argument) -> CallExpr:
    return CallExpr(SPAN, MemberAccessExpr(SPAN, _identifier(kind), operation), list(args))


def _method_call(receiver: str, operation: str, *args: Argument) -> CallExpr:
    return CallExpr(SPAN, MemberAccessExpr(SPAN, _identifier(receiver), operation), list(args))


class _Engine:
    def __init__(self) -> None:
        self.types = {
            "a": "array<float>",
            "mat": "matrix<float>",
            "m": "map<string,float>",
            "unknown": "unknown",
        }
        self.call_result = "unknown"

    def infer_type(self, value: Any) -> str:
        if isinstance(value, Identifier):
            return self.types.get(value.name, "unknown")
        if isinstance(value, Literal):
            return value.literal_type
        if isinstance(value, CallExpr):
            return self.call_result
        return "unknown"

    def infer_qualifier(self, value: Any) -> str:
        return "const" if isinstance(value, Literal) else "series"

    def infer_value(self, value: Any) -> SimpleNamespace:
        type_name = self.infer_type(value)
        return SimpleNamespace(
            type_name=type_name,
            qualifier=self.infer_qualifier(value),
            can_be_na=type_name not in {"bool", "int", "string"},
            is_reference=type_name.startswith(("array<", "matrix<", "map<")),
            is_collection=type_name.startswith(("array<", "matrix<", "map<")),
        )


@pytest.fixture
def fallback_environment(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _Engine]:
    profile = parse_code('//@version=6\nindicator("collections")\n').ast.version_context
    engine = _Engine()
    monkeypatch.setattr(
        collection_frontend, "_resolve_collection_call", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(collection_frontend, "_inference_engine", lambda *args, **kwargs: engine)

    def target_descriptor(expr: Any, symbols: Any, *, profile: Any) -> dict[str, Any]:
        del symbols, profile
        type_name = engine.infer_type(expr)
        return {
            "expr": getattr(expr, "name", type(expr).__name__),
            "type": type_name,
            **collection_frontend._collection_type_parts(type_name),
        }

    monkeypatch.setattr(collection_frontend, "_target_descriptor", target_descriptor)
    monkeypatch.setattr(
        collection_frontend,
        "_bound_arguments",
        lambda name, args, **kwargs: [
            {"position": index, "parameter": arg.name, "binding": "fallback"}
            for index, arg in enumerate(args)
        ],
    )
    return profile, engine


def test_fallback_collection_mutations_cover_function_forms(
    fallback_environment: tuple[Any, _Engine],
) -> None:
    profile, _engine = fallback_environment
    cases = [
        (
            _function_call("array", "push", _arg(_identifier("a")), _arg(_literal(1.0, "float"))),
            "push",
            {"value"},
        ),
        (
            _function_call(
                "array", "unshift", _arg(_identifier("a")), _arg(_literal(2.0, "float"))
            ),
            "unshift",
            {"value"},
        ),
        (
            _function_call(
                "array",
                "set",
                _arg(_identifier("a")),
                _arg(_literal(0, "int")),
                _arg(_literal(3.0, "float")),
            ),
            "set",
            {"index", "value"},
        ),
        (
            _function_call(
                "matrix",
                "set",
                _arg(_identifier("mat")),
                _arg(_literal(0, "int")),
                _arg(_literal(1, "int")),
                _arg(_literal(4.0, "float")),
            ),
            "set",
            {"row", "column", "value"},
        ),
        (
            _function_call(
                "map",
                "put",
                _arg(_identifier("m")),
                _arg(_literal("k", "string")),
                _arg(_literal(5.0, "float")),
            ),
            "put",
            {"key", "value"},
        ),
        (
            _function_call("map", "remove", _arg(_identifier("m")), _arg(_literal("k", "string"))),
            "remove",
            {"key"},
        ),
        (_function_call("array", "clear", _arg(_identifier("a"))), "clear", set()),
        (_function_call("map", "clear", _arg(_identifier("m"))), "clear", set()),
        (_function_call("matrix", "clear", _arg(_identifier("mat"))), "clear", set()),
    ]
    for call, operation, extra_keys in cases:
        row = collection_frontend._collection_mutation_descriptor(
            call, symbols=None, context=("function",), profile=profile
        )
        assert row is not None
        assert row["operation"] == operation
        assert row["local_scope"] is True
        assert extra_keys <= row.keys()

    assert (
        collection_frontend._collection_mutation_descriptor(
            _function_call("math", "max", _arg(_literal(1, "int"))),
            symbols=None,
            context=(),
            profile=profile,
        )
        is None
    )


def test_fallback_collection_mutations_cover_method_forms(
    fallback_environment: tuple[Any, _Engine],
) -> None:
    profile, _engine = fallback_environment
    cases = [
        (_method_call("a", "push", _arg(_literal(1.0, "float"))), "push", {"value"}),
        (_method_call("a", "unshift", _arg(_literal(2.0, "float"))), "unshift", {"value"}),
        (
            _method_call("a", "set", _arg(_literal(0, "int")), _arg(_literal(3.0, "float"))),
            "set",
            {"index", "value"},
        ),
        (
            _method_call(
                "mat",
                "set",
                _arg(_literal(0, "int")),
                _arg(_literal(1, "int")),
                _arg(_literal(4.0, "float")),
            ),
            "set",
            {"row", "column", "value"},
        ),
        (
            _method_call("m", "put", _arg(_literal("k", "string")), _arg(_literal(5.0, "float"))),
            "put",
            {"key", "value"},
        ),
        (_method_call("m", "remove", _arg(_literal("k", "string"))), "remove", {"key"}),
        (_method_call("a", "clear"), "clear", set()),
        (_method_call("m", "clear"), "clear", set()),
        (_method_call("mat", "clear"), "clear", set()),
    ]
    for call, operation, extra_keys in cases:
        row = collection_frontend._collection_mutation_descriptor(
            call, symbols=None, context=(), profile=profile
        )
        assert row is not None
        assert row["operation"] == operation
        if row["function_form"] is not None:
            assert row["function_form"].endswith(f".{operation}")
        else:
            assert call.callee.member == "clear"
        assert row["method_parameters"] or not call.arguments
        assert extra_keys <= row.keys()


def test_fallback_collection_accesses_cover_function_forms(
    fallback_environment: tuple[Any, _Engine],
) -> None:
    profile, engine = fallback_environment
    cases = [
        (
            _function_call("array", "get", _arg(_identifier("a")), _arg(_literal(0, "int"))),
            "get",
            {"index"},
        ),
        (_function_call("array", "first", _arg(_identifier("a"))), "first", set()),
        (_function_call("array", "last", _arg(_identifier("a"))), "last", set()),
        (_function_call("array", "size", _arg(_identifier("a"))), "size", set()),
        (_function_call("array", "copy", _arg(_identifier("a"))), "copy", set()),
        (
            _function_call(
                "array", "includes", _arg(_identifier("a")), _arg(_literal(1.0, "float"))
            ),
            "includes",
            {"value"},
        ),
        (
            _function_call(
                "array", "indexof", _arg(_identifier("a")), _arg(_literal(1.0, "float"))
            ),
            "indexof",
            {"value"},
        ),
        (
            _function_call(
                "matrix",
                "get",
                _arg(_identifier("mat")),
                _arg(_literal(0, "int")),
                _arg(_literal(1, "int")),
            ),
            "get",
            {"row", "column"},
        ),
        (_function_call("matrix", "rows", _arg(_identifier("mat"))), "rows", set()),
        (_function_call("matrix", "columns", _arg(_identifier("mat"))), "columns", set()),
        (_function_call("matrix", "copy", _arg(_identifier("mat"))), "copy", set()),
        (
            _function_call("map", "get", _arg(_identifier("m")), _arg(_literal("k", "string"))),
            "get",
            {"key"},
        ),
        (
            _function_call(
                "map", "contains", _arg(_identifier("m")), _arg(_literal("k", "string"))
            ),
            "contains",
            {"key"},
        ),
        (
            _function_call("map", "remove", _arg(_identifier("m")), _arg(_literal("k", "string"))),
            "remove",
            {"key"},
        ),
        (_function_call("map", "keys", _arg(_identifier("m"))), "keys", set()),
        (_function_call("map", "values", _arg(_identifier("m"))), "values", set()),
        (_function_call("map", "size", _arg(_identifier("m"))), "size", set()),
        (_function_call("map", "copy", _arg(_identifier("m"))), "copy", set()),
    ]
    for index, (call, operation, extra_keys) in enumerate(cases):
        engine.call_result = "int" if index == 0 else "unknown"
        row = collection_frontend._collection_access_descriptor(
            call, symbols=None, context=("if",), profile=profile
        )
        assert row is not None
        assert row["operation"] == operation
        assert row["result_type"] != "unknown"
        assert extra_keys <= row.keys()

    assert (
        collection_frontend._collection_access_descriptor(
            _function_call("math", "max", _arg(_literal(1, "int"))),
            symbols=None,
            context=(),
            profile=profile,
        )
        is None
    )


def test_fallback_collection_accesses_cover_method_forms(
    fallback_environment: tuple[Any, _Engine],
) -> None:
    profile, engine = fallback_environment
    engine.call_result = "unknown"
    cases = [
        (_method_call("a", "get", _arg(_literal(0, "int"))), "get", {"index"}),
        (_method_call("a", "first"), "first", set()),
        (_method_call("a", "last"), "last", set()),
        (_method_call("a", "size"), "size", set()),
        (_method_call("a", "copy"), "copy", set()),
        (_method_call("a", "includes", _arg(_literal(1.0, "float"))), "includes", {"value"}),
        (_method_call("a", "indexof", _arg(_literal(1.0, "float"))), "indexof", {"value"}),
        (
            _method_call("mat", "get", _arg(_literal(0, "int")), _arg(_literal(1, "int"))),
            "get",
            {"row", "column"},
        ),
        (_method_call("mat", "rows"), "rows", set()),
        (_method_call("mat", "columns"), "columns", set()),
        (_method_call("mat", "copy"), "copy", set()),
        (_method_call("m", "get", _arg(_literal("k", "string"))), "get", {"key"}),
        (_method_call("m", "contains", _arg(_literal("k", "string"))), "contains", {"key"}),
        (_method_call("m", "remove", _arg(_literal("k", "string"))), "remove", {"key"}),
        (_method_call("m", "keys"), "keys", set()),
        (_method_call("m", "values"), "values", set()),
        (_method_call("m", "size"), "size", set()),
        (_method_call("m", "copy"), "copy", set()),
    ]
    for call, operation, extra_keys in cases:
        row = collection_frontend._collection_access_descriptor(
            call, symbols=None, context=(), profile=profile
        )
        assert row is not None
        assert row["operation"] == operation
        assert row["function_form"].endswith(f".{operation}")
        assert extra_keys <= row.keys()


def test_resolved_collection_descriptor_covers_roles_and_invalid_target(
    fallback_environment: tuple[Any, _Engine], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile, engine = fallback_environment
    args = [
        _arg(_literal("k", "string")),
        _arg(_literal(0, "int")),
        _arg(_literal(1, "int")),
        _arg(_literal(2, "int")),
        _arg(_literal(3.0, "float")),
    ]
    parameters = tuple(
        CollectionParameterSpec(name, type_name, role)
        for name, type_name, role in [
            ("key", "string", "key"),
            ("index", "int", "index"),
            ("row", "int", "row"),
            ("column", "int", "column"),
            ("value", "float", "value"),
        ]
    )
    bindings = tuple(
        CollectionArgumentBinding(arg, param, index, "positional", engine.infer_type(arg.value))
        for index, (arg, param) in enumerate(zip(args, parameters))
    )
    resolution = CollectionCallResolution(
        operation="put",
        function_form="map.put",
        form="method",
        collection_kind="map",
        receiver_type="map<string,float>",
        parameters=parameters,
        bindings=bindings,
        return_type="float",
    )
    call = _method_call("m", "put", *args)
    row = collection_frontend._collection_descriptor_from_resolution(
        call,
        resolution,
        symbols=None,
        context=("method",),
        profile=profile,
        include_result=True,
    )
    assert row is not None
    assert {"key", "index", "row", "column", "value"} <= row.keys()
    assert row["result_type"] == "float"

    invalid = SimpleNamespace(form="unknown", bindings=(), parameters=())
    assert (
        collection_frontend._collection_descriptor_from_resolution(
            call,
            invalid,
            symbols=None,
            context=(),
            profile=profile,
            include_result=False,
        )
        is None
    )
