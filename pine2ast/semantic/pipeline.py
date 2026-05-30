from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pine2ast.ast.nodes import Program


PASS_PIPELINE = (
    "declaration_index",
    "scope_symbols",
    "type_inference",
    "qualifier_inference",
    "builtin_validation",
    "strategy_context_validation",
    "unsupported_feature_extraction",
)


class SemanticPass(Protocol):
    name: str

    def run(self, program: Program) -> None: ...


@dataclass(frozen=True, slots=True)
class PassResult:
    name: str
    diagnostics_before: int
    diagnostics_after: int


class AnalyzerPassPipeline:
    def __init__(self, passes: tuple[SemanticPass, ...]) -> None:
        names = tuple(semantic_pass.name for semantic_pass in passes)
        if names != PASS_PIPELINE:
            raise ValueError(f"Unexpected semantic pass pipeline order: {names!r}")
        self._passes = passes

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(semantic_pass.name for semantic_pass in self._passes)

    def run(self, program: Program, *, diagnostics_count) -> tuple[PassResult, ...]:
        results: list[PassResult] = []
        for semantic_pass in self._passes:
            before = diagnostics_count()
            semantic_pass.run(program)
            after = diagnostics_count()
            results.append(PassResult(semantic_pass.name, before, after))
        return tuple(results)
