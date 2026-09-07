"""AST-anchored static linking of same-language Pine libraries.

Only resolved identifier occurrences are edited, never arbitrary source strings.
The linked virtual source is parsed and type-checked again by the normal frontend.
Original inputs and projection ranges remain available in the linkage receipt.

This revision admits scalar and array-of-scalar functions, helpers and constant globals.
Mixed Pine versions, exported user-defined types/methods and request expressions in
libraries are rejected explicitly, not silently executed with importer semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import json
from typing import Mapping

from pine2ast.api import ParseOptions, ParsePipeline
from pine2ast.ast.base import ASTNode
from pine2ast.ast.nodes import (
    Block,
    CallExpr,
    EnumDeclaration,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    Identifier,
    ImportDeclaration,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Program,
    Reassignment,
    TupleDeclaration,
    TypeDeclaration,
    VarDeclaration,
)
from pine2ast.ast.visitors import walk
from pine2ast.catalog import CatalogRepository
from pine2ast.lexer.token import TokenKind
from .store import (
    LibraryError,
    LibraryStore,
    MAX_DEPTH,
    MAX_SOURCE_BYTES,
    canonical,
    source_hash,
    valid_ref,
)

PREFIX = "__p2a_library_"
SCALARS = {"int", "float", "bool", "string", "color"}
LINK_SCHEMA = "pine2ast.linked_libraries.v1"


@dataclass(frozen=True, slots=True)
class LinkedSource:
    code: str
    _receipt: bytes

    def receipt(self) -> dict:
        value = json.loads(self._receipt)
        body = {k: v for k, v in value.items() if k != "content_hash"}
        if (
            source_hash(canonical(body)) != value["content_hash"]
            or source_hash(self.code) != value["linked_source_hash"]
        ):
            raise LibraryError("P2A_LIBRARY_PROJECTION", "linked source or projection was changed")
        return value

    def verify(self) -> None:
        """Reproduce the complete projection; a self-rehashed receipt is not proof."""
        value = self.receipt()
        if value.get("schema_id") != LINK_SCHEMA or value.get("profile") not in {
            "same_version_scalar_v1",
            "same_version_arrays_v2",
        }:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "unsupported linkage profile")
        root_name = value.get("root_source_name")
        try:
            root = value["sources"][root_name]["raw_text"]
            sources = {ref: value["sources"][ref]["raw_text"] for ref in value["dependencies"]}
            if sources:
                rebuilt = link_libraries(root, LibraryStore.create(sources), source_name=root_name)
            else:
                raise LibraryError("P2A_LIBRARY_PROJECTION", "linked source needs dependencies")
        except (KeyError, TypeError) as exc:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "incomplete linkage provenance") from exc
        if rebuilt.code != self.code or rebuilt._receipt != self._receipt:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "linkage differs from original sources")

    @property
    def dependency_hashes(self) -> dict[str, str]:
        return dict(self.receipt()["dependencies"])

    def original_location(self, offset: int) -> dict | None:
        """Project a virtual character offset back to its original file and line."""
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        receipt = self.receipt()
        for row in receipt["projection"]:
            if row["generated_start"] <= offset < row["generated_end"]:
                # Renamed tokens project to their original token; untouched chunks
                # have equal length and preserve exact character offsets.
                original_length = row["source_end"] - row["source_start"]
                generated_length = row["generated_end"] - row["generated_start"]
                delta = (
                    offset - row["generated_start"] if original_length == generated_length else 0
                )
                original = row["source_start"] + delta
                text = receipt["sources"][row["source"]]["text"]
                return {
                    "source": row["source"],
                    "offset": original,
                    "line": text.count("\n", 0, original) + 1,
                    "column": original - text.rfind("\n", 0, original),
                }
        return None


@dataclass(slots=True)
class _Unit:
    ref: str
    text: str
    program: Program
    tokens: list
    imports: dict[str, str]
    functions: dict[str, FunctionDeclaration]
    constants: dict[str, VarDeclaration]
    globals: set[str]
    exports: set[str]
    renamed: dict[str, str]


def _parse(ref: str, text: str) -> _Unit:
    options = ParseOptions(
        source_name=ref, run_semantic=False, collect_tokens=True, created_at_utc_ms=0
    )
    pipeline = ParsePipeline(options)
    normalized = pipeline.normalize(text)
    result = pipeline.parse(normalized.text)
    if not result.ok or result.ast is None:
        detail = "; ".join(d.message for d in result.diagnostics if d.is_error)
        raise LibraryError("P2A_LIBRARY_SYNTAX", detail, source=ref, line=1)
    program = result.ast
    declarations, functions, constants, exports, imports = set(), {}, {}, set(), {}
    for item in program.items:
        if isinstance(item, ImportDeclaration):
            path = valid_ref(item.path)
            alias = item.alias or item.library
            if not alias or alias in imports or alias in declarations:
                raise LibraryError(
                    "P2A_LIBRARY_ALIAS",
                    "duplicate or invalid import alias",
                    source=ref,
                    line=item.span.start_line,
                )
            imports[alias] = path
        elif isinstance(
            item,
            (
                FunctionDeclaration,
                MethodDeclaration,
                VarDeclaration,
                TypeDeclaration,
                EnumDeclaration,
            ),
        ):
            if item.name in declarations or item.name in imports:
                raise LibraryError(
                    "P2A_LIBRARY_NAME",
                    "duplicate module-level name",
                    source=ref,
                    line=item.span.start_line,
                )
            declarations.add(item.name)
            if getattr(item, "is_exported", False):
                exports.add(item.name)
            if isinstance(item, FunctionDeclaration):
                functions[item.name] = item
            elif isinstance(item, VarDeclaration):
                constants[item.name] = item
        elif isinstance(item, TupleDeclaration):
            for target in item.targets:
                if target.name != "_":
                    declarations.add(target.name)
    # Aliases may not overwrite existing builtin namespaces or declaration names.
    catalog = CatalogRepository.default().readonly_view(program.version_context.pine_version)
    namespaces = {
        name.split(".")[0]
        for cat in catalog.values()
        if isinstance(cat, Mapping)
        for name in cat
        if isinstance(name, str) and "." in name
    }
    if set(imports) & namespaces:
        raise LibraryError(
            "P2A_LIBRARY_ALIAS", "import alias conflicts with a builtin namespace", source=ref
        )
    for node in walk(program):
        name = getattr(node, "name", None)
        if isinstance(name, str) and name.startswith(PREFIX):
            raise LibraryError(
                "P2A_LIBRARY_RESERVED",
                "reserved linker identifier",
                source=ref,
                line=node.span.start_line,
            )
        if isinstance(node, ImportDeclaration) and node not in program.items:
            raise LibraryError(
                "P2A_LIBRARY_IMPORT_SCOPE",
                "imports must be module-level",
                source=ref,
                line=node.span.start_line,
            )
    return _Unit(
        ref,
        normalized.text,
        program,
        result.tokens or [],
        imports,
        functions,
        constants,
        declarations,
        exports,
        {},
    )


class _Linker:
    def __init__(self, root: str, store: LibraryStore, source_name: str):
        self.root = _parse(source_name, root)
        self.root_raw = root
        self.profile = "same_version_scalar_v1"
        self.store = store
        self.units: dict[str, _Unit] = {}
        self.version = self.root.program.version_context.pine_version
        self.selected: set[tuple[str, str]] = set()
        self.visiting: list[tuple[str, str]] = []
        self.order: list[tuple[str, str]] = []
        self.edits: dict[str, dict[tuple[int, int], str]] = {}
        catalog = CatalogRepository.default().readonly_view(self.version)
        self.builtins = {
            name
            for category in catalog.values()
            if isinstance(category, Mapping)
            for name in category
            if isinstance(name, str)
        }
        self.namespaces = {name.split(".")[0] for name in self.builtins if "." in name}

    def fail(self, unit: _Unit, node: ASTNode, code: str, message: str):
        raise LibraryError(code, message, source=unit.ref, line=node.span.start_line)

    def load(self, ref: str, stack: tuple[str, ...] = ()) -> None:
        if ref in stack:
            raise LibraryError("P2A_LIBRARY_CYCLE", " -> ".join((*stack, ref)))
        if len(stack) >= MAX_DEPTH:
            raise LibraryError("P2A_LIBRARY_LIMIT", "dependency depth exceeded")
        if ref in self.units:
            return
        text = self.store.source(ref)
        unit = _parse(ref, text)
        if unit.program.declaration is None or unit.program.declaration.script_type != "library":
            raise LibraryError(
                "P2A_LIBRARY_DECLARATION", "dependency must declare library()", source=ref
            )
        if unit.program.version_context.pine_version != self.version:
            raise LibraryError(
                "P2A_LIBRARY_VERSION_CONTEXT",
                "mixed Pine-language versions need separate evaluation; not admitted by this linker",
                source=ref,
            )
        call = unit.program.declaration.call
        title = next(
            (a.value for a in call.arguments if a.name == "title"),
            call.arguments[0].value if call.arguments else None,
        )
        if (
            not isinstance(title, Literal)
            or title.literal_type != "string"
            or title.value != ref.split("/")[1]
        ):
            raise LibraryError(
                "P2A_LIBRARY_TITLE",
                "library title must match the locked publication name",
                source=ref,
            )
        if not unit.exports:
            raise LibraryError(
                "P2A_LIBRARY_EXPORT", "library must export at least one declaration", source=ref
            )
        if unit.exports - set(unit.functions):
            raise LibraryError(
                "P2A_LIBRARY_EXPORT_SHAPE",
                "this link profile supports scalar function exports only",
                source=ref,
            )
        for name in unit.exports:
            function = unit.functions[name]
            for parameter in function.parameters:
                if (
                    parameter.type_ref is None
                    or not (
                        parameter.type_ref.name in SCALARS
                        or (
                            parameter.type_ref.name == "array"
                            and len(parameter.type_ref.template_args) == 1
                            and parameter.type_ref.template_args[0].name in SCALARS
                            and not parameter.type_ref.template_args[0].template_args
                            and parameter.explicit_qualifier != "simple"
                        )
                    )
                    or parameter.explicit_qualifier not in {None, "simple", "series"}
                ):
                    self.fail(
                        unit,
                        parameter,
                        "P2A_LIBRARY_PARAMETER",
                        "export requires a declared scalar or series array-of-scalar parameter",
                    )
                if parameter.type_ref.name == "array":
                    self.profile = "same_version_arrays_v2"
        unit.renamed = {
            name: PREFIX + source_hash((ref + "\0" + text))[7:27] + "_" + name
            for name in unit.functions | unit.constants
        }
        # Resolve every declared edge, even when calls under it are not selected.
        self.units[ref] = unit
        for child in sorted(set(unit.imports.values())):
            self.load(child, (*stack, ref))

    def edit(self, unit: _Unit, start: int, end: int, text: str) -> None:
        edits = self.edits.setdefault(unit.ref, {})
        key = (start, end)
        if key in edits and edits[key] != text:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "conflicting identifier projection")
        edits[key] = text

    def name_edit(self, unit: _Unit, node: ASTNode, name: str) -> None:
        # Declaration names are not Identifier AST children; bind the exact lexer
        # token before its parameter list / initializer, never global replace().
        until = (
            node.initializer.span.start_offset
            if isinstance(node, VarDeclaration)
            else node.span.end_offset
        )
        matches = [
            t
            for t in unit.tokens
            if t.kind == TokenKind.IDENTIFIER
            and t.text == name
            and node.span.start_offset <= t.span.start_offset < until
        ]
        if not matches:
            self.fail(unit, node, "P2A_LIBRARY_PROJECTION", "declaration token not found")
        token = matches[0]
        self.edit(unit, token.span.start_offset, token.span.end_offset, unit.renamed[name])

    def require(self, ref: str, name: str, *, public: bool = False) -> None:
        unit = self.units[ref]
        if public and name not in unit.exports:
            raise LibraryError(
                "P2A_LIBRARY_PRIVATE", "imported member is not exported: " + name, source=ref
            )
        key = (ref, name)
        if key in self.visiting:
            raise LibraryError(
                "P2A_LIBRARY_RECURSION", "recursive function/constant dependency", source=ref
            )
        if key in self.selected:
            return
        declaration = unit.functions.get(name) or unit.constants.get(name)
        if declaration is None:
            raise LibraryError(
                "P2A_LIBRARY_MEMBER", "unresolved library member: " + name, source=ref
            )
        self.visiting.append(key)
        if isinstance(declaration, VarDeclaration):
            if declaration.mode or declaration.explicit_qualifier not in {None, "const"}:
                self.fail(
                    unit,
                    declaration,
                    "P2A_LIBRARY_CAPTURE",
                    "library function cannot capture a non-const global",
                )
            if any(
                isinstance(n, Reassignment)
                and isinstance(n.target, Identifier)
                and n.target.name == name
                for item in unit.program.items
                if not isinstance(item, (FunctionDeclaration, MethodDeclaration))
                for n in walk(item)
            ):
                self.fail(unit, declaration, "P2A_LIBRARY_CAPTURE", "global constant is reassigned")
            # Admit only syntax known to be a scalar constant, not parent-scope data.
            allowed = {"Literal", "Identifier", "UnaryExpr", "BinaryExpr", "ConditionalExpr"}
            if any(n.kind not in allowed for n in walk(declaration.initializer)):
                self.fail(
                    unit,
                    declaration,
                    "P2A_LIBRARY_CAPTURE",
                    "global initializer is not a supported constant expression",
                )
            self.visit(unit, declaration.initializer, [], constant_only=True)
        else:
            self.visit_function(unit, declaration)
        self.name_edit(unit, declaration, name)
        self.visiting.pop()
        self.selected.add(key)
        self.order.append(key)

    def visit_function(self, unit: _Unit, function: FunctionDeclaration) -> None:
        for parameter in function.parameters:
            if parameter.default_value is not None:
                self.visit(unit, parameter.default_value, [])
        self.visit(unit, function.body, [set(p.name for p in function.parameters)])

    def visit(
        self, unit: _Unit, node: ASTNode, scopes: list[set[str]], *, constant_only: bool = False
    ) -> None:
        def local(name):
            return any(name in s for s in reversed(scopes))

        if isinstance(node, MemberAccessExpr):
            if isinstance(node.object, Identifier) and not local(node.object.name):
                alias = node.object.name
                if alias in unit.imports:
                    if constant_only:
                        self.fail(
                            unit,
                            node,
                            "P2A_LIBRARY_CAPTURE",
                            "library call is not a constant initializer",
                        )
                    target = self.units[unit.imports[alias]]
                    self.require(target.ref, node.member, public=True)
                    self.edit(
                        unit,
                        node.span.start_offset,
                        node.span.end_offset,
                        target.renamed[node.member],
                    )
                    return
            if constant_only:
                self.fail(
                    unit,
                    node,
                    "P2A_LIBRARY_CAPTURE",
                    "only literal/arithmetic constant globals are admitted",
                )
        if isinstance(node, Identifier):
            name = node.name
            if local(name):
                return
            if name in unit.imports:
                self.fail(
                    unit,
                    node,
                    "P2A_LIBRARY_ALIAS_VALUE",
                    "library alias must qualify an exported function",
                )
            if unit is not self.root:
                if name in unit.globals:
                    if constant_only and name not in unit.constants:
                        self.fail(unit, node, "P2A_LIBRARY_CAPTURE", "not a scalar constant")
                    self.require(unit.ref, name)
                    self.edit(
                        unit, node.span.start_offset, node.span.end_offset, unit.renamed[name]
                    )
                elif constant_only or (name not in self.builtins and name not in self.namespaces):
                    self.fail(
                        unit, node, "P2A_LIBRARY_UNBOUND", "unresolved library identifier: " + name
                    )
            return
        if isinstance(node, CallExpr) and unit is not self.root:
            from pine2ast.semantic.type_infer import callee_name

            name = callee_name(node.callee) or ""
            if name.startswith("array."):
                self.profile = "same_version_arrays_v2"
            if (
                name == "input"
                or name.startswith(("input.", "request.", "strategy."))
                or name == "security"
            ):
                self.fail(
                    unit,
                    node,
                    "P2A_LIBRARY_CALL_PROFILE",
                    "unsupported call in imported function: " + name,
                )
            if name in {
                "plot",
                "plotshape",
                "plotchar",
                "hline",
                "fill",
                "indicator",
                "strategy",
                "library",
                "alertcondition",
            }:
                self.fail(
                    unit,
                    node,
                    "P2A_LIBRARY_LOCAL_CALL",
                    "global-only call inside imported function",
                )
        if isinstance(node, Block):
            scope = set()
            for statement in node.statements:
                self.visit(unit, statement, [*scopes, scope], constant_only=constant_only)
                if isinstance(statement, VarDeclaration):
                    scope.add(statement.name)
                elif isinstance(statement, TupleDeclaration):
                    scope.update(t.name for t in statement.targets)
            return
        if isinstance(node, FunctionDeclaration):
            self.visit_function(unit, node)
            return
        if isinstance(node, ForRangeStructure):
            for field in fields(node):
                value = getattr(node, field.name)
                if isinstance(value, ASTNode):
                    self.visit(
                        unit, value, [*scopes, {node.variable}] if field.name == "body" else scopes
                    )
            return
        if isinstance(node, ForInStructure):
            if unit is not self.root:
                self.profile = "same_version_arrays_v2"
            self.visit(unit, node.iterable, scopes)
            self.visit(unit, node.body, [*scopes, set(node.target.names)])
            return
        if isinstance(node, Reassignment) and unit is not self.root:
            if isinstance(node.target, Identifier) and not local(node.target.name):
                self.fail(
                    unit,
                    node,
                    "P2A_LIBRARY_CAPTURE",
                    "cannot reassign a library global from a function",
                )
        for field in fields(node):
            if field.name in {
                "span",
                "documentation",
                "type_ref",
                "annotations",
                "producer_metadata",
                "diagnostics",
            }:
                continue
            value = getattr(node, field.name)
            if isinstance(value, ASTNode):
                self.visit(unit, value, scopes, constant_only=constant_only)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, ASTNode):
                        self.visit(unit, child, scopes, constant_only=constant_only)

    def run(self) -> LinkedSource:
        if self.version not in {5, 6}:
            raise LibraryError("P2A_LIBRARY_VERSION", "library imports require Pine v5 or v6")
        if self.root.program.declaration is None:
            raise LibraryError("P2A_LIBRARY_DECLARATION", "consumer must have a script declaration")
        for ref in sorted(set(self.root.imports.values())):
            self.load(ref)
        for item in self.root.program.items:
            if isinstance(item, ImportDeclaration):
                self.edit(self.root, item.span.start_offset, item.span.end_offset, "")
            else:
                self.visit(self.root, item, [])
        closure = {ref: source_hash(self.store.source(ref)) for ref in sorted(self.units)}
        identity = source_hash(
            canonical(
                {
                    "profile": self.profile,
                    "root": source_hash(self.root_raw),
                    "libraries": closure,
                }
            )
        )
        code, projection = [], []
        length = 0

        def literal(text):
            nonlocal length
            code.append(text)
            length += len(text)

        def chunk(unit, start, end):
            nonlocal length
            cursor = start
            edits = sorted(
                (a, b, v)
                for (a, b), v in self.edits.get(unit.ref, {}).items()
                if start <= a and b <= end
            )
            for a, b, replacement in [*edits, (end, end, "")]:
                if a < cursor:
                    raise LibraryError("P2A_LIBRARY_PROJECTION", "overlapping identifier ranges")
                for original_start, original_end, text in (
                    (cursor, a, unit.text[cursor:a]),
                    (a, b, replacement),
                ):
                    if text:
                        projection.append(
                            {
                                "generated_start": length,
                                "generated_end": length + len(text),
                                "source": unit.ref,
                                "source_start": original_start,
                                "source_end": original_end,
                            }
                        )
                        literal(text)
                cursor = b

        end = self.root.program.declaration.span.end_offset
        chunk(self.root, 0, end)
        literal("\n// openpine-library-link: " + identity + "\n")
        for ref, name in self.order:
            unit = self.units[ref]
            item = unit.functions.get(name) or unit.constants[name]
            chunk(unit, item.span.start_offset, item.span.end_offset)
            literal("\n")
        chunk(self.root, end, len(self.root.text))
        joined = "".join(code)
        if len(joined.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise LibraryError("P2A_LIBRARY_LIMIT", "linked source exceeds size limit")
        sources = {
            u.ref: {
                "text": u.text,
                "sha256": source_hash(u.text),
                "raw_text": self.root_raw if u is self.root else self.store.source(u.ref),
            }
            for u in [self.root, *self.units.values()]
        }
        receipt = {
            "schema_id": LINK_SCHEMA,
            "profile": self.profile,
            "pine_version": self.version,
            "root_source_name": self.root.ref,
            "root_source_hash": source_hash(self.root_raw),
            "linked_source_hash": source_hash(joined),
            "closure_hash": identity,
            "dependencies": closure,
            "sources": sources,
            "projection": projection,
            "declarations": [
                {"ref": r, "name": n, "linked_name": self.units[r].renamed[n]}
                for r, n in self.order
            ],
        }
        receipt["content_hash"] = source_hash(canonical(receipt))
        return LinkedSource(joined, canonical(receipt))


def link_libraries(
    source: str, store: LibraryStore, *, source_name: str = "<memory>"
) -> LinkedSource:
    """Resolve exact revisions and perform lexical module lowering before type admission."""
    if not isinstance(store, LibraryStore):
        raise LibraryError("P2A_LIBRARY_LOCK", "an admitted LibraryStore is required")
    # Even a manually constructed dataclass cannot bypass admission or retain mutable inputs.
    detached = LibraryStore.admit(store.lock(), store._sources, expected_hash=store.content_hash)
    if source_name in detached._sources:
        raise LibraryError("P2A_LIBRARY_SOURCE", "root source name collides with a library ref")
    return _Linker(source, detached, source_name).run()


def has_library_imports(source: str, *, source_name: str = "<memory>") -> bool:
    """Lexical dispatch only; import text in strings/comments is not a declaration."""
    tokens, _ = ParsePipeline(ParseOptions(source_name=source_name)).lex_only(source)
    return any(token.kind == TokenKind.IMPORT for token in tokens)
