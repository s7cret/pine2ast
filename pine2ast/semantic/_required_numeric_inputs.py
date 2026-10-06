"""Hand-authored LOCAL numeric-input catalog invariants.

Expectations are independent of installed inventory and generator output, but
that construction independence is NOT independent external contractual proof.
Exact signatures/defaults remain guarded locally while authority conflicts stay
UNVERIFIED. See docs/RC6_REQUIRED_NUMERIC_INPUT_CONTRACTS.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_MISSING = object()


def _parameter(
    name: str,
    type_name: str,
    *,
    required: bool = False,
    qualifier: str = "const",
    default: Any = _MISSING,
) -> dict[str, Any]:
    value = {
        "name": name,
        "type": type_name,
        "required": required,
        "qualifier_max": qualifier,
    }
    if default is not _MISSING:
        value["default"] = default
    return value


def numeric_input_authority(version: int) -> dict[str, Any]:
    """Disclose evidence boundaries; local success never discharges Pine debt.

    This is claim metadata, not a second, externally complete denominator.
    Versioned retained responses and exact excerpts are mapped in the document.
    """
    source = f"evidence/authority-inputs-v{version}.html"
    evidenced = [
        {
            "dimension": "specialized_calls_start_v5",
            "source": "evidence/authority-migration-v5.html",
            "section": "Split of input() into several functions",
        }
    ]
    unresolved = []
    if version >= 5:
        evidenced += [
            {"dimension": dimension, "source": source, "section": section}
            for dimension, section in (
                ("bounded_options_forms", "Integer input / Float input"),
                ("numeric_const_arguments", "Input function parameters"),
                ("int_return_input_int", "Integer input"),
            )
        ]
        unresolved += [
            {
                "dimension": dimension,
                "status": "UNVERIFIED",
                "reason": reason,
            }
            for dimension, reason in (
                ("optional_text_defaults", "No retained exact empty-default authority."),
                ("bounded_default_absence", "No retained proof of absent min/max defaults."),
                (
                    "float_return_type",
                    "Float signatures say input int; examples do not resolve exact result type.",
                ),
            )
        ]
        if version == 5:
            unresolved += [
                {"dimension": dimension, "status": "UNVERIFIED", "reason": reason}
                for dimension, reason in (
                    (
                        "display_membership_and_exact_signature",
                        "v5 common prose includes display; numeric signatures omit it.",
                    ),
                    ("step_default", "v5 retained text does not state step=1."),
                    ("confirm_default", "v5 retained text does not state confirm=false."),
                )
            ]
        else:
            evidenced += [
                {"dimension": dimension, "source": source, "section": section}
                for dimension, section in (
                    ("ordered_parameter_names", "Integer input / Float input"),
                    ("step_default", "Input function parameters / step"),
                    ("confirm_default", "Input function parameters / confirm"),
                    ("display_default", "Input function parameters / display"),
                    ("active_default_and_qualifier", "Input function parameters / active"),
                )
            ]
    return {
        "guard_basis": "LOCAL_CATALOG_INVARIANT",
        "external_contract_complete": False,
        "status": "UNVERIFIED",
        "coverage_ratio_basis": "local_checks_not_external_requirements",
        "externally_evidenced": evidenced,
        "unresolved": unresolved,
        "local_only_conventions": [
            "symbol_id",
            "overload_id",
            "default_serialization",
            "options_array_type_encoding",
            "allow_extra_positional",
        ],
        "remaining_obligations": "Full numeric authority and full CAT-01–04 remain open; no mandatory dimension is waived.",
    }


def _required_contract(version: int, dtype: str) -> dict[str, Any]:
    # LOCAL exact representation only. v5 display and float return authority
    # conflicts are unresolved; do not change catalogs or infer external proof.
    head = [_parameter("defval", dtype, required=True), _parameter("title", "string", default="")]
    tail = [
        _parameter("tooltip", "string", default=""),
        _parameter("inline", "string", default=""),
        _parameter("group", "string", default=""),
        _parameter("confirm", "bool", default=False),
    ]
    if version == 6:
        tail += [
            _parameter("display", "display", default="display.all"),
            _parameter("active", "bool", qualifier="input", default=True),
        ]
    name = f"input.{dtype}"
    return {
        "symbol_id": f"pine:function:{name}",
        "name": name,
        "allow_extra_positional": False,
        "parameters": [
            *head,
            _parameter("minval", dtype),
            _parameter("maxval", dtype),
            _parameter("step", dtype, default=1),
            *tail,
        ],
        "returns": dtype,
        "return_qualifier": "input",
        "overloads": [
            {
                "overload_id": f"pine:function:{name}#overload:0",
                "parameters": [
                    *head,
                    _parameter("options", f"array<{dtype}>", required=True),
                    *tail,
                ],
                "returns": dtype,
                "return_qualifier": "input",
            }
        ],
    }


def _differences(actual: Any, expected: Any, path: str) -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, Mapping):
            return [path]
        differences = []
        for key, value in expected.items():
            differences.extend(_differences(actual.get(key, _MISSING), value, f"{path}.{key}"))
        # Absence is part of the fixed local callable shape. An overload can
        # override the canonical arity policy, and version gates or variadic
        # parameters can change admission even when every expected key matches.
        # Unrelated annotations remain outside this guard.
        for key in ("default", "allow_extra_positional", "variadic", "added_in", "removed_in"):
            if key not in expected and key in actual:
                differences.append(f"{path}.{key}")
        return differences
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [path]
        return [
            difference
            for index, (left, right) in enumerate(zip(actual, expected))
            for difference in _differences(left, right, f"{path}[{index}]")
        ]
    # Python equality alone aliases False/0 and True/1, hiding corrupt defaults.
    return [] if type(actual) is type(expected) and actual == expected else [path]


def required_numeric_input_gaps(
    version: int, sections: Mapping[str, Any]
) -> tuple[int, list[dict[str, Any]]]:
    """Compare a fixed required slice, including negative version membership."""
    functions = sections.get("functions")
    functions = functions if isinstance(functions, Mapping) else {}
    gaps: list[dict[str, Any]] = []
    checked = 0
    for dtype in ("int", "float"):
        name = f"input.{dtype}"
        path = f"sections.functions.{name}"
        if version <= 4:
            differences = [path] if name in functions else []
        else:
            differences = _differences(
                functions.get(name), _required_contract(version, dtype), path
            )
        if not differences:
            checked += 1
        for difference in differences:
            gaps.append(
                {
                    "code": "REQUIRED_INPUT_CONTRACT",
                    "path": difference,
                    "basis": "LOCAL_CATALOG_INVARIANT",
                    "message": f"Pine v{version}: local numeric-input invariant mismatch (not external authority proof)",
                }
            )
    return checked, gaps
