from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REQUIRED_TOP_LEVEL_SECTIONS = ("functions", "namespaces", "types", "variables")
_REQUIRED_FUNCTION_FIELDS = ("name", "kind", "pine_version", "parameters", "returns", "scope")
_ALLOWED_FUNCTION_KINDS = {"builtin", "declaration"}
_ALLOWED_FUNCTION_SCOPES = {"any", "global", "global_only", "strategy_readonly"}
_ALLOWED_VARIABLE_QUALIFIERS = {"const", "input", "simple", "series"}
_ALLOWED_PARAM_KEYS = {
    "name",
    "type",
    "required",
    "qualifier_max",
    "metadata_version",
    "deprecated_in",
    "removed_in",
    "replacement",
    "diagnostic_code",
}


class BuiltinRegistrySchemaError(ValueError):
    """Raised when the bundled builtin registry does not match its strict schema."""


def _schema_error(path: str, message: str) -> BuiltinRegistrySchemaError:
    return BuiltinRegistrySchemaError(f"Invalid builtin registry at {path}: {message}")


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _schema_error(path, "expected object")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise _schema_error(path, "expected non-empty string")
    return value


def validate_builtin_registry(registry: dict[str, Any]) -> None:
    """Validate the builtin registry schema strictly enough to catch corrupt packs.

    The registry is intentionally a compact JSON snapshot, not a full JSON-Schema
    document. This validator protects the semantic analyzer from malformed or
    accidentally drifted data while still allowing additive metadata keys at the
    top level and function-entry level.
    """

    root = _require_mapping(registry, "$")
    if root.get("schema_version") != 1 or root.get("pine_version") != "6":
        raise _schema_error("$", "unsupported schema_version/pine_version")
    for section in _REQUIRED_TOP_LEVEL_SECTIONS:
        if section not in root:
            raise _schema_error(f"$.{section}", "missing required section")
        _require_mapping(root[section], f"$.{section}")

    namespaces = root["namespaces"]
    for name, meta in namespaces.items():
        _require_string(name, f"$.namespaces key {name!r}")
        _require_mapping(meta, f"$.namespaces.{name}")

    types = root["types"]
    for name, meta in types.items():
        _require_string(name, f"$.types key {name!r}")
        _require_mapping(meta, f"$.types.{name}")
        if "name" in meta and meta["name"] != name:
            raise _schema_error(f"$.types.{name}.name", "must match registry key")

    variables = root["variables"]
    for name, meta in variables.items():
        _require_string(name, f"$.variables key {name!r}")
        entry = _require_mapping(meta, f"$.variables.{name}")
        _require_string(entry.get("type"), f"$.variables.{name}.type")
        qualifier = _require_string(entry.get("qualifier"), f"$.variables.{name}.qualifier")
        if qualifier not in _ALLOWED_VARIABLE_QUALIFIERS:
            raise _schema_error(
                f"$.variables.{name}.qualifier", f"unsupported qualifier {qualifier!r}"
            )

    functions = root["functions"]
    seen_names: set[str] = set()
    for name, meta in functions.items():
        _require_string(name, f"$.functions key {name!r}")
        entry = _require_mapping(meta, f"$.functions.{name}")
        for required in _REQUIRED_FUNCTION_FIELDS:
            if required not in entry:
                raise _schema_error(f"$.functions.{name}.{required}", "missing required field")
        if entry["name"] != name:
            raise _schema_error(f"$.functions.{name}.name", "must match registry key")
        if name in seen_names:
            raise _schema_error(f"$.functions.{name}", "duplicate function name")
        seen_names.add(name)
        if entry["kind"] not in _ALLOWED_FUNCTION_KINDS:
            raise _schema_error(f"$.functions.{name}.kind", f"unsupported kind {entry['kind']!r}")
        if entry["pine_version"] != "6":
            raise _schema_error(f"$.functions.{name}.pine_version", "must be '6'")
        scope = _require_string(entry["scope"], f"$.functions.{name}.scope")
        if scope not in _ALLOWED_FUNCTION_SCOPES:
            raise _schema_error(f"$.functions.{name}.scope", f"unsupported scope {scope!r}")
        _require_string(entry["returns"], f"$.functions.{name}.returns")
        params = entry["parameters"]
        if not isinstance(params, list):
            raise _schema_error(f"$.functions.{name}.parameters", "expected array")
        param_names: set[str] = set()
        for idx, param in enumerate(params):
            p_path = f"$.functions.{name}.parameters[{idx}]"
            p = _require_mapping(param, p_path)
            unknown = set(p) - _ALLOWED_PARAM_KEYS
            if unknown:
                raise _schema_error(p_path, f"unknown parameter metadata keys: {sorted(unknown)}")
            p_name = _require_string(p.get("name"), f"{p_path}.name")
            if p_name in param_names:
                raise _schema_error(f"{p_path}.name", f"duplicate parameter {p_name!r}")
            param_names.add(p_name)
            if "type" in p:
                _require_string(p["type"], f"{p_path}.type")
            if "required" in p and not isinstance(p["required"], bool):
                raise _schema_error(f"{p_path}.required", "expected boolean")
            if "qualifier_max" in p:
                _require_string(p["qualifier_max"], f"{p_path}.qualifier_max")


@lru_cache(maxsize=1)
def load_builtin_registry() -> dict[str, Any]:
    data = Path(__file__).with_name("builtins_v6.json").read_text(encoding="utf-8")
    registry = json.loads(data)
    validate_builtin_registry(registry)
    return registry


# Internal snapshot used by tests and strict-mode confidence. This is not an
# exhaustive TradingView/Pine official API list.
INTERNAL_EXPECTED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "ta": {
        "sma",
        "ema",
        "bb",
        "macd",
        "rsi",
        "atr",
        "highest",
        "lowest",
        "crossover",
        "crossunder",
        "change",
        "valuewhen",
    },
    "math": {
        "abs",
        "max",
        "min",
        "round",
        "floor",
        "ceil",
        "sqrt",
        "pow",
        "log",
        "exp",
        "sin",
        "cos",
    },
    "str": {
        "tostring",
        "tonumber",
        "format",
        "contains",
        "startswith",
        "endswith",
        "replace",
        "split",
        "length",
    },
    "color": {"new", "rgb", "from_gradient"},
    "request": {
        "currency_rate",
        "dividends",
        "earnings",
        "financial",
        "quandl",
        "security",
        "security_lower_tf",
        "seed",
        "splits",
    },
    "line": {
        "new",
        "delete",
        "set_xy1",
        "set_xy2",
        "get_x1",
        "get_y1",
        "get_x2",
        "get_y2",
        "style_solid",
        "style_dashed",
        "style_dotted",
        "style_arrow_left",
        "style_arrow_right",
        "style_arrow_both",
    },
    "label": {
        "new",
        "delete",
        "set_text",
        "set_x",
        "set_y",
        "get_text",
        "get_x",
        "get_y",
        "style_none",
        "style_xcross",
        "style_cross",
        "style_triangleup",
        "style_triangledown",
        "style_flag",
        "style_circle",
        "style_arrowup",
        "style_arrowdown",
        "style_label_up",
        "style_label_down",
        "style_label_left",
        "style_label_right",
        "style_label_lower_left",
        "style_label_lower_right",
        "style_label_upper_left",
        "style_label_upper_right",
    },
    "box": {"new", "delete", "set_left", "set_right", "set_top", "set_bottom"},
    "table": {"new", "cell", "clear", "delete", "set_position"},
    "polyline": {"new", "delete"},
    "display": {"all", "none", "data_window", "pane", "price_scale", "status_line"},
    "position": {
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "middle_left",
        "middle_right",
        "middle_center",
    },
    "barmerge": {"gaps_off", "gaps_on", "lookahead_off", "lookahead_on"},
    "dividends": {"gross", "net"},
    "earnings": {"actual", "estimate", "standardized"},
    "splits": {"denominator", "numerator"},
    "strategy.closedtrades": {
        "entry_bar_index",
        "entry_comment",
        "entry_id",
        "entry_price",
        "entry_time",
        "exit_bar_index",
        "exit_comment",
        "exit_id",
        "exit_price",
        "exit_time",
        "max_drawdown",
        "max_runup",
        "profit",
        "size",
    },
    "strategy.opentrades": {
        "entry_bar_index",
        "entry_comment",
        "entry_id",
        "entry_price",
        "entry_time",
        "max_drawdown",
        "max_runup",
        "profit",
        "size",
    },
}

# Curated official members known to exist but not yet represented in this
# registry snapshot. Kept separate so coverage output does not imply official
# coverage is complete when the internal expected set is green.
OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "line": {"set_extend", "set_style", "set_width", "set_x1", "set_x2", "set_y1", "set_y2"},
    "label": {"set_size", "set_style", "set_tooltip"},
    "box": {
        "set_border_color",
        "set_border_style",
        "set_border_width",
        "set_extend",
        "set_text",
        "set_text_color",
        "set_text_size",
        "set_text_wrap",
    },
    "table": {
        "cell_set_bgcolor",
        "cell_set_height",
        "cell_set_text",
        "cell_set_text_color",
        "cell_set_text_size",
        "cell_set_width",
        "merge_cells",
    },
}

# Known but deliberately deferred/unsupported surfaces. These are not counted as
# missing internal coverage and should not be used to claim official completeness.
KNOWN_DEFERRED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "request": {"economic"},
}
KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "runtime": {"error"},
}

# Backwards-compatible public alias used by older tests/imports.
EXPECTED_NAMESPACE_MEMBERS = INTERNAL_EXPECTED_NAMESPACE_MEMBERS


def _full_names(namespace: str, members: set[str]) -> set[str]:
    return {f"{namespace}.{member}" for member in members}


def builtin_registry_coverage_report() -> dict[str, Any]:
    registry = load_builtin_registry()
    functions = set(registry.get("functions", {}))
    variables = set(registry.get("variables", {}))
    namespaces = set(registry.get("namespaces", {}))
    tracked_namespaces = sorted(
        namespaces
        | set(INTERNAL_EXPECTED_NAMESPACE_MEMBERS)
        | set(OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS)
        | set(KNOWN_DEFERRED_NAMESPACE_MEMBERS)
        | set(KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS)
    )
    namespace_reports = {}
    all_entries = functions | variables
    for namespace in tracked_namespaces:
        prefix = namespace + "."
        entries = sorted(name for name in all_entries if name.startswith(prefix))
        entry_set = set(entries)
        internal_expected = _full_names(
            namespace, INTERNAL_EXPECTED_NAMESPACE_MEMBERS.get(namespace, set())
        )
        official_unmapped = (
            _full_names(namespace, OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS.get(namespace, set()))
            - entry_set
        )
        known_deferred = _full_names(
            namespace, KNOWN_DEFERRED_NAMESPACE_MEMBERS.get(namespace, set())
        )
        known_unsupported = _full_names(
            namespace, KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS.get(namespace, set())
        )
        missing_internal = sorted(internal_expected - entry_set)
        namespace_reports[namespace] = {
            "entry_count": len(entries),
            "entries": entries,
            "coverage_basis": "internal_expected_snapshot_not_official_complete",
            "internal_expected_count": len(internal_expected),
            "missing_internal_expected": missing_internal,
            "internal_coverage_ratio": (
                (len(internal_expected & entry_set) / len(internal_expected))
                if internal_expected
                else None
            ),
            "official_unmapped": sorted(official_unmapped),
            "known_deferred": sorted(known_deferred),
            "known_unsupported": sorted(known_unsupported),
            # Backwards-compatible names for existing tests and artifacts.
            "expected_count": len(internal_expected),
            "missing_expected": missing_internal,
            "coverage_ratio": (
                (len(internal_expected & entry_set) / len(internal_expected))
                if internal_expected
                else None
            ),
        }
    missing_by_ns = {
        ns: data["missing_internal_expected"]
        for ns, data in namespace_reports.items()
        if data["missing_internal_expected"]
    }
    official_unmapped_by_ns = {
        ns: data["official_unmapped"]
        for ns, data in namespace_reports.items()
        if data["official_unmapped"]
    }
    known_deferred_by_ns = {
        ns: data["known_deferred"]
        for ns, data in namespace_reports.items()
        if data["known_deferred"]
    }
    known_unsupported_by_ns = {
        ns: data["known_unsupported"]
        for ns, data in namespace_reports.items()
        if data["known_unsupported"]
    }
    return {
        "schema_version": registry.get("schema_version"),
        "pine_version": registry.get("pine_version"),
        "function_count": len(functions),
        "variable_count": len(variables),
        "namespace_count": len(namespaces),
        "coverage_basis": "internal_expected_snapshot_not_official_complete",
        "missing_internal_expected_count": sum(len(v) for v in missing_by_ns.values()),
        "official_unmapped_count": sum(len(v) for v in official_unmapped_by_ns.values()),
        "known_deferred_count": sum(len(v) for v in known_deferred_by_ns.values()),
        "known_unsupported_count": sum(len(v) for v in known_unsupported_by_ns.values()),
        "taxonomy": {
            "internal_expected": "curated project confidence set; missing items are actionable regressions/backlog",
            "official_unmapped": "known official Pine members not yet modeled in builtins_v6.json",
            "known_deferred": "known official or quasi-official surface intentionally deferred",
            "known_unsupported": "known surface intentionally unsupported by this parser/semantic layer",
        },
        "namespaces": namespace_reports,
    }
