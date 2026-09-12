"""Source-scoped callable projection using the ordinary semantic binding owners.

A temporary typed view retains original function/method names for overload selection.
Only selected member tokens and declarations are then alpha-renamed. No method
body, receiver expression, argument order or runtime semantics are synthesized.
The complete source projection is rebuilt during normal library admission.
"""

from __future__ import annotations

from bisect import bisect_right

from pine2ast.api import ParseOptions, ParsePipeline
from pine2ast.ast.nodes import CallExpr, FunctionDeclaration, Identifier, MemberAccessExpr, MethodDeclaration
from pine2ast.ast.visitors import walk
from .store import LibraryError


class _Visibility:
    def __init__(self, linker, projection: list[dict]):
        self.linker = linker
        self.projection = projection
        self.starts = [r["generated_start"] for r in projection]
        self.units = {linker.root.ref: linker.root, **linker.units}
        self.method_rows = {
            ref: sorted(
                ((node.span.start_offset, key, node) for key, node in (unit.methods | unit.functions).items()),
                key=lambda row: row[0],
            )
            for ref, unit in self.units.items()
        }
        self.method_starts = {
            ref: [row[0] for row in rows] for ref, rows in self.method_rows.items()
        }
        self.declarations = {}

    def location(self, offset: int) -> tuple[str, int]:
        i = bisect_right(self.starts, offset) - 1
        if i < 0:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "method node has no source origin")
        row = self.projection[i]
        if not row["generated_start"] <= offset < row["generated_end"]:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "method node is outside source ranges")
        same = (
            row["generated_end"] - row["generated_start"] == row["source_end"] - row["source_start"]
        )
        return row["source"], row["source_start"] + (offset - row["generated_start"] if same else 0)

    def origin(self, node) -> str:
        return self.location(node.span.start_offset)[0]

    def declaration(self, node: FunctionDeclaration | MethodDeclaration):
        cached = self.declarations.get(id(node))
        if cached is not None:
            return cached
        ref, offset = self.location(node.span.start_offset)
        i = bisect_right(self.method_starts[ref], offset) - 1
        if i >= 0:
            _, key, original = self.method_rows[ref][i]
            if original.span.start_offset <= offset < original.span.end_offset:
                result = self.units[ref], key, original
                self.declarations[id(node)] = result
                return result
        raise LibraryError("P2A_LIBRARY_PROJECTION", "method declaration has no original")

    def explicit_owner(self, call: CallExpr):
        callee = call.callee
        if not (isinstance(callee, MemberAccessExpr) and isinstance(callee.object, Identifier)):
            return None
        ref, start = self.location(callee.span.start_offset)
        end_ref, end = self.location(callee.span.end_offset - 1)
        if ref != end_ref:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "method callee spans multiple sources")
        return self.linker.explicit_method_calls.get((ref, start, end + 1))

    def function_owner(self, call: CallExpr):
        callee = call.callee
        if not (isinstance(callee, MemberAccessExpr) and isinstance(callee.object, Identifier)):
            return None
        ref, start = self.location(callee.span.start_offset)
        end_ref, end = self.location(callee.span.end_offset - 1)
        if ref != end_ref:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "function callee spans multiple sources")
        return self.linker.explicit_function_calls.get((ref, start, end + 1))

    def allows_function(self, call: CallExpr, function: FunctionDeclaration) -> bool:
        caller_ref, call_offset = self.location(call.span.start_offset)
        owner, _, original = self.declaration(function)
        target = self.function_owner(call)
        if target is not None:
            return owner.ref == target and original.is_exported
        return owner.ref == caller_ref and original.span.start_offset <= call_offset

    def allows(self, call: CallExpr, method: MethodDeclaration) -> bool:
        caller = self.units[self.origin(call)]
        owner, _, original = self.declaration(method)
        target = self.explicit_owner(call)
        if target is not None:
            return owner.ref == target and original.is_exported
        # A bare local function-style method call is scoped to its source unit.
        if isinstance(call.callee, Identifier):
            return owner is caller
        return owner is caller or (original.is_exported and owner.ref in caller.imports.values())


def project_methods(linker, code: str, projection: list[dict]) -> None:
    visibility = _Visibility(linker, projection)
    pipeline = ParsePipeline(
        ParseOptions(run_semantic=False, collect_tokens=True, created_at_utc_ms=0)
    )
    parsed = pipeline.parse(code)
    if parsed.ast is None or not parsed.ok:
        raise LibraryError("P2A_LIBRARY_METHOD_BINDING", "method projection must have valid syntax")
    exported = set()
    for node in parsed.ast.items:
        if isinstance(node, MethodDeclaration):
            _, _, original = visibility.declaration(node)
            if original.is_exported:
                exported.add(id(node))
        elif isinstance(node, FunctionDeclaration):
            ref, offset = visibility.location(node.span.start_offset)
            unit = visibility.units[ref]
            if any(
                f.is_exported and f.span.start_offset <= offset < f.span.end_offset
                for f in unit.functions.values()
            ):
                exported.add(id(node))
    # The normal resolver consumes receiver type, argument names and qualifiers.
    # The linker adds visibility only; it does not implement type matching.
    model = pipeline.semantic_only(
        parsed.ast, method_visibility=visibility, projected_exports=frozenset(exported)
    )
    errors = [d for d in model.diagnostics if d.is_error]
    if errors:
        error = errors[0]
        ref, offset = visibility.location(error.span.start_offset)
        unit = visibility.units[ref]
        raise LibraryError(
            "P2A_LIBRARY_METHOD_BINDING",
            error.message,
            source=ref,
            line=unit.text.count("\n", 0, offset) + 1,
            column=offset - unit.text.rfind("\n", 0, offset),
        )
    index = model.function_candidates.index
    calls = {c.node_id: c for c in model.semantic_facts.calls}
    for node in walk(parsed.ast):
        if not isinstance(node, CallExpr) or not isinstance(node.callee, (Identifier, MemberAccessExpr)):
            continue
        fact = calls.get(index.id_for(node))
        if fact is None or fact.call_form not in {"USER_METHOD", "USER_FUNCTION"} or fact.resolution_status != "RESOLVED":
            continue
        if fact.call_form == "USER_FUNCTION":
            candidate = model.function_candidates.by_symbol.get(fact.symbol_id)
            if candidate is None:
                continue
            unit, key, original_declaration = visibility.declaration(candidate.declaration)
            if not key.startswith("@function:"):
                continue
        else:
            candidate = model.method_candidates.by_symbol.get(fact.symbol_id)
        if candidate is None:
            raise LibraryError("P2A_LIBRARY_PROJECTION", "selected method declaration is missing")
        unit, key, _ = visibility.declaration(candidate.declaration)
        if unit is linker.root:
            continue
        explicit = (isinstance(node.callee, Identifier) or visibility.explicit_owner(node) is not None
                    or visibility.function_owner(node) is not None)
        member = (node.callee.name if isinstance(node.callee, Identifier) else node.callee.member)
        start = node.callee.span.start_offset if explicit else node.callee.span.end_offset - len(member)
        ref, original = visibility.location(start)
        caller = visibility.units[ref]
        length = node.callee.span.end_offset - start
        spelling = code[start : node.callee.span.end_offset]
        if caller.text[original : original + length] != spelling:
            raise LibraryError(
                "P2A_LIBRARY_PROJECTION", "selected method token differs from source"
            )
        linker.edit(caller, original, original + length, unit.renamed[key])
    for unit in linker.units.values():
        for key, node in unit.functions.items():
            if key.startswith("@function:"):
                token = next((t for t in unit.tokens
                              if node.span.start_offset <= t.span.start_offset < node.body.span.start_offset
                              and t.text == node.name), None)
                if token is None:
                    raise LibraryError("P2A_LIBRARY_PROJECTION", "function name token is missing")
                linker.edit(unit, token.span.start_offset, token.span.end_offset, unit.renamed[key])
        for key, node in unit.methods.items():
            token = next(
                (
                    t
                    for t in unit.tokens
                    if node.span.start_offset
                    <= t.span.start_offset
                    < node.receiver_type.span.start_offset
                    and t.text == node.name
                ),
                None,
            )
            if token is None:
                raise LibraryError("P2A_LIBRARY_PROJECTION", "method name token is missing")
            linker.edit(unit, token.span.start_offset, token.span.end_offset, unit.renamed[key])
