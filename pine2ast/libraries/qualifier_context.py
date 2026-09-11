"""Reproducible, bounded provenance for projected exported function results.

This is derived evidence, not caller-supplied qualifier authority. Admission
relinks pinned original sources and compares the entire receipt and declaration
inventory. It never guesses provenance from generated identifier spellings.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, NoReturn

from pine2ast.api import ParseOptions, ParsePipeline
from pine2ast.ast.nodes import FunctionDeclaration, MethodDeclaration, Program
from pine2ast.ast.serialize import ast_to_dict
from .linker import LinkedSource, _parse, link_libraries
from .store import (
    LibraryError,
    LibraryStore,
    MAX_LIBRARIES,
    MAX_SOURCE_BYTES,
    MAX_TOTAL_BYTES,
    canonical,
    source_hash,
    strict_json,
)

CONTEXT_SCHEMA = "pine2ast.library_qualifier_context.v1"
CONTEXT_CAPABILITY = "library_qualifier_context_v1"
METHOD_CONTEXT_SCHEMA = "pine2ast.library_qualifier_context.v2"
METHOD_CONTEXT_CAPABILITY = "library_method_projection_v1"
MAX_CONTEXT_BYTES = 64_000_000
MAX_CONTEXT_NODES = 500_000
MAX_CONTEXT_DEPTH = 16


def _fail(message: str) -> NoReturn:
    raise LibraryError("P2A_LIBRARY_QUALIFIER_CONTEXT", message)


def _bounded(value: object) -> None:
    """Check size, depth and cycles before canonical serialization or relinking."""
    stack = [(value, 0, False)]
    active: set[int] = set()
    count = size = 0
    while stack:
        node, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(node))
            continue
        count += 1
        if depth > MAX_CONTEXT_DEPTH or count > MAX_CONTEXT_NODES:
            _fail("context structural limit exceeded")
        if isinstance(node, str):
            size += len(node.encode("utf-8"))
        elif isinstance(node, (dict, list)):
            if len(node) > MAX_CONTEXT_NODES:
                _fail("context container limit exceeded")
            if id(node) in active:
                _fail("cyclic context")
            active.add(id(node))
            stack.append((node, depth, True))
            values = list(node.items()) if isinstance(node, dict) else enumerate(node)
            for key, item in values:
                if isinstance(node, dict):
                    if not isinstance(key, str):
                        _fail("context keys must be strings")
                    size += len(key.encode("utf-8"))
                stack.append((item, depth + 1, False))
        elif isinstance(node, float):
            if not math.isfinite(node):
                _fail("context must contain finite JSON numbers")
        elif node is not None and type(node) not in {int, bool}:
            _fail("context must contain JSON values")
        if size > MAX_CONTEXT_BYTES:
            _fail("context byte limit exceeded")


def _decode(data: bytes) -> dict[str, Any]:
    if type(data) is not bytes or len(data) > MAX_CONTEXT_BYTES:
        _fail("context JSON byte limit exceeded or invalid representation")
    try:
        payload = strict_json(data)
        _bounded(payload)
    except LibraryError as exc:
        raise LibraryError(
            "P2A_LIBRARY_QUALIFIER_CONTEXT", f"invalid context UTF-8 JSON: {exc}"
        ) from exc
    return payload


def _span(node: FunctionDeclaration | MethodDeclaration) -> dict[str, int]:
    return {"start_offset": node.span.start_offset, "end_offset": node.span.end_offset}


def _syntax(code: str) -> Program:
    pipeline = ParsePipeline(ParseOptions(run_semantic=False, created_at_utc_ms=0))
    tokens, diagnostics = pipeline.lex_only(code)
    resolution = pipeline.resolve_version(pipeline.normalize(code).text)
    if resolution.context is None or any(d.is_error for d in diagnostics):
        _fail("projected source must produce clean syntax")
    parsed = pipeline.parse_only(tokens, version_context=resolution.context)
    if parsed.program is None or any(d.is_error for d in parsed.diagnostics):
        _fail("projected source must produce clean syntax")
    return parsed.program


def _payload(linked: LinkedSource) -> dict[str, Any]:
    receipt = linked.receipt()
    generated = {}
    for node in _syntax(linked.code).items:
        if isinstance(node, (FunctionDeclaration, MethodDeclaration)):
            generated.setdefault((type(node), node.name), []).append(node)
    originals = {
        ref: _parse(ref, receipt["sources"][ref]["raw_text"]) for ref in receipt["dependencies"]
    }
    rows = []
    for row in receipt["declarations"]:
        unit = originals[row["ref"]]
        original = unit.functions.get(row["name"]) or unit.methods.get(row["name"])
        if original is None or not original.is_exported:
            continue
        matches = []
        for node in generated.get((type(original), row["linked_name"]), ()):

            location = linked.original_location(node.span.start_offset)
            if (location is not None and location["source"] == row["ref"]
                    and original.span.start_offset <= location["offset"] < original.span.end_offset):
                matches.append(node)
        if len(matches) != 1:
            _fail("exported declaration does not have one exact source projection")
        projected = matches[0]
        rows.append({
            "source": row["ref"],
            "source_hash": receipt["dependencies"][row["ref"]],
            "name": original.name,
            "span": _span(original),
            "generated_name": projected.name,
            "generated_span": _span(projected),
            "minimum_return_qualifier": "simple",
        })
    rows.sort(key=lambda row: row["generated_span"]["start_offset"])
    body = {
        "schema_id": (METHOD_CONTEXT_SCHEMA if receipt["profile"] == "same_version_methods_v5" else CONTEXT_SCHEMA),
        "pine_version": receipt["pine_version"],
        "linked_source_hash": receipt["linked_source_hash"],
        "linkage_receipt_hash": receipt["content_hash"],
        "linkage_receipt": receipt,
        "exported_functions": rows,
    }
    body["content_hash"] = source_hash(canonical(body))
    return body


@dataclass(frozen=True, slots=True)
class LibraryQualifierContext:
    _payload_bytes: bytes
    code: str

    def __post_init__(self) -> None:
        if type(self._payload_bytes) is not bytes or len(self._payload_bytes) > MAX_CONTEXT_BYTES:
            _fail("context byte limit exceeded or invalid representation")
        if not isinstance(self.code, str) or len(self.code.encode("utf-8")) > MAX_SOURCE_BYTES:
            _fail("context source size exceeded or invalid representation")

    @classmethod
    def from_linked_source(cls, linked: LinkedSource) -> LibraryQualifierContext:
        if not isinstance(linked, LinkedSource):
            _fail("LinkedSource is required")
        # Bound hostile manually-constructed receipts before the existing verifier.
        receipt = _decode(linked._receipt)
        if canonical(receipt) != linked._receipt:
            _fail("receipt bytes must be canonical")
        return cls.admit(_payload_after_rebuild(receipt, linked.code))

    @classmethod
    def admit(cls, payload: Mapping[str, Any]) -> LibraryQualifierContext:
        _bounded(payload)
        if not isinstance(payload, dict) or payload.get("schema_id") not in {CONTEXT_SCHEMA, METHOD_CONTEXT_SCHEMA}:
            _fail("unsupported context schema")
        if type(payload.get("pine_version")) is not int or payload["pine_version"] not in {5, 6}:
            _fail("context requires Pine v5 or v6")
        linked = _rebuild(payload.get("linkage_receipt"))
        expected = _payload(linked)
        if canonical(payload) != canonical(expected):
            _fail("context differs from all and only projected exported declarations")
        return cls(canonical(expected), linked.code)

    def to_dict(self) -> dict[str, Any]:
        return _decode(self._payload_bytes)

    def declaration_ids(self, program: Program) -> frozenset[int]:
        # Even a manually constructed instance cannot supply unverified floors.
        verified = LibraryQualifierContext.admit(self.to_dict())
        if self.code != verified.code:
            _fail("context code differs from reconstructed source")
        syntax = _syntax(verified.code)
        if canonical(ast_to_dict(program)) != canonical(ast_to_dict(syntax)):
            _fail("context requires the exact projected syntax AST")
        keys = {
            (
                row["generated_name"],
                row["generated_span"]["start_offset"],
                row["generated_span"]["end_offset"],
            )
            for row in verified.to_dict()["exported_functions"]
        }
        return frozenset(
            id(node)
            for node in program.items
            if isinstance(node, (FunctionDeclaration, MethodDeclaration))
            and (node.name, node.span.start_offset, node.span.end_offset) in keys
        )


def _rebuild(receipt: object) -> LinkedSource:
    _bounded(receipt)
    if not isinstance(receipt, dict):
        _fail("linkage receipt must be an object")
    try:
        root_name = receipt["root_source_name"]
        sources = receipt["sources"]
        dependencies = receipt["dependencies"]
        if (
            not isinstance(root_name, str)
            or not isinstance(sources, dict)
            or not isinstance(dependencies, dict)
        ):
            _fail("invalid receipt source inventory")
        if not 1 <= len(dependencies) <= MAX_LIBRARIES or len(sources) != len(dependencies) + 1:
            _fail("receipt source count exceeded or inconsistent")
        root = sources[root_name]["raw_text"]
        if not isinstance(root, str) or len(root.encode("utf-8")) > MAX_SOURCE_BYTES:
            _fail("root source size exceeded")
        originals = {ref: sources[ref]["raw_text"] for ref in dependencies}
        if any(not isinstance(text, str) for text in originals.values()):
            _fail("library sources must be text")
        if sum(len(text.encode("utf-8")) for text in originals.values()) > MAX_TOTAL_BYTES:
            _fail("library source aggregate size exceeded")
        rebuilt = link_libraries(root, LibraryStore.create(originals), source_name=root_name)
    except (KeyError, TypeError) as exc:
        raise LibraryError(
            "P2A_LIBRARY_QUALIFIER_CONTEXT", "incomplete linkage provenance"
        ) from exc
    if rebuilt._receipt != canonical(receipt):
        _fail("linkage differs from pinned original sources")
    return rebuilt


def _payload_after_rebuild(receipt: object, code: str) -> dict[str, Any]:
    rebuilt = _rebuild(receipt)
    if rebuilt.code != code:
        _fail("linked source differs from reconstructed source")
    return _payload(rebuilt)
