"""Producer-owned AST2.1 feature admission and fresh semantic verification."""

from __future__ import annotations

from typing import Any, Mapping

from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError, decode_program

METHOD_RECEIVER_CAPABILITY = "method_receiver_qualifiers_v1"


def receiver_feature(
    ast: Mapping[str, Any], context: Mapping[str, Any], *, budget: ASTAdmissionBudget
) -> bool:
    """Inspect already-preflighted plain data, including unused declarations."""
    found = False
    stack: list[Any] = [ast]
    while stack:
        value = stack.pop()
        budget.charge()
        if isinstance(value, dict):
            if "receiver_explicit_qualifier" in value:
                if (
                    value.get("kind") != "MethodDeclaration"
                    or type(value["receiver_explicit_qualifier"]) is not str
                    or value["receiver_explicit_qualifier"] not in {"simple", "series"}
                ):
                    raise ASTDecodeError("invalid method receiver qualifier field")
                found = True
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    if ast.get("schema_version") != ("2.1" if found else "2.0"):
        raise ASTDecodeError("AST revision and method receiver feature must match exactly")
    if found and (
        type(context.get("pine_version")) is not int or context["pine_version"] not in {5, 6}
    ):
        raise ASTDecodeError("method receiver qualifiers require Pine v5/v6")
    return found


def verify_method_receiver_semantics(
    ast: Mapping[str, Any], facts: Mapping[str, Any], *, budget: ASTAdmissionBudget
) -> None:
    """Rebuild facts from canonical AST with the sole producer semantic owner.

    No supplied symbol, qualifier, scope or callable model is reused. Comparing
    all authoritative facts/calls closes colluding chains through aliases/UDFs
    and operations. Ordinary AST2.0 retains its existing verification route.
    """
    from pine2ast import ParseOptions, ParsePipeline
    from .model import content_hash

    program = decode_program(ast, budget=budget)
    try:
        model = ParsePipeline(
            ParseOptions(max_ast_nodes=budget.limits.max_ast_nodes)
        ).semantic_only(program)
        if any(d.is_error for d in model.diagnostics):
            raise ASTDecodeError("reconstructed method receiver semantics contain errors")
        if model.semantic_facts is None:
            raise ASTDecodeError("reconstructed semantic facts are missing")
        fresh = model.semantic_facts.artifact
        budget.charge(len(fresh["facts"]) + len(fresh["calls"]))
        # Producer metadata is independently checked by bundle lineage. Every
        # semantic artifact field, including identities, defaults, diagnostics,
        # coverage, coercions and const/qualifier facts, must match the fresh run.
        expected = {key: value for key, value in fresh.items() if key != "content_hash"}
        # The artifact owner adds producer provenance after the semantic pass.
        # Its identity/lineage was already verified; replay does not invent a
        # different local-build stamp or compare hashes of different envelopes.
        if "producer" in facts:
            expected["producer"] = facts["producer"]
        expected["content_hash"] = content_hash(expected)
        if facts != expected:
            raise ASTDecodeError("AST2.1 semantic facts differ from fresh producer analysis")
    except (ValueError, RecursionError, TypeError, KeyError, AttributeError) as exc:
        raise ASTDecodeError(f"method receiver semantic replay failed: {exc}") from exc
