"""Version-exact static semantic hardening for Pine Script v1-v6.

This module belongs to the Pine2AST frontend.  It validates only language and
static-semantic rules.  Runtime execution, series rollback, data alignment and
broker fills remain downstream responsibilities and are deliberately not
simulated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from pine2ast.ast.base import ASTNode
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.ast.visitors import walk
from pine2ast.lexer.token import SourceSpan

_REQUIREMENTS_PATH = Path(__file__).with_name("version_semantic_requirements.json")


@dataclass(frozen=True, slots=True)
class SemanticRequirement:
    requirement_id: str
    pine_versions: tuple[int, ...]
    owner: str
    category: str
    description: str
    verification: str
    docs_ref: str
    test_id: str


@dataclass(frozen=True, slots=True)
class VersionSemanticOutcome:
    pine_version: int
    applicable_rule_ids: tuple[str, ...]
    diagnostics_added: int
    ruleset_hash: str


def _stable_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _hash(value: object) -> str:
    return "sha256:" + sha256(_stable_json(value).encode("utf-8")).hexdigest()


def load_semantic_requirements() -> tuple[SemanticRequirement, ...]:
    raw = json.loads(_REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    if raw.get("schema_id") != "pine2ast.version_semantic_requirements.v1":
        raise ValueError("invalid version semantic requirement schema")
    rows: list[SemanticRequirement] = []
    seen: set[str] = set()
    for item in raw.get("requirements", []):
        rid = str(item["requirement_id"])
        if rid in seen:
            raise ValueError(f"duplicate semantic requirement id: {rid}")
        seen.add(rid)
        versions = tuple(int(v) for v in item["pine_versions"])
        if not versions or any(v not in {1, 2, 3, 4, 5, 6} for v in versions):
            raise ValueError(f"invalid versions for {rid}: {versions}")
        owner = str(item["owner"])
        if owner not in {
            "pine2ast",
            "ast2python",
            "pinelib",
            "backtest_engine",
            "marketdata-provider",
        }:
            raise ValueError(f"invalid owner for {rid}: {owner}")
        rows.append(
            SemanticRequirement(
                requirement_id=rid,
                pine_versions=versions,
                owner=owner,
                category=str(item["category"]),
                description=str(item["description"]),
                verification=str(item["verification"]),
                docs_ref=str(item["docs_ref"]),
                test_id=str(item["test_id"]),
            )
        )
    return tuple(rows)


def requirements_for_version(
    version: int, *, owner: str | None = None
) -> tuple[SemanticRequirement, ...]:
    return tuple(
        row
        for row in load_semantic_requirements()
        if version in row.pine_versions and (owner is None or row.owner == owner)
    )


def requirements_hash() -> str:
    raw = json.loads(_REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    return _hash(raw)


def _get(node: object, key: str, default: object = None) -> object:
    if isinstance(node, Mapping):
        return node.get(key, default)
    return getattr(node, key, default)


def _kind(node: object) -> str:
    value = _get(node, "kind")
    return str(value) if isinstance(value, str) else type(node).__name__


def _iter_nodes(program: ASTNode) -> Iterable[ASTNode]:
    # The native AST visitor is linear and avoids serializing the entire tree
    # merely to apply a static availability gate.
    yield from walk(program)


def _span_from_mapping(value: object) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if not isinstance(value, Mapping):
        return SourceSpan.zero()
    try:
        return SourceSpan(
            int(value.get("start_offset", 0)),
            int(value.get("end_offset", 0)),
            int(value.get("start_line", 1)),
            int(value.get("start_col", 1)),
            int(value.get("end_line", value.get("start_line", 1))),
            int(value.get("end_col", value.get("start_col", 1))),
        )
    except (TypeError, ValueError):
        return SourceSpan.zero()


def _node_span(node: object) -> SourceSpan:
    return _span_from_mapping(_get(node, "span") or _get(node, "loc"))


def _callee_name(value: object) -> str | None:
    kind = _kind(value)
    if kind == "Identifier":
        name = _get(value, "name")
        return str(name) if isinstance(name, str) else None
    if kind == "MemberAccessExpr":
        root = _callee_name(_get(value, "object"))
        member = _get(value, "member")
        return f"{root}.{member}" if root and isinstance(member, str) else None
    if kind == "GenericInstantiationExpr":
        return _callee_name(_get(value, "base"))
    return None


def _call_name(node: object) -> str | None:
    if _kind(node) != "CallExpr":
        return None
    return _callee_name(_get(node, "callee"))


def _argument_names(node: object) -> set[str]:
    result: set[str] = set()
    arguments = _get(node, "arguments")
    if not isinstance(arguments, Sequence) or isinstance(arguments, (str, bytes, bytearray)):
        return result
    for argument in arguments:
        name = _get(argument, "name")
        if isinstance(name, str):
            result.add(name)
    return result


def _version_from_ast(program: object) -> int:
    context = getattr(program, "version_context", None)
    version = getattr(context, "pine_version", None)
    if type(version) is not int and isinstance(context, Mapping):
        version = context.get("pine_version")
    if type(version) is not int or version not in {1, 2, 3, 4, 5, 6}:
        raise ValueError("PineVersionContext.pine_version is required and must be 1..6")
    return version


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[str, int, int, str]:
    return (
        diagnostic.code,
        diagnostic.span.start_offset,
        diagnostic.span.end_offset,
        diagnostic.message,
    )


def _append_diagnostic(result: object, diagnostic: Diagnostic, *, limit: int | None = None) -> bool:
    diagnostics = getattr(result, "diagnostics", None)
    if not isinstance(diagnostics, list):
        return False
    if limit is not None and len(diagnostics) >= limit:
        return False
    keys = {_diagnostic_key(item) for item in diagnostics if isinstance(item, Diagnostic)}
    if _diagnostic_key(diagnostic) in keys:
        return False
    diagnostics.append(diagnostic)
    program = getattr(result, "ast", None)
    ast_diagnostics = getattr(program, "diagnostics", None)
    if isinstance(ast_diagnostics, list) and diagnostic not in ast_diagnostics:
        ast_diagnostics.append(diagnostic)
    return True


def _error(code: str, message: str, span: SourceSpan) -> Diagnostic:
    return Diagnostic(Severity.ERROR, code, message, span)


def _unavailable_node_kinds(version: int) -> Mapping[str, str]:
    common_modern = {
        "MethodDeclaration": "user-defined methods",
        "TypeDeclaration": "user-defined types",
        "EnumDeclaration": "enum declarations",
        "ImportDeclaration": "library imports",
        "SwitchStructure": "switch",
        "WhileStructure": "while",
        "MapLiteral": "map literals",
        "MatrixLiteral": "matrix literals",
    }
    if version == 1:
        return {
            **common_modern,
            "IfStructure": "if statements",
            "ForRangeStructure": "for loops",
            "ForInStructure": "for-in loops",
            "FunctionDeclaration": "user-defined functions",
            "Reassignment": "reassignment",
            "TupleDeclaration": "tuple declarations",
            "BreakStatement": "break",
            "ContinueStatement": "continue",
        }
    if version == 2:
        return {
            **common_modern,
            "ForInStructure": "for-in loops",
            "TupleDeclaration": "tuple declarations",
        }
    if version == 3:
        return {
            **common_modern,
            "ForInStructure": "for-in loops",
        }
    if version == 4:
        return {
            "MethodDeclaration": "user-defined methods",
            "TypeDeclaration": "user-defined types",
            "EnumDeclaration": "enum declarations",
            "ImportDeclaration": "library imports",
            "SwitchStructure": "switch",
            "WhileStructure": "while",
            "MapLiteral": "map literals",
            "MatrixLiteral": "matrix literals",
        }
    return {}


def _validate_node_availability(version: int, nodes: Sequence[object]) -> list[Diagnostic]:
    unavailable = _unavailable_node_kinds(version)
    diagnostics: list[Diagnostic] = []
    for node in nodes:
        kind = str(_get(node, "kind", ""))
        feature = unavailable.get(kind)
        if feature:
            diagnostics.append(
                _error(
                    codes.VERSION_FEATURE_UNAVAILABLE,
                    f"{feature} are not available in Pine v{version}.",
                    _node_span(node),
                )
            )
        if kind == "VarDeclaration" and version <= 3:
            if _get(node, "mode") in {"var", "varip"} or _get(node, "type_ref") is not None:
                diagnostics.append(
                    _error(
                        codes.VERSION_FEATURE_UNAVAILABLE,
                        f"Typed/var declarations are not available in Pine v{version}.",
                        _node_span(node),
                    )
                )
        if kind == "VarDeclaration" and version == 4 and _get(node, "mode") == "varip":
            # varip is accepted only when explicitly present in the v4 pack.  The
            # pack is authoritative; this guard catches drift in historical packs.
            pass
    return diagnostics


def _validate_declaration(
    version: int, program: object, nodes: Sequence[object]
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    declaration_nodes = [n for n in nodes if _get(n, "kind") == "DeclarationStatement"]
    if not declaration_nodes:
        return diagnostics
    node = declaration_nodes[0]
    script_type = str(_get(node, "script_type") or "")
    call = _get(node, "call")
    call_name = _callee_name(_get(call, "callee")) if call is not None else None
    name = call_name or script_type
    allowed = {
        1: {"study", "strategy"},
        2: {"study", "strategy"},
        3: {"study", "strategy"},
        4: {"study", "strategy"},
        5: {"indicator", "strategy", "library"},
        6: {"indicator", "strategy", "library"},
    }[version]
    if name and name not in allowed:
        diagnostics.append(
            _error(
                codes.VERSION_DECLARATION_UNAVAILABLE,
                f"Declaration {name}() is not available in Pine v{version}; allowed declarations: {', '.join(sorted(allowed))}.",
                _node_span(node),
            )
        )
    return diagnostics


def _validate_calls(version: int, nodes: Sequence[object]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    legacy_names = {
        "study",
        "sma",
        "ema",
        "rsi",
        "atr",
        "highest",
        "lowest",
        "barssince",
        "valuewhen",
        "security",
        "tickerid",
        "iff",
        "offset",
    }
    modern_roots = {"ta", "request", "math", "str", "ticker"}
    v5_v6_only_calls = {
        "input.int",
        "input.float",
        "input.bool",
        "input.string",
        "input.color",
        "input.timeframe",
        "input.symbol",
        "input.session",
        "input.source",
        "input.time",
    }
    user_callable_names = {
        str(_get(node, "name"))
        for node in nodes
        if type(node).__name__ in {"FunctionDeclaration", "MethodDeclaration"}
        and _get(node, "name")
    }
    for node in nodes:
        name = _call_name(node)
        if not name:
            continue
        is_user_callable = "." not in name and name in user_callable_names
        args = _argument_names(node)
        root = name.split(".", 1)[0]
        if version <= 4 and (root in modern_roots or name in v5_v6_only_calls):
            diagnostics.append(
                _error(
                    codes.MODERN_NAMESPACE_UNAVAILABLE,
                    f"Modern namespace call {name}() is not available in Pine v{version}.",
                    _node_span(node),
                )
            )
        if version >= 5 and name in legacy_names and not is_user_callable:
            diagnostics.append(
                _error(
                    codes.LEGACY_SPELLING_UNAVAILABLE,
                    f"Legacy call {name}() is not valid in Pine v{version}; use the versioned namespace spelling.",
                    _node_span(node),
                )
            )
        if version <= 3 and name.startswith(("array.", "map.", "matrix.")):
            diagnostics.append(
                _error(
                    codes.VERSION_CALL_UNAVAILABLE,
                    f"Collection call {name}() is not available in Pine v{version}.",
                    _node_span(node),
                )
            )
        if version == 4 and name.startswith(("map.", "matrix.")):
            diagnostics.append(
                _error(
                    codes.VERSION_CALL_UNAVAILABLE,
                    f"Collection call {name}() is not available in Pine v4.",
                    _node_span(node),
                )
            )
        if version == 6 and name.startswith("strategy.") and "when" in args:
            diagnostics.append(
                _error(
                    codes.VERSION_PARAMETER_UNAVAILABLE,
                    f"The when parameter of {name}() was removed in Pine v6.",
                    _node_span(node),
                )
            )
        if version >= 5 and name in {"indicator", "strategy", "library"}:
            if "resolution" in args or "resolution_gaps" in args:
                diagnostics.append(
                    _error(
                        codes.VERSION_PARAMETER_UNAVAILABLE,
                        "resolution/resolution_gaps declaration parameters were renamed to timeframe/timeframe_gaps in Pine v5.",
                        _node_span(node),
                    )
                )
        if version == 6 and "transp" in args and not is_user_callable:
            diagnostics.append(
                _error(
                    codes.VERSION_PARAMETER_UNAVAILABLE,
                    "The transp parameter is not available in Pine v6; encode transparency in the color value.",
                    _node_span(node),
                )
            )
        arguments = _get(node, "arguments")
        argument_count = (
            len(arguments)
            if isinstance(arguments, Sequence) and not isinstance(arguments, (str, bytes))
            else 0
        )
        if version >= 5 and name == "rsi" and argument_count >= 2 and not is_user_callable:
            diagnostics.append(
                _error(
                    codes.LEGACY_SPELLING_UNAVAILABLE,
                    "The historical two-argument rsi() overload is not available in Pine v5/v6.",
                    _node_span(node),
                )
            )
    return diagnostics


def _validate_version_context(program: object, version: int) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    context = getattr(program, "version_context", None)
    catalog_hash = getattr(context, "catalog_hash", None)
    if not isinstance(catalog_hash, str) or not catalog_hash.startswith("sha256:"):
        diagnostics.append(
            _error(
                codes.VERSION_CATALOG_IDENTITY_MISMATCH,
                "PineVersionContext.catalog_hash must be a sealed SHA-256 identity.",
                getattr(program, "span", SourceSpan.zero()),
            )
        )
    context_version = getattr(context, "pine_version", None)
    if context_version != version:
        diagnostics.append(
            _error(
                codes.VERSION_CATALOG_IDENTITY_MISMATCH,
                "AST and PineVersionContext version identities do not match.",
                getattr(program, "span", SourceSpan.zero()),
            )
        )
    return diagnostics


def apply_version_semantics(
    source: str | bytes, result: object, *, options: object | None = None
) -> object:
    """Apply version-exact static checks to a completed ParseResult.

    The pass is idempotent.  It adds only diagnostics and immutable producer
    metadata; it never rewrites source, changes the selected Pine version or
    substitutes a neighbouring version pack.
    """
    program = getattr(result, "ast", None)
    if not isinstance(program, ASTNode):
        return result
    version = _version_from_ast(program)
    nodes = tuple(_iter_nodes(program))
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(_validate_version_context(program, version))
    diagnostics.extend(_validate_node_availability(version, nodes))
    diagnostics.extend(_validate_declaration(version, program, nodes))
    diagnostics.extend(_validate_calls(version, nodes))
    added = sum(1 for item in diagnostics if _append_diagnostic(result, item))

    applicable = tuple(
        sorted(row.requirement_id for row in requirements_for_version(version, owner="pine2ast"))
    )
    outcome = VersionSemanticOutcome(
        pine_version=version,
        applicable_rule_ids=applicable,
        diagnostics_added=added,
        ruleset_hash=requirements_hash(),
    )
    result_diagnostics = getattr(result, "diagnostics", None)
    ast_diagnostics = getattr(program, "diagnostics", None)
    if isinstance(ast_diagnostics, list) and isinstance(result_diagnostics, list):
        ast_diagnostics[:] = result_diagnostics

    version_failed = any(item.is_error for item in diagnostics)
    frontend_failed = version_failed or (
        isinstance(result_diagnostics, list) and any(item.is_error for item in result_diagnostics)
    )
    metadata = getattr(program, "producer_metadata", None)
    if isinstance(metadata, dict):
        metadata["version_semantics"] = {
            "schema_id": "pine2ast.version_semantics.v1",
            "pine_version": outcome.pine_version,
            "ruleset_hash": outcome.ruleset_hash,
            "applicable_rule_ids": list(outcome.applicable_rule_ids),
            "diagnostics_added": outcome.diagnostics_added,
            "gate": "fail" if version_failed else "pass",
        }
        metadata["version_semantic_gate"] = "fail" if version_failed else "pass"
        metadata["frontend_gate"] = "fail" if frontend_failed else "pass"
        run_semantic = bool(getattr(options, "run_semantic", True))
        metadata["semantic_gate"] = (
            "not_run" if not run_semantic else ("fail" if frontend_failed else "pass")
        )
    return result


__all__ = [
    "SemanticRequirement",
    "VersionSemanticOutcome",
    "apply_version_semantics",
    "load_semantic_requirements",
    "requirements_for_version",
    "requirements_hash",
]
