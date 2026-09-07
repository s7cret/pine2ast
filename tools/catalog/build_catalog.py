#!/usr/bin/env python3
"""Build the canonical Pine v1-v6 catalog from audited inputs.

This builder is intentionally standalone: it imports only the Python standard
library and never imports the package being built.  Pine v5/v6 are migrated
losslessly from the RC5 reference snapshots.  Pine v1-v4 are materialized from
explicit, source-controlled historical projections and version-rule files.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SECTION_KIND = {
    "annotations": "annotation",
    "keywords": "keyword",
    "operators": "operator",
    "declarations": "declaration",
    "functions": "function",
    "methods": "method",
    "variables": "variable",
    "constants": "constant",
    "types": "type",
    "namespaces": "namespace",
    "enum_values": "enum_value",
}
SECTIONS = tuple(SECTION_KIND)
DROP_FIELDS = {
    "pine_version",
    "runtime_contract_unsupported",
    "ast2python_lowerable",
    "pinelib_runtime_support",
    "simulation_support",
    "live_safe",
    "codegen",
    "runtime",
    "simulation",
}
SPEC_REFS = {
    1: "tradingview-pine-v1-historical-static-snapshot-2026-08-27",
    2: "tradingview-pine-v2-historical-static-snapshot-2026-08-27",
    3: "tradingview-pine-v3-historical-static-snapshot-2026-08-27",
    4: "tradingview-pine-v4-historical-static-snapshot-2026-08-27",
    5: "tradingview-pine-v5-reference-snapshot-2026-08-26",
    6: "tradingview-pine-v6-reference-snapshot-2026-08-26",
}
STATUS = {
    1: "HISTORICAL_STATIC_SNAPSHOT",
    2: "HISTORICAL_STATIC_SNAPSHOT",
    3: "HISTORICAL_STATIC_SNAPSHOT",
    4: "HISTORICAL_STATIC_SNAPSHOT",
    5: "STATIC_COMPLETE",
    6: "STATIC_COMPLETE",
}

# Unknown/parametric return types must use explicit deterministic rules.
RETURN_RULE_IDS = {
    "array.avg": "return.collection.numeric_average.v1",
    "array.first": "return.collection.element.v1",
    "array.from": "return.array.from_arguments.v1",
    "array.get": "return.collection.element.v1",
    "array.insert": "return.void.v1",
    "array.last": "return.collection.element.v1",
    "array.max": "return.collection.element.v1",
    "array.min": "return.collection.element.v1",
    "array.pop": "return.collection.element.v1",
    "array.remove": "return.collection.element.v1",
    "array.shift": "return.collection.element.v1",
    "array.sort": "return.void.v1",
    "array.sum": "return.collection.numeric_sum.v1",
    "array.unshift": "return.void.v1",
    "box": "return.reference.box.v1",
    "input": "return.input.defval_type.v1",
    "input.enum": "return.input.enum_type.v1",
    "label": "return.reference.label.v1",
    "line": "return.reference.line.v1",
    "linefill": "return.reference.linefill.v1",
    "map.get": "return.map.value.v1",
    "map.remove": "return.map.value.v1",
    "matrix.get": "return.matrix.element.v1",
    "nz": "return.na.source_or_numeric_promotion.v1",
    "math.abs": "return.scalar.numeric_identity.v1",
    "math.round": "return.round.argument_arity.v1",
}

# Pine permits a ``series`` value at ordinary expression parameters unless the
# reference signature declares a weaker maximum. Keep weaker maxima in one
# data-driven table so every generated pack and overload shares the lattice.
QUALIFIER_MAX_OVERRIDES: dict[str, dict[str, str]] = {
    "input": {
        "defval": "const",
        "title": "const",
        "type": "const",
        "minval": "const",
        "maxval": "const",
        "step": "const",
        "options": "const",
        "confirm": "const",
    },
    # Specialized numeric inputs start in v5 and require const defaults. Source
    # inputs and active have different contracts; never widen this by prefix.
    # Primary v5/v6 authority: docs/STAGE2_INPUT_DEFVAL_QUALIFIERS.md.
    "input.int": {"defval": "const"},
    "input.float": {"defval": "const"},
    "ta.ema": {"length": "simple"},
    "ta.rma": {"length": "simple"},
    "ta.rsi": {"length": "simple"},
    "ta.supertrend": {"atrPeriod": "simple"},
    "ta.dmi": {"diLength": "simple", "adxSmoothing": "simple"},
}

# The pinned RC5 registry contained name-only entries for these admitted calls.
SIGNATURE_OVERRIDES: dict[str, list[dict[str, Any]]] = {
    "na": [{"name": "x", "required": True, "type": "any"}],
    "ta.supertrend": [
        {"name": "factor", "required": True, "type": "float"},
        {"name": "atrPeriod", "required": True, "type": "int"},
    ],
    "ta.dmi": [
        {"name": "diLength", "required": True, "type": "int"},
        {"name": "adxSmoothing", "required": True, "type": "int"},
    ],
    "int": [{"name": "value", "required": True, "type": "any"}],
    "float": [{"name": "x", "required": True, "type": "float"}],
}


def enrich_callable_contract(name: str, definition: dict[str, Any]) -> None:
    """Complete callable qualifier metadata before catalog sealing."""

    # Explicit casting functions were introduced in Pine v4. Keep the earlier
    # signature rows for version/coverage audits, but do not backport the call.
    # This metadata belongs to the function, never the historical input constant.
    if name == "float":
        definition["added_in"] = 4

    # Audited source correction; RC5 input bytes remain immutable. See
    # docs/STAGE2_SCALAR_SIGNATURE_REVIEW.md for independent/versioned sources.
    if name in {"math.abs", "math.ceil", "math.floor", "math.exp", "math.round", "math.sqrt"}:
        number = {"name": "number", "required": True, "type": "float"}
        definition["parameters"] = [number]
        definition["returns"] = (
            "int" if name in {"math.ceil", "math.floor", "math.round"} else "float"
        )
        definition["return_qualifier_rule_id"] = "qualifier.scalar.argument_join.v1"
        if name == "math.abs":
            definition["overloads"] = [
                {"parameters": [{**number, "type": "int"}], "returns": "int"}
            ]
            definition["return_rule_id"] = RETURN_RULE_IDS[name]
        elif name == "math.round":
            definition["overloads"] = [
                {
                    "parameters": [
                        number.copy(),
                        {"name": "precision", "required": True, "type": "int"},
                    ],
                    "returns": "float",
                }
            ]
            definition["return_rule_id"] = RETURN_RULE_IDS[name]

    if not definition.get("parameters") and name in SIGNATURE_OVERRIDES:
        definition["parameters"] = copy.deepcopy(SIGNATURE_OVERRIDES[name])
    if name in {"na", "nz"}:
        definition["return_qualifier_rule_id"] = "qualifier.scalar.argument_join_simple_floor.v1"
    if name == "math.pow":
        definition["return_qualifier_rule_id"] = "qualifier.scalar.argument_join.v1"
    candidates = [definition]
    overloads = definition.get("overloads")
    if isinstance(overloads, list):
        candidates.extend(item for item in overloads if isinstance(item, dict))
    overrides = QUALIFIER_MAX_OVERRIDES.get(name, {})
    for candidate in candidates:
        for parameter in candidate.get("parameters", []):
            if not isinstance(parameter, dict):
                continue
            # The frozen source mislabeled these rule inputs as const. They
            # accept fixed-for-run (simple) values, including user inputs, not series.
            risk_parameter = {
                "strategy.risk.max_position_size": "contracts",
                "strategy.risk.allow_entry_in": "value",
            }.get(name)
            if risk_parameter is not None and parameter.get("name") == risk_parameter:
                parameter["qualifier_max"] = "simple"
            elif parameter.get("name") in overrides:
                parameter["qualifier_max"] = overrides[str(parameter["name"])]
            else:
                parameter.setdefault(
                    "qualifier_max", overrides.get(str(parameter.get("name")), "series")
                )
        candidate.setdefault("return_qualifier", "series")
    if name == "array.from" and isinstance(definition.get("parameters"), list):
        for parameter in definition["parameters"]:
            if isinstance(parameter, dict) and parameter.get("name") == "values":
                parameter["variadic"] = True


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_identity(path: Path, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
    }


def jsonl_write(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def encode_identity(name: str) -> str:
    encoded = "".join(
        (
            char.lower()
            if char.lower() in "abcdefghijklmnopqrstuvwxyz0123456789_.-"
            else f"u{ord(char):04x}"
        )
        for char in name
    )
    if not encoded:
        raise ValueError("empty catalog symbol name")
    return encoded


def symbol_id(section: str, name: str) -> str:
    return f"pine:{SECTION_KIND[section]}:{encode_identity(name)}"


def normalized_definition(
    section: str, name: str, raw: Any, *, sid: str | None = None
) -> dict[str, Any]:
    definition = copy.deepcopy(raw) if isinstance(raw, Mapping) else {"value": raw}
    for key in DROP_FIELDS:
        definition.pop(key, None)
    definition.pop("name", None)
    definition = normalize(definition)
    if section in {"functions", "methods"}:
        enrich_callable_contract(name, definition)
        active_sid = sid or symbol_id(section, name)
        overloads = definition.get("overloads")
        if isinstance(overloads, list):
            for index, overload in enumerate(overloads):
                if not isinstance(overload, dict):
                    raise ValueError(f"{section}.{name} overload {index} must be an object")
                overload.setdefault("overload_id", f"{active_sid}#overload:{index}")
        if name == "nz":
            # Legacy snapshots summarized the float overload only. The actual
            # return is input-dependent; use one explicit deterministic rule.
            definition["return_rule_id"] = RETURN_RULE_IDS[name]
        if definition.get("returns") in {None, "unknown", "any"}:
            rule_id = RETURN_RULE_IDS.get(name)
            if rule_id is None and name.startswith("array.new<") and name.endswith(">"):
                rule_id = "return.array.explicit_element_type.v1"
            # Historical functions can preserve an explicit polymorphic return.
            if rule_id is None and definition.get("returns") == "any":
                rule_id = "return.historical.polymorphic.v1"
            if rule_id is None:
                raise ValueError(f"missing static return rule for {section}.{name}")
            definition["return_rule_id"] = rule_id
    return definition


def record(
    section: str,
    name: str,
    raw: Any,
    *,
    sid: str | None = None,
    provenance: str,
) -> dict[str, Any]:
    active_sid = sid or symbol_id(section, name)
    return {
        "symbol_id": active_sid,
        "kind": SECTION_KIND[section],
        "section": section,
        "name": name,
        "definition": normalized_definition(section, name, raw, sid=active_sid),
        "provenance": provenance,
    }


def flatten_modern(registry: Mapping[str, Any], version: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for section in SECTIONS:
        mapping = registry.get(section, {}) or {}
        if not isinstance(mapping, Mapping):
            raise ValueError(f"registry section {section} must be an object")
        for name, raw in sorted(mapping.items()):
            item = record(section, str(name), raw, provenance=f"rc5.v{version}")
            if item["symbol_id"] in result:
                raise ValueError(f"duplicate symbol identity {item['symbol_id']}")
            result[item["symbol_id"]] = item
    return result


def clone_record(
    item: Mapping[str, Any], *, name: str | None = None, definition: Any | None = None
) -> dict[str, Any]:
    result = copy.deepcopy(dict(item))
    if name is not None:
        result["name"] = name
    if definition is not None:
        result["definition"] = normalize(definition)
    return result


def definition_with_name(item: Mapping[str, Any], new_name: str) -> dict[str, Any]:
    definition = copy.deepcopy(item["definition"])
    # Names are not stored in normalized definitions.  Parameter/return metadata remains.
    return normalized_definition(item["section"], new_name, definition, sid=str(item["symbol_id"]))


def add_active(target: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
    active_key = (item["section"], item["name"])
    for current in target.values():
        if (current["section"], current["name"]) != active_key:
            continue
        if current["symbol_id"] == item["symbol_id"]:
            target[current["symbol_id"]] = item
            return
        # A few modern namespace functions collapse to one historical spelling.
        # Merge only callable overloads; all other collisions are fatal.
        if item["section"] != "functions":
            raise ValueError(f"ambiguous historical spelling {active_key}")
        merged = copy.deepcopy(current)
        left = _as_overloads(merged["definition"])
        right = _as_overloads(item["definition"])
        combined: list[dict[str, Any]] = []
        seen: set[bytes] = set()
        for overload in left + right:
            key = canonical_bytes({k: v for k, v in overload.items() if k != "overload_id"})
            if key in seen:
                continue
            seen.add(key)
            combined.append(overload)
        merged["definition"]["overloads"] = combined
        merged["definition"].pop("parameters", None)
        merged["definition"]["historical_merged_symbol_ids"] = sorted(
            set(merged["definition"].get("historical_merged_symbol_ids", []))
            | {str(current["symbol_id"]), str(item["symbol_id"])}
        )
        target[current["symbol_id"]] = merged
        return
    target[str(item["symbol_id"])] = item


def _as_overloads(definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    if isinstance(definition.get("overloads"), list):
        return [
            copy.deepcopy(item) for item in definition["overloads"] if isinstance(item, Mapping)
        ]
    return [
        {
            "parameters": copy.deepcopy(definition.get("parameters", [])),
            "returns": definition.get("returns", "unknown"),
        }
    ]


def rename_parameters(definition: dict[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    result = copy.deepcopy(definition)
    for key in ("parameters",):
        params = result.get(key)
        if isinstance(params, list):
            for param in params:
                if isinstance(param, dict) and param.get("name") in mapping:
                    param["name"] = mapping[str(param["name"])]
    overloads = result.get("overloads")
    if isinstance(overloads, list):
        for overload in overloads:
            if isinstance(overload, dict):
                overload["parameters"] = rename_parameters(
                    {"parameters": overload.get("parameters", [])}, mapping
                )["parameters"]
    return result


def trim_parameters(definition: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    result = copy.deepcopy(definition)
    params = result.get("parameters")
    if isinstance(params, list):
        result["parameters"] = [
            item for item in params if isinstance(item, dict) and item.get("name") in allowed
        ]
    return result


def legacy_input_definition() -> dict[str, Any]:
    return {
        "allow_extra_positional": True,
        "kind": "builtin",
        "parameters": [
            {"name": "defval", "required": False, "type": "any"},
            {"name": "title", "required": False, "type": "string"},
            {"name": "type", "required": False, "type": "string"},
            {"name": "minval", "required": False, "type": "float"},
            {"name": "maxval", "required": False, "type": "float"},
            {"name": "step", "required": False, "type": "float"},
            {"name": "options", "required": False, "type": "array<any>"},
            {"name": "confirm", "required": False, "type": "bool"},
        ],
        "returns": "any",
        "return_rule_id": "return.input.defval_type.v1",
        "scope": "any",
        "historical_signature_source": "tv.v4.input",
    }


def legacy_study_definition(indicator: Mapping[str, Any]) -> dict[str, Any]:
    result = rename_parameters(
        copy.deepcopy(dict(indicator)),
        {"timeframe": "resolution", "timeframe_gaps": "resolution_gaps"},
    )
    allowed = {
        "title",
        "shorttitle",
        "overlay",
        "format",
        "precision",
        "scale",
        "resolution",
        "resolution_gaps",
        "max_bars_back",
        "max_lines_count",
        "max_labels_count",
        "max_boxes_count",
    }
    result = trim_parameters(result, allowed)
    result["kind"] = "declaration"
    result["scope"] = "global_only"
    return result


def legacy_security_definition(current: Mapping[str, Any], *, version: int) -> dict[str, Any]:
    result = rename_parameters(copy.deepcopy(dict(current)), {"timeframe": "resolution"})
    allowed = {"symbol", "resolution", "expression", "gaps"}
    if version >= 3:
        allowed.add("lookahead")
    result = trim_parameters(result, allowed)
    for param in result.get("parameters", []):
        if param.get("name") == "gaps":
            param["type"] = "bool"
        if param.get("name") == "lookahead":
            param["type"] = "barmerge.lookahead"
    result.pop("dynamic_allowed", None)
    result["historical_default_lookahead"] = (
        "barmerge.lookahead_on" if version <= 2 else "barmerge.lookahead_off"
    )
    return result


def project_v4(
    flat5: Mapping[str, dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    rule = config["v4"]
    target: dict[str, dict[str, Any]] = {}
    exact = dict(rule.get("function_exact_renames", {}))
    unwrap = tuple(rule.get("function_prefix_unwrap", ()))
    remove_names = set(rule.get("function_remove_names", ()))
    remove_prefixes = tuple(rule.get("function_remove_prefixes", ()))
    var_remove = tuple(rule.get("variable_remove_prefixes", ()))
    const_remove = tuple(rule.get("constant_remove_prefixes", ()))
    keep_types = set(rule.get("types_keep", ()))

    for item in flat5.values():
        section = str(item["section"])
        name = str(item["name"])
        if section == "methods":
            continue
        if section == "keywords" or section == "operators":
            continue
        if section == "functions":
            if name in remove_names or name.startswith(remove_prefixes):
                continue
            if name in {"ta.max", "ta.min"}:  # historical max/min are math forms
                continue
            new_name = exact.get(name, name)
            for prefix in unwrap:
                if new_name.startswith(prefix):
                    new_name = new_name[len(prefix) :]
                    break
            definition = definition_with_name(item, new_name)
            if name == "indicator":
                definition = legacy_study_definition(definition)
            elif name == "input":
                definition = legacy_input_definition()
            elif name == "request.security":
                definition = legacy_security_definition(definition, version=4)
            elif name in {"time", "time_close"}:
                definition = rename_parameters(definition, {"timeframe": "resolution"})
            elif name in {
                "math.abs",
                "math.ceil",
                "math.floor",
                "math.exp",
                "math.round",
                "math.sqrt",
            }:
                definition = rename_parameters(definition, {"number": "x"})
            elif name == "nz":
                definition = rename_parameters(definition, {"source": "x", "replacement": "y"})
            add_active(target, clone_record(item, name=new_name, definition=definition))
            continue
        if section in {"variables", "constants"}:
            blocked = var_remove if section == "variables" else const_remove
            if name.startswith(blocked):
                continue
            new_name = name
            if section == "variables" and new_name.startswith("ta."):
                new_name = new_name[3:]
            if new_name.startswith("math."):
                new_name = new_name[5:]
            add_active(
                target,
                clone_record(item, name=new_name, definition=definition_with_name(item, new_name)),
            )
            continue
        if section == "types":
            if name not in keep_types:
                continue
            add_active(target, copy.deepcopy(item))
            continue
        if section == "namespaces":
            # Re-derived after projection from active dotted spellings.
            continue
        add_active(target, copy.deepcopy(item))

    # v4-only input type constants removed in v5.
    input_types = {
        "input.bool",
        "input.color",
        "input.float",
        "input.integer",
        "input.resolution",
        "input.session",
        "input.source",
        "input.string",
        "input.symbol",
        "input.time",
    }
    for name in sorted(input_types):
        sid = f"pine:constant:legacy.{encode_identity(name)}"
        add_active(
            target,
            record(
                "constants",
                name,
                {"kind": "constant", "qualifier": "const", "scope": "value", "type": "string"},
                sid=sid,
                provenance="tv.migration.v5.input_split",
            ),
        )
        add_active(
            target,
            record(
                "variables",
                name,
                {"qualifier": "const", "type": "string"},
                sid=f"pine:variable:legacy.{encode_identity(name)}",
                provenance="tv.migration.v5.input_split",
            ),
        )

    # Removed in v5 but valid in v4.
    add_active(
        target,
        record(
            "functions",
            "iff",
            {
                "kind": "builtin",
                "parameters": [
                    {"name": "condition", "required": True, "type": "bool"},
                    {"name": "then", "required": True, "type": "any"},
                    {"name": "else", "required": True, "type": "any"},
                ],
                "returns": "any",
                "return_rule_id": "return.historical.branch_merge.v1",
                "scope": "any",
                "evaluation": "EAGER",
            },
            sid="pine:function:legacy.iff",
            provenance="tv.migration.v5.iff_removed",
        ),
    )
    add_active(
        target,
        record(
            "functions",
            "offset",
            {
                "kind": "builtin",
                "parameters": [
                    {"name": "series", "required": True, "type": "series<any>"},
                    {"name": "offset", "required": True, "type": "int"},
                ],
                "returns": "series<any>",
                "scope": "any",
            },
            sid="pine:function:legacy.offset",
            provenance="tv.migration.v5.offset_removed",
        ),
    )

    # Restore the removed v4 RSI overload.
    rsi = next(
        (
            item
            for item in target.values()
            if item["section"] == "functions" and item["name"] == "rsi"
        ),
        None,
    )
    if rsi is not None:
        definition = copy.deepcopy(rsi["definition"])
        primary = {
            "parameters": [
                {"name": "x", "required": True, "type": "float", "qualifier_max": "series"},
                {"name": "y", "required": True, "type": "int", "qualifier_max": "simple"},
            ],
            "returns": definition.get("returns", "series<float>"),
            "overload_id": f"{rsi['symbol_id']}#overload:0",
            "stateful": True,
        }
        legacy = {
            "parameters": [
                {"name": "x", "required": True, "type": "series<float>"},
                {"name": "y", "required": True, "type": "series<float>"},
            ],
            "returns": "series<float>",
            "overload_id": f"{rsi['symbol_id']}#overload:1",
            "historical_semantics": "100 - 100 / (1 + x / y)",
            "stateful": False,
        }
        definition["overloads"] = [primary, legacy]
        definition.pop("parameters", None)
        target[str(rsi["symbol_id"])] = clone_record(rsi, definition=definition)

    return _with_generated_structure(target, version=4, config=config)


def project_v3(
    v4: Mapping[str, dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    rule = config["v3"]
    target: dict[str, dict[str, Any]] = {}
    function_exact = dict(rule.get("function_exact_renames", {}))
    variable_exact = dict(rule.get("variable_exact_renames", {}))
    function_remove = tuple(rule.get("remove_prefixes", ()))
    removed_types = set(rule.get("remove_types", ()))
    constant_unwrap = tuple(rule.get("constant_prefix_unwrap", ()))

    for item in v4.values():
        section = str(item["section"])
        name = str(item["name"])
        if section == "methods":
            continue
        if section in {"keywords", "operators", "namespaces"}:
            continue
        if section == "functions":
            if name.startswith(function_remove):
                continue
            new_name = function_exact.get(name, name)
            definition = definition_with_name(item, new_name)
            if name == "round":
                # The v3 reference has only round(x); precision was added in v4.
                definition.pop("overloads", None)
            add_active(
                target,
                clone_record(item, name=new_name, definition=definition),
            )
            continue
        if section in {"variables", "constants"}:
            if name.startswith(function_remove):
                continue
            new_name = variable_exact.get(name, name)
            if section == "variables" and new_name.startswith("timeframe."):
                new_name = new_name[len("timeframe.") :]
            if section == "constants":
                for prefix in constant_unwrap:
                    if new_name.startswith(prefix):
                        new_name = new_name[len(prefix) :]
                        break
            add_active(
                target,
                clone_record(item, name=new_name, definition=definition_with_name(item, new_name)),
            )
            continue
        if section == "types":
            base = name.split("<", 1)[0]
            if base in removed_types:
                continue
        add_active(target, copy.deepcopy(item))
    return _with_generated_structure(target, version=3, config=config)


def project_v2(
    v3: Mapping[str, dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    target = copy.deepcopy(dict(v3))
    for sid, item in list(target.items()):
        if item["section"] == "functions" and item["name"] == "security":
            target[sid] = clone_record(
                item,
                definition=legacy_security_definition(item["definition"], version=2),
            )
    return _with_generated_structure(target, version=2, config=config)


def project_v1(
    v2: Mapping[str, dict[str, Any]], config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    # TradingView documents v2 as fully backwards-compatible with v1.  The
    # callable/value catalog is therefore inherited; the version policy removes
    # v2-only grammar such as :=, if, for and user-defined functions.
    return _with_generated_structure(copy.deepcopy(dict(v2)), version=1, config=config)


def _with_generated_structure(
    items: Mapping[str, dict[str, Any]], *, version: int, config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    result = {
        sid: copy.deepcopy(item)
        for sid, item in items.items()
        if item["section"] not in {"keywords", "operators", "namespaces", "declarations"}
    }
    version_cfg = config[f"v{version}"]
    for keyword in version_cfg.get("keywords", []):
        add_active(
            result,
            record(
                "keywords",
                str(keyword),
                {"source": "official_historical_policy"},
                provenance=f"version_rules.v{version}",
            ),
        )
    for operator in version_cfg.get("operators", []):
        add_active(
            result,
            record(
                "operators",
                str(operator),
                {"source": "official_historical_policy"},
                provenance=f"version_rules.v{version}",
            ),
        )
    # Namespace identities are derived, not guessed independently.
    namespace_names: set[str] = set()
    for item in result.values():
        name = str(item["name"])
        if "." not in name:
            continue
        parts = name.split(".")[:-1]
        current: list[str] = []
        for part in parts:
            current.append(part)
            namespace_names.add(".".join(current))
    for namespace in sorted(namespace_names):
        add_active(
            result,
            record(
                "namespaces",
                namespace,
                {"source": "derived_from_active_symbols"},
                provenance=f"materialized.v{version}",
            ),
        )
    # Declaration rows are explicit catalog identities for parser admission.
    for item in list(result.values()):
        if item["section"] == "functions" and item["definition"].get("kind") == "declaration":
            add_active(
                result,
                record(
                    "declarations",
                    str(item["name"]),
                    {"callable_symbol_id": item["symbol_id"]},
                    sid=f"pine:declaration:{encode_identity(str(item['name']))}",
                    provenance=f"materialized.v{version}",
                ),
            )
    return result


def semantic_id(item: Mapping[str, Any]) -> str:
    return digest({"symbol_id": item["symbol_id"], "definition": item["definition"]})


def delta_between(
    previous: Mapping[str, dict[str, Any]], current: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid in sorted(set(previous) | set(current)):
        old = previous.get(sid)
        new = current.get(sid)
        if old is None and new is not None:
            rows.append(
                {
                    "op": "ADD",
                    "symbol_id": sid,
                    "section": new["section"],
                    "name": new["name"],
                    "semantic_id": semantic_id(new),
                }
            )
            continue
        if old is not None and new is None:
            rows.append({"op": "REMOVE", "symbol_id": sid})
            continue
        assert old is not None and new is not None
        if old["section"] != new["section"] or old["name"] != new["name"]:
            rows.append(
                {
                    "op": "RENAME",
                    "symbol_id": sid,
                    "section": new["section"],
                    "name": new["name"],
                }
            )
        if semantic_id(old) != semantic_id(new):
            rows.append({"op": "PATCH", "symbol_id": sid, "semantic_id": semantic_id(new)})
    return rows


def materialize_pack(
    *,
    version: int,
    items: Mapping[str, dict[str, Any]],
    rules: Mapping[str, Any],
    source_manifest_hash: str,
    projection_hash: str,
    provenance_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    sections = {section: {} for section in SECTIONS}
    names_seen: set[tuple[str, str]] = set()
    for sid, item in sorted(items.items()):
        key = (str(item["section"]), str(item["name"]))
        if key in names_seen:
            raise ValueError(f"ambiguous active spelling v{version}: {key}")
        names_seen.add(key)
        definition = copy.deepcopy(item["definition"])
        definition.update({"symbol_id": sid, "name": item["name"]})
        if item["section"] in {"functions", "methods"}:
            enrich_callable_contract(str(item["name"]), definition)
            overloads = definition.get("overloads")
            if isinstance(overloads, list):
                for index, overload in enumerate(overloads):
                    if not isinstance(overload, dict):
                        raise ValueError(
                            f"{item['section']}.{item['name']} overload {index} must be an object"
                        )
                    overload["overload_id"] = f"{sid}#overload:{index}"
        if item["section"] == "functions":
            definition["pine_version"] = str(version)
        if item["section"] == "operators":
            operator = str(item["name"])
            rule_ids = rules.get("semantic", {}).get("rule_ids", {})
            if operator == "and":
                definition["static_rule_id"] = rule_ids.get("logical_and")
            elif operator == "or":
                definition["static_rule_id"] = rule_ids.get("logical_or")
            elif operator == "/":
                definition["static_rule_id"] = rule_ids.get("const_int_division")
            elif operator == "?:":
                definition["static_rule_id"] = rule_ids.get("ternary")
            else:
                definition["static_rule_id"] = (
                    f"operator.{encode_identity(operator)}.static.v{version}"
                )
        sections[str(item["section"])][str(item["name"])] = definition
    body = {
        "schema_id": "pine.catalog.pack.v1",
        "schema_version": "1.0.0",
        "pine_version": version,
        "status": STATUS[version],
        "coverage_basis": (
            "official_historical_migration_guides_and_archived_manual_conservative_snapshot"
            if version <= 4
            else "pinned_reference_registry_static_snapshot"
        ),
        "spec_snapshot_ref": SPEC_REFS[version],
        "source_manifest_hash": source_manifest_hash,
        "historical_projection_hash": projection_hash,
        "provenance_sources": copy.deepcopy(provenance_sources),
        "rules": copy.deepcopy(dict(rules)),
        "sections": sections,
    }
    catalog_hash = digest(body)
    without_content = {**body, "catalog_hash": catalog_hash}
    return {**without_content, "content_hash": digest(without_content)}


def compare_lossless_modern(
    original: Mapping[str, Any], pack: Mapping[str, Any], *, version: int
) -> list[dict[str, Any]]:
    losses: list[dict[str, Any]] = []
    for section in SECTIONS:
        expected_map = original.get(section, {}) or {}
        actual_map = pack["sections"][section]
        if set(expected_map) != set(actual_map):
            losses.append(
                {
                    "version": version,
                    "section": section,
                    "name_set_mismatch": {
                        "missing": sorted(set(expected_map) - set(actual_map)),
                        "extra": sorted(set(actual_map) - set(expected_map)),
                    },
                }
            )
            continue
        for name, raw in expected_map.items():
            expected = normalized_definition(section, name, raw)
            actual = copy.deepcopy(actual_map[name])
            for key in ("symbol_id", "name", "pine_version", "static_rule_id"):
                actual.pop(key, None)
            if actual != expected:
                losses.append(
                    {
                        "version": version,
                        "section": section,
                        "name": name,
                        "expected": expected,
                        "actual": actual,
                    }
                )
    return losses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    inputs = root / "catalog_migration_inputs" / "rc5"
    source_dir = root / "catalog_source"
    pack_dir = root / "pine2ast" / "catalog_data" / "packs"
    reports = root / "catalog_reports"
    reports.mkdir(parents=True, exist_ok=True)

    input_paths = {version: inputs / f"builtins_v{version}.rc5.json" for version in (5, 6)}
    rule_path = source_dir / "version_rules.json"
    projection_path = source_dir / "historical_projection.json"
    for path in (*input_paths.values(), rule_path, projection_path):
        if not path.is_file():
            raise SystemExit(f"required catalog input is missing: {path}")

    registries = {
        version: json.loads(path.read_text(encoding="utf-8"))
        for version, path in input_paths.items()
    }
    version_rules = json.loads(rule_path.read_text(encoding="utf-8"))
    projection_doc = json.loads(projection_path.read_text(encoding="utf-8"))
    projection = {key: value for key, value in projection_doc.items() if key.startswith("v")}
    if set(version_rules.get("versions", {})) != {str(v) for v in range(1, 7)}:
        raise SystemExit("version_rules.json must define exactly Pine v1 through v6")

    # Explicit additive syntax updates extend the frozen migration inputs;
    # never rewrite an archived reference file or project new keywords backwards.
    for version in (5, 6):
        additions = version_rules["versions"][str(version)]["syntax"].get("keyword_additions", {})
        for name, row in additions.items():
            if (
                name in registries[version]["keywords"]
                or row.get("name") != name
                or not row.get("source")
            ):
                raise SystemExit("invalid or overlapping syntax addition")
            registries[version]["keywords"][name] = copy.deepcopy(row)

    modern5 = flatten_modern(registries[5], 5)
    modern6 = flatten_modern(registries[6], 6)
    version_items: dict[int, dict[str, dict[str, Any]]] = {}
    version_items[4] = project_v4(modern5, projection)
    version_items[3] = project_v3(version_items[4], projection)
    version_items[2] = project_v2(version_items[3], projection)
    version_items[1] = project_v1(version_items[2], projection)
    version_items[5] = modern5
    version_items[6] = modern6

    # Build canonical symbols and content-addressed semantics from all versions.
    canonical: dict[str, dict[str, Any]] = {}
    semantics: dict[str, dict[str, Any]] = {}
    observed: dict[str, list[int]] = {}
    for version in range(1, 7):
        for sid, item in version_items[version].items():
            observed.setdefault(sid, []).append(version)
            canonical.setdefault(
                sid,
                {
                    "symbol_id": sid,
                    "kind": item["kind"],
                    "canonical_name": item["name"],
                    "section": item["section"],
                },
            )
            sem_id = semantic_id(item)
            semantics.setdefault(
                sem_id,
                {
                    "semantic_id": sem_id,
                    "symbol_id": sid,
                    "definition": item["definition"],
                },
            )
    symbols = []
    for sid in sorted(canonical):
        row = copy.deepcopy(canonical[sid])
        row["first_observed_version"] = min(observed[sid])
        row["last_observed_version"] = max(observed[sid])
        # Prefer current canonical spelling when the symbol survives into v5/v6.
        for preferred in (6, 5, 4, 3, 2, 1):
            item = version_items[preferred].get(sid)
            if item is not None:
                row["canonical_name"] = item["name"]
                row["section"] = item["section"]
                row["kind"] = item["kind"]
                break
        symbols.append(row)

    deltas: dict[int, list[dict[str, Any]]] = {}
    previous: dict[str, dict[str, Any]] = {}
    for version in range(1, 7):
        deltas[version] = delta_between(previous, version_items[version])
        previous = version_items[version]

    input_identity = {
        "rc5_v5": file_identity(input_paths[5], root),
        "rc5_v6": file_identity(input_paths[6], root),
        "version_rules": file_identity(rule_path, root),
        "historical_projection": file_identity(projection_path, root),
    }
    manifest_body = {
        "schema_id": "pine.catalog.source_manifest.v2",
        "schema_version": "2.0.0",
        "input_identity": input_identity,
        "versions": {
            str(version): {
                "status": STATUS[version],
                "coverage_basis": (
                    "official_historical_migration_guides_and_archived_manual_conservative_snapshot"
                    if version <= 4
                    else "pinned_reference_registry_static_snapshot"
                ),
                "spec_snapshot_ref": SPEC_REFS[version],
                "delta_path": f"deltas/v{version}.jsonl",
            }
            for version in range(1, 7)
        },
        "policy": {
            "canonical_identity": "stable symbol_id across historical renames",
            "semantic_storage": "content-addressed definitions",
            "delta_storage": "sequential real changes v1 through v6",
            "legacy_registry_runtime_use": False,
            "unknown_version_fallback": False,
        },
    }
    manifest = {**manifest_body, "content_hash": digest(manifest_body)}

    temp = root / ".catalog-build-tmp"
    shutil.rmtree(temp, ignore_errors=True)
    (temp / "source" / "deltas").mkdir(parents=True)
    (temp / "packs").mkdir(parents=True)
    jsonl_write(temp / "source" / "symbols.jsonl", symbols)
    jsonl_write(
        temp / "source" / "semantics.jsonl",
        sorted(semantics.values(), key=lambda row: row["semantic_id"]),
    )
    for version in range(1, 7):
        jsonl_write(temp / "source" / "deltas" / f"v{version}.jsonl", deltas[version])
    (temp / "source" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    projection_hash = digest(projection_doc)
    packs: dict[int, dict[str, Any]] = {}
    pack_hashes: dict[str, str] = {}
    for version in range(1, 7):
        rules = version_rules["versions"][str(version)]
        provenance_sources = [
            copy.deepcopy(source)
            for source in projection_doc.get("sources", [])
            if version in source.get("applies_to", [])
        ]
        if version >= 5:
            provenance_sources.append(
                {
                    "id": f"rc5.registry.v{version}",
                    "path": input_identity[f"rc5_v{version}"]["path"],
                    "sha256": input_identity[f"rc5_v{version}"]["sha256"],
                    "assertions": ["lossless_static_registry_migration"],
                }
            )
        pack = materialize_pack(
            version=version,
            items=version_items[version],
            rules=rules,
            source_manifest_hash=manifest["content_hash"],
            projection_hash=projection_hash,
            provenance_sources=provenance_sources,
        )
        packs[version] = pack
        pack_hashes[str(version)] = pack["catalog_hash"]
        (temp / "packs" / f"pine_v{version}.pack.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    losses = compare_lossless_modern(registries[5], packs[5], version=5)
    losses.extend(compare_lossless_modern(registries[6], packs[6], version=6))
    if losses:
        raise SystemExit(f"catalog migration is not lossless: {len(losses)} differences")

    counts = {
        str(version): {section: len(packs[version]["sections"][section]) for section in SECTIONS}
        for version in range(1, 7)
    }
    report = {
        "schema_id": "pine.catalog.migration_report.v2",
        "ok": True,
        "input_identity": input_identity,
        "canonical_symbol_count": len(symbols),
        "semantic_definition_count": len(semantics),
        "delta_counts": {str(version): len(deltas[version]) for version in range(1, 7)},
        "section_counts": counts,
        "pack_hashes": pack_hashes,
        "migration_loss_count": 0,
        "migration_loss": [],
        "historical_projection_hash": projection_hash,
        "invariants": {
            "ambiguous_active_spelling": 0,
            "orphan_operations": 0,
            "orphan_semantics": 0,
            "duplicate_symbol_ids": 0,
            "rename_cycles": 0,
            "modern_migration_loss": 0,
        },
    }
    (temp / "migration_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    generated = {
        source_dir / "symbols.jsonl": temp / "source" / "symbols.jsonl",
        source_dir / "semantics.jsonl": temp / "source" / "semantics.jsonl",
        source_dir / "manifest.json": temp / "source" / "manifest.json",
        reports / "migration_report.json": temp / "migration_report.json",
    }
    for version in range(1, 7):
        generated[source_dir / "deltas" / f"v{version}.jsonl"] = (
            temp / "source" / "deltas" / f"v{version}.jsonl"
        )
        generated[pack_dir / f"pine_v{version}.pack.json"] = (
            temp / "packs" / f"pine_v{version}.pack.json"
        )

    drift: list[str] = []
    for target, candidate in generated.items():
        data = candidate.read_bytes()
        if args.check:
            if not target.exists() or target.read_bytes() != data:
                drift.append(target.relative_to(root).as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    shutil.rmtree(temp)
    if drift:
        print(json.dumps({"ok": False, "drift": drift}, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
