from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_builtin_registry() -> dict[str, Any]:
    data = Path(__file__).with_name("builtins_v6.json").read_text(encoding="utf-8")
    registry = json.loads(data)
    if registry.get("schema_version") != 1 or registry.get("pine_version") != "6":
        raise ValueError("Unsupported builtins_v6.json schema")
    for name, entry in registry.get("functions", {}).items():
        for required in ("name", "kind", "pine_version", "parameters", "returns", "scope"):
            if required not in entry:
                raise ValueError(f"Builtin {name} is missing {required}")
    return registry


EXPECTED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "ta": {"sma", "ema", "bb", "macd", "rsi", "atr", "highest", "lowest", "crossover", "crossunder", "change", "valuewhen"},
    "math": {"abs", "max", "min", "round", "floor", "ceil", "sqrt", "pow", "log", "exp", "sin", "cos"},
    "str": {"tostring", "tonumber", "format", "contains", "startswith", "endswith", "replace", "split", "length"},
    "color": {"new", "rgb", "from_gradient"},
    "request": {"currency_rate", "dividends", "earnings", "financial", "quandl", "security", "security_lower_tf", "seed", "splits"},
    "line": {"new", "delete", "set_xy1", "set_xy2", "get_x1", "get_y1", "get_x2", "get_y2", "style_solid", "style_dashed", "style_dotted", "style_arrow_left", "style_arrow_right", "style_arrow_both"},
    "label": {"new", "delete", "set_text", "set_x", "set_y", "get_text", "get_x", "get_y", "style_none", "style_xcross", "style_cross", "style_triangleup", "style_triangledown", "style_flag", "style_circle", "style_arrowup", "style_arrowdown", "style_label_up", "style_label_down", "style_label_left", "style_label_right", "style_label_lower_left", "style_label_lower_right", "style_label_upper_left", "style_label_upper_right"},
    "box": {"new", "delete", "set_left", "set_right", "set_top", "set_bottom"},
    "table": {"new", "cell", "clear", "delete", "set_position"},
    "polyline": {"new", "delete"},
    "display": {"all", "none", "data_window", "pane", "price_scale", "status_line"},
    "position": {"top_left", "top_right", "bottom_left", "bottom_right", "middle_left", "middle_right", "middle_center"},
    "barmerge": {"gaps_off", "gaps_on", "lookahead_off", "lookahead_on"},
    "dividends": {"gross", "net"},
    "earnings": {"actual", "estimate", "standardized"},
    "splits": {"denominator", "numerator"},
    "strategy.closedtrades": {"entry_bar_index", "entry_comment", "entry_id", "entry_price", "entry_time", "exit_bar_index", "exit_comment", "exit_id", "exit_price", "exit_time", "max_drawdown", "max_runup", "profit", "size"},
    "strategy.opentrades": {"entry_bar_index", "entry_comment", "entry_id", "entry_price", "entry_time", "max_drawdown", "max_runup", "profit", "size"},
}


def builtin_registry_coverage_report() -> dict[str, Any]:
    registry = load_builtin_registry()
    functions = set(registry.get("functions", {}))
    variables = set(registry.get("variables", {}))
    namespaces = sorted(registry.get("namespaces", {}))
    namespace_reports = {}
    for namespace in namespaces:
        prefix = namespace + "."
        entries = sorted(name for name in functions | variables if name.startswith(prefix))
        expected = EXPECTED_NAMESPACE_MEMBERS.get(namespace)
        expected_full = {f"{namespace}.{member}" for member in expected} if expected else set()
        namespace_reports[namespace] = {
            "entry_count": len(entries),
            "entries": entries,
            "expected_count": len(expected_full),
            "missing_expected": sorted(expected_full - set(entries)),
            "coverage_ratio": (len(expected_full & set(entries)) / len(expected_full)) if expected_full else None,
        }
    # Nested strategy trade namespaces are useful enough for a dedicated report.
    for namespace, expected in EXPECTED_NAMESPACE_MEMBERS.items():
        if namespace in namespace_reports:
            continue
        prefix = namespace + "."
        entries = sorted(name for name in functions | variables if name.startswith(prefix))
        expected_full = {f"{namespace}.{member}" for member in expected}
        namespace_reports[namespace] = {
            "entry_count": len(entries),
            "entries": entries,
            "expected_count": len(expected_full),
            "missing_expected": sorted(expected_full - set(entries)),
            "coverage_ratio": (len(expected_full & set(entries)) / len(expected_full)) if expected_full else None,
        }
    return {
        "schema_version": registry.get("schema_version"),
        "pine_version": registry.get("pine_version"),
        "function_count": len(functions),
        "variable_count": len(variables),
        "namespace_count": len(namespaces),
        "namespaces": namespace_reports,
    }
