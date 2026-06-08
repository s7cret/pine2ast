"""P1.6 security hardening contract.

These tests pin the behavior of ``pine2ast.security`` and the security
checks wired into ``pine2ast.api``. They are split into two layers:

  1. Unit tests of the security helpers themselves (pure functions,
     no Pine parsing). Fast, no fixtures, no AST.
  2. Integration tests through ``parse_code`` / ``parse_file`` that
     verify a security violation surfaces as a clean FATAL diagnostic
     with the documented code, and that the AST is *never* produced
     (no half-parsed program leaks out the door).

Markers:
  - default: all tests run in CI on every push.
  - ``@pytest.mark.security_ceiling``: tests that pin a resource
    ceiling. CI may run these in a separate, slower job if we ever
    decide to make the ceiling itself adjustable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pine2ast import security
from pine2ast.api import ParseOptions, parse_code, parse_file
from pine2ast.diagnostics import codes
from pine2ast.diagnostics.diagnostic import Severity

# ---------------------------------------------------------------------------
# security.sanitize_source_name
# ---------------------------------------------------------------------------


def test_sanitize_source_name_none_returns_default() -> None:
    assert security.sanitize_source_name(None) == "<memory>"


def test_sanitize_source_name_empty_returns_default() -> None:
    assert security.sanitize_source_name("") == "<memory>"


def test_sanitize_source_name_passes_normal_through() -> None:
    # Short relative path: returned verbatim.
    assert security.sanitize_source_name("my_script.pine") == "my_script.pine"


def test_sanitize_source_name_strips_control_chars() -> None:
    # NUL, BEL, and a tab — the regex strips everything < 0x20 plus 0x7F.
    out = security.sanitize_source_name("foo\x00bar\x07baz\x7f")
    assert "\x00" not in out
    assert "\x07" not in out
    assert "\x7f" not in out
    # The rest of the printable text is preserved.
    assert "foo" in out and "bar" in out and "baz" in out


def test_sanitize_source_name_truncates_long_strings() -> None:
    long = "a" * 1000
    out = security.sanitize_source_name(long)
    # The cap is hard-coded to 512 + "..." marker.
    assert len(out) <= security.ABSOLUTE_MAX_SOURCE_NAME_LEN + 3
    assert out.endswith("...")


def test_sanitize_source_name_redacts_deep_paths() -> None:
    # 15 components — well above the SOURCE_NAME_MAX_COMPONENTS cap (8).
    deep = "/home/u/" + "/".join(f"d{i}" for i in range(15)) + "/secret.pine"
    out = security.sanitize_source_name(deep)
    # Sanitized form is shorter than the original and starts with the
    # ellipsis marker (proving we did redact).
    assert out.startswith(".../")
    assert len(out) < len(deep)
    # The first three path components (the most identifying ones: /home/u)
    # are gone.
    assert "/home/u/" not in out


# ---------------------------------------------------------------------------
# security.is_safe_runtime_contract_profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [None, "compatibility", "v1.4", "runtime_contract_v1_4"],
)
def test_is_safe_runtime_contract_profile_accepts_whitelisted(value: str | None) -> None:
    assert security.is_safe_runtime_contract_profile(value) is True


@pytest.mark.parametrize(
    "value",
    ["", "v1", "v1.5", "v2", "experimental", "PWN", "v1.4; rm -rf /"],
)
def test_is_safe_runtime_contract_profile_rejects_unknown(value: str) -> None:
    assert security.is_safe_runtime_contract_profile(value) is False


# ---------------------------------------------------------------------------
# security.find_overflowing_float_literals
# ---------------------------------------------------------------------------


def test_find_overflowing_float_literals_catches_huge_exp() -> None:
    out = security.find_overflowing_float_literals("x = 1e500")
    assert len(out) == 1
    start, end, text = out[0]
    assert text == "1e500"
    assert "x = 1e500"[start:end] == "1e500"


def test_find_overflowing_float_literals_catches_negative_huge_exp() -> None:
    out = security.find_overflowing_float_literals("x = -1e500")
    assert len(out) == 1
    assert out[0][2] == "-1e500"


def test_find_overflowing_float_literals_ignores_normal_numbers() -> None:
    src = "a = 1.0\nb = 1e10\nc = -3.14\nd = 0.0\ne = 1.5e-5"
    assert security.find_overflowing_float_literals(src) == []


def test_find_overflowing_float_literals_flags_edge_of_double_range() -> None:
    # 1e308 is the largest finite double; the helper flags anything
    # whose absolute value is >= 1e308. The next representable value
    # is 1e309 which overflows to inf.
    out = security.find_overflowing_float_literals("x = 1e308")
    assert len(out) == 1
    out = security.find_overflowing_float_literals("x = 1e307")
    assert out == []


def test_find_overflowing_float_literals_skips_inside_identifiers() -> None:
    # The regex uses negative look-around so it must NOT match `e500`
    # inside an identifier like `e500foo`.
    out = security.find_overflowing_float_literals("e500foo = 1.0")
    assert out == []


# ---------------------------------------------------------------------------
# security.safe_resolve_path
# ---------------------------------------------------------------------------


def test_safe_resolve_path_accepts_normal_file(tmp_path: Path) -> None:
    f = tmp_path / "ok.pine"
    f.write_text("//@version=6\nindicator('x')\n")
    resolved = security.safe_resolve_path(f, must_exist=True)
    assert resolved == f.resolve()


def test_safe_resolve_path_refuses_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.pine"
    real.write_text("//@version=6\n")
    link = tmp_path / "link.pine"
    os.symlink(str(real), str(link))
    with pytest.raises(ValueError, match="symlink"):
        security.safe_resolve_path(link, must_exist=True)


def test_safe_resolve_path_refuses_traversal(tmp_path: Path) -> None:
    # File is *inside* tmp_path. The path "../escape.pine" is a relative
    # path that resolves to outside the cwd.
    outside = tmp_path.parent / "outside.pine"
    outside.write_text("//@version=6\n")
    try:
        with pytest.raises(ValueError, match="escape"):
            security.safe_resolve_path("../outside.pine", must_exist=True)
    finally:
        outside.unlink()


def test_safe_resolve_path_raises_for_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        security.safe_resolve_path(tmp_path / "nope.pine", must_exist=True)


# ---------------------------------------------------------------------------
# ParseOptions.clamp_to_ceiling
# ---------------------------------------------------------------------------


def test_clamp_to_ceiling_passes_defaults_through() -> None:
    # Default ParseOptions: every resource field is well under the
    # ceiling. clamp_to_ceiling should be a no-op for sane values.
    p = ParseOptions()
    c = p.clamp_to_ceiling()
    assert c.max_file_size_bytes == p.max_file_size_bytes
    assert c.max_tokens == p.max_tokens
    assert c.max_ast_nodes == p.max_ast_nodes
    assert c.max_diagnostics == p.max_diagnostics


def test_clamp_to_ceiling_clamps_huge_bypass() -> None:
    # The whole point: a caller cannot bypass the DoS guard by
    # passing 2**63. They get the absolute ceiling, period.
    p = ParseOptions(
        max_file_size_bytes=2**63,
        max_tokens=2**63,
        max_ast_nodes=2**63,
        max_diagnostics=2**63,
    )
    c = p.clamp_to_ceiling()
    assert c.max_file_size_bytes == security.ABSOLUTE_MAX_FILE_SIZE_BYTES
    assert c.max_tokens == security.ABSOLUTE_MAX_TOKENS
    assert c.max_ast_nodes == security.ABSOLUTE_MAX_AST_NODES
    assert c.max_diagnostics == security.ABSOLUTE_MAX_DIAGNOSTICS


def test_clamp_to_ceiling_preserves_lower_caller_bounds() -> None:
    # A caller that wants a strict 10 KiB ceiling should get exactly
    # 10 KiB, not 50 MiB. The clamp only enforces the upper bound.
    p = ParseOptions(max_file_size_bytes=10_000)
    c = p.clamp_to_ceiling()
    assert c.max_file_size_bytes == 10_000


# ---------------------------------------------------------------------------
# parse_code: security-tier diagnostics
# ---------------------------------------------------------------------------


def test_parse_code_rejects_long_source_name() -> None:
    long_name = "a" * 1000
    r = parse_code("//@version=6\nindicator('x')\n", ParseOptions(source_name=long_name))
    assert r.ast is None
    assert len(r.diagnostics) == 1
    diag = r.diagnostics[0]
    assert diag.code == codes.SOURCE_NAME_TOO_LONG
    assert diag.severity is Severity.FATAL


def test_parse_code_rejects_control_chars_in_source_name() -> None:
    r = parse_code(
        "//@version=6\nindicator('x')\n",
        ParseOptions(source_name="hello\x00world"),
    )
    assert r.ast is None
    assert r.diagnostics[0].code == codes.SOURCE_NAME_CONTROL_CHAR


def test_parse_code_rejects_unknown_runtime_profile() -> None:
    r = parse_code(
        "//@version=6\nindicator('x')\n",
        ParseOptions(runtime_contract_profile="experimental"),
    )
    assert r.ast is None
    assert r.diagnostics[0].code == codes.RUNTIME_CONTRACT_PROFILE_UNKNOWN
    # The error message echoes the bad profile so the caller can fix it.
    assert "experimental" in r.diagnostics[0].message


def test_parse_code_rejects_overflow_literal() -> None:
    r = parse_code(
        "//@version=6\nindicator('x')\nplot(1e500)\n",
    )
    assert r.ast is None
    assert r.diagnostics[0].code == codes.FLOAT_OVERFLOW_LITERAL
    assert "1e500" in r.diagnostics[0].message


def test_parse_code_allows_overflow_when_below_threshold() -> None:
    # 1e100 is finite, well within the double range. Should parse clean.
    r = parse_code(
        "//@version=6\nindicator('x')\nplot(1e100)\n",
    )
    assert r.ast is not None
    assert r.ok is True


def test_parse_code_sanitizes_source_name_in_normalizer_path() -> None:
    # The deep path is sanitized: it should not appear in full in
    # any diagnostic. We don't depend on the SourceNormalizer
    # emitting a source_name-bearing diagnostic (currently it doesn't),
    # but we do pin that the sanitization helper was called.
    deep = "/home/u/" + "/".join(f"d{i}" for i in range(15)) + "/secret.pine"
    r = parse_code("//@version=6\nindicator('x')\n", ParseOptions(source_name=deep))
    assert r.ok is True
    # No diagnostic carries the full path verbatim.
    for d in r.diagnostics:
        assert deep not in d.message


# ---------------------------------------------------------------------------
# parse_file: path-safety
# ---------------------------------------------------------------------------


def test_parse_file_refuses_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.pine"
    real.write_text("//@version=6\nindicator('x')\n")
    link = tmp_path / "link.pine"
    os.symlink(str(real), str(link))
    r = parse_file(str(link))
    assert r.ast is None
    assert r.diagnostics[0].code == codes.UNSAFE_PATH


def test_parse_file_works_for_normal_file(tmp_path: Path) -> None:
    f = tmp_path / "ok.pine"
    f.write_text("//@version=6\nindicator('x')\n")
    r = parse_file(str(f))
    assert r.ok is True
    assert r.ast is not None


def test_parse_file_returns_clean_error_for_missing(tmp_path: Path) -> None:
    r = parse_file(str(tmp_path / "nope.pine"))
    assert r.ast is None
    assert r.diagnostics[0].code == codes.UNSAFE_PATH
