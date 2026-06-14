from __future__ import annotations

from importlib.resources import files

from pine2ast import ParseOptions, ParsePipeline, parse_code, pine_language_profile
from pine2ast.diagnostics import Severity, codes
from pine2ast.reference_catalog.official_reference import (
    load_official_reference_index,
    official_reference_diff_payload,
)


def _error_codes(source: str, options: ParseOptions | None = None) -> set[str]:
    result = parse_code(source, options)
    return {
        diag.code
        for diag in result.diagnostics
        if diag.severity in {Severity.ERROR, Severity.FATAL}
    }


def test_native_v5_profile_does_not_emit_v6_compatibility_warning() -> None:
    result = parse_code(
        """//@version=5
indicator("native v5")
plot(close)
""",
        ParseOptions(version=5),
    )

    assert result.ok
    assert result.ast is not None
    assert result.ast.version == 5
    assert not any(diag.code == codes.UNSUPPORTED_VERSION for diag in result.diagnostics)


def test_legacy_v5_compat_mode_still_warns_for_default_v6_target() -> None:
    result = parse_code(
        """//@version=5
indicator("compat")
plot(close)
""",
        ParseOptions(strict_v6=False),
    )

    assert result.ok
    assert any(
        diag.code == codes.UNSUPPORTED_VERSION and diag.severity is Severity.WARNING
        for diag in result.diagnostics
    )


def test_v5_and_v6_profiles_have_different_bool_rules() -> None:
    source = """//@version=5
indicator("legacy bool")
if close
    x = 1
bool b = na
"""
    assert not (
        _error_codes(source, ParseOptions(version=5))
        & {
            codes.NON_BOOL_CONDITION,
            codes.BOOL_CANNOT_BE_NA,
            codes.NA_IN_BOOL_CONTEXT,
        }
    )

    v6_source = source.replace("//@version=5", "//@version=6")
    assert codes.NON_BOOL_CONDITION in _error_codes(v6_source)
    assert codes.BOOL_CANNOT_BE_NA in _error_codes(v6_source)


def test_dynamic_requests_parameter_is_known_on_declarations() -> None:
    for declaration in ("indicator", "strategy", "library"):
        extra = "\nexport f() => 1" if declaration == "library" else "\nplot(close)"
        source = f'//@version=6\n{declaration}("dynamic", dynamic_requests=false){extra}\n'
        assert codes.UNKNOWN_PARAMETER not in _error_codes(source)


def test_exported_const_can_use_const_math_call() -> None:
    result = parse_code("""//@version=6
library("MyConstants")
export const float SILVER_RATIO = 1.0 + math.sqrt(2)
""")

    assert result.ok
    assert codes.QUALIFIER_MISMATCH not in {diag.code for diag in result.diagnostics}


def test_parse_pipeline_stage_api_is_public() -> None:
    pipeline = ParsePipeline(ParseOptions(run_semantic=False, collect_tokens=True))
    tokens, diagnostics = pipeline.lex_only('//@version=6\nindicator("x")\n')
    assert tokens
    assert diagnostics == []
    parsed = pipeline.parse_only(tokens)
    assert parsed.program is not None


def test_language_profile_flags_are_explicit() -> None:
    v5 = pine_language_profile(5)
    v6 = pine_language_profile(6)
    assert v5.version == 5
    assert v5.bool_allows_na is True
    assert v5.supports_dynamic_requests_default is False
    assert v6.version == 6
    assert v6.bool_allows_na is False
    assert v6.supports_dynamic_requests_default is True


def test_official_reference_diff_is_version_aware_and_category_complete() -> None:
    index = load_official_reference_index(
        str(files("pine2ast.reference_catalog").joinpath("official_pine_v6_reference_index.json"))
    )
    payload = official_reference_diff_payload(index)

    assert payload["pine_version"] == 6
    assert set(payload["missing_by_category"]) >= {
        "functions",
        "variables",
        "methods",
        "constants",
        "types",
        "operators",
        "keywords",
        "annotations",
    }
    assert payload["summary"]["missing_official_count"] == 0
    assert payload["coverage_axes"]["runtime_out_of_scope"]
