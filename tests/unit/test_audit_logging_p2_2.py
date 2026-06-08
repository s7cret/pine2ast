"""P2.2 security audit logging contract.

The hook is opt-in. When ``ParseOptions.security_audit_hook`` is
``None`` (the default), no audit work happens. When set, the runner
filters diagnostics to the security-tier whitelist and invokes the
hook once per match. A buggy hook is contained: the parse path
completes normally and the diagnostic is still in the result.

Markers:
  - default: all tests run on every push.
"""

from __future__ import annotations

import os
import pytest

from pine2ast import audit
from pine2ast.api import ParseOptions, parse_code, parse_file

# ---------------------------------------------------------------------------
# audit module: whitelist + make_event
# ---------------------------------------------------------------------------


def test_security_audit_codes_includes_known_codes() -> None:
    expected = {
        "P2A1106",
        "P2A1107",
        "P2A1108",
        "P2A1109",
        "P2A1110",
        "P2A1111",
        "P2A1112",
        "P2A1113",
        "P2A9001",
        "P2A9002",
        "P2A9003",
        "P2A9201",
    }
    assert expected.issubset(audit.SECURITY_AUDIT_CODES)


def test_is_security_audit_code_filters_correctly() -> None:
    assert audit.is_security_audit_code("P2A1109") is True
    assert audit.is_security_audit_code("P2A9201") is True
    # Non-security codes are rejected.
    assert audit.is_security_audit_code("P2A0501") is False  # SYNTAX_ERROR
    assert audit.is_security_audit_code("P2A1101") is False  # UNDECLARED_VARIABLE


def test_make_event_serializes_span_and_severity() -> None:
    from pine2ast.diagnostics import Diagnostic, Severity
    from pine2ast.lexer.token import SourceSpan

    diag = Diagnostic(
        Severity.FATAL,
        "P2A1109",
        "Unknown runtime_contract_profile: 'pwn'",
        SourceSpan(
            start_offset=0, end_offset=10, start_line=1, start_col=1, end_line=1, end_col=11
        ),
    )
    ev = audit.make_event(diag, source_name="<memory>")
    d = ev.to_dict()
    assert d["code"] == "P2A1109"
    assert d["severity"] == "FATAL"
    assert d["span_start"] == 0
    assert d["span_end"] == 10
    assert d["source_name"] == "<memory>"
    assert "timestamp" in d
    assert "pwn" in d["message"]


# ---------------------------------------------------------------------------
# AuditHookRunner
# ---------------------------------------------------------------------------


def test_runner_no_hook_is_noop() -> None:
    runner = audit.AuditHookRunner(None)
    from pine2ast.diagnostics import Diagnostic, Severity
    from pine2ast.lexer.token import SourceSpan

    diag = Diagnostic(Severity.FATAL, "P2A1109", "x", SourceSpan.zero())
    runner.emit(diag, source_name="<memory>")
    assert runner.observed == 0


def test_runner_skips_non_security_codes() -> None:
    seen: list[str] = []
    runner = audit.AuditHookRunner(lambda e: seen.append(e.code))
    from pine2ast.diagnostics import Diagnostic, Severity
    from pine2ast.lexer.token import SourceSpan

    diag = Diagnostic(Severity.ERROR, "P2A0501", "syntax", SourceSpan.zero())
    runner.emit(diag, source_name="<memory>")
    assert seen == []
    assert runner.observed == 0


def test_runner_emits_security_codes() -> None:
    seen: list[audit.SecurityAuditEvent] = []
    runner = audit.AuditHookRunner(lambda e: seen.append(e))
    from pine2ast.diagnostics import Diagnostic, Severity
    from pine2ast.lexer.token import SourceSpan

    diag = Diagnostic(Severity.FATAL, "P2A9201", "refusing", SourceSpan.zero())
    runner.emit(diag, source_name="/some/path")
    assert len(seen) == 1
    assert seen[0].code == "P2A9201"
    assert seen[0].source_name == "/some/path"
    assert runner.observed == 1


def test_runner_swallows_hook_exceptions() -> None:
    def bad(ev: audit.SecurityAuditEvent) -> None:
        raise RuntimeError("audit pipeline on fire")

    runner = audit.AuditHookRunner(bad)
    from pine2ast.diagnostics import Diagnostic, Severity
    from pine2ast.lexer.token import SourceSpan

    diag = Diagnostic(Severity.FATAL, "P2A1109", "x", SourceSpan.zero())
    # Must not raise. The parse path depends on the runner being
    # exception-safe.
    runner.emit(diag, source_name="<memory>")


# ---------------------------------------------------------------------------
# parse_code integration
# ---------------------------------------------------------------------------


def test_parse_code_calls_hook_on_profile_reject() -> None:
    seen: list[audit.SecurityAuditEvent] = []

    def hook(ev: audit.SecurityAuditEvent) -> None:
        seen.append(ev)

    r = parse_code(
        '//@version=6\nindicator("x")',
        ParseOptions(runtime_contract_profile="pwn", security_audit_hook=hook),
    )
    assert r.ast is None
    assert len(seen) == 1
    assert seen[0].code == "P2A1109"


def test_parse_code_calls_hook_on_overflow() -> None:
    seen: list[audit.SecurityAuditEvent] = []
    parse_code(
        '//@version=6\nindicator("x")\nplot(1e500)',
        ParseOptions(security_audit_hook=seen.append),
    )
    assert any(e.code == "P2A1110" for e in seen)


def test_parse_code_calls_hook_on_control_char() -> None:
    seen: list[audit.SecurityAuditEvent] = []
    parse_code(
        '//@version=6\nindicator("x")',
        ParseOptions(source_name="bad\x00name", security_audit_hook=seen.append),
    )
    assert any(e.code == "P2A1107" for e in seen)


def test_parse_code_calls_hook_on_long_source_name() -> None:
    seen: list[audit.SecurityAuditEvent] = []
    parse_code(
        '//@version=6\nindicator("x")',
        ParseOptions(source_name="a" * 1000, security_audit_hook=seen.append),
    )
    assert any(e.code == "P2A1106" for e in seen)


def test_parse_code_does_not_call_hook_on_normal_parse() -> None:
    seen: list[audit.SecurityAuditEvent] = []
    parse_code(
        '//@version=6\nindicator("x")\nplot(close)',
        ParseOptions(security_audit_hook=seen.append),
    )
    assert seen == []


def test_parse_code_does_not_call_hook_on_syntax_error() -> None:
    # A syntax error is NOT a security event. Hook stays silent.
    seen: list[audit.SecurityAuditEvent] = []
    parse_code(
        '//@version=6\nindicator("x"\nplot(close)',  # missing )
        ParseOptions(security_audit_hook=seen.append),
    )
    assert seen == []


def test_parse_code_buggy_hook_does_not_break_parse() -> None:
    def bad(ev: audit.SecurityAuditEvent) -> None:
        raise RuntimeError("siem down")

    # Must not raise. The diagnostic is still in the result.
    r = parse_code(
        '//@version=6\nindicator("x")\nplot(1e500)',
        ParseOptions(security_audit_hook=bad),
    )
    assert r.ast is None
    assert any(d.code == "P2A1110" for d in r.diagnostics)


def test_parse_code_sanitizes_source_name_in_event() -> None:
    seen: list[audit.SecurityAuditEvent] = []
    deep = "/home/u/" + "/".join(f"d{i}" for i in range(15)) + "/secret.pine"
    parse_code(
        '//@version=6\nindicator("x")',
        ParseOptions(source_name=deep, security_audit_hook=seen.append),
    )
    # We don't have a security-tier diagnostic here, so seen is
    # empty. But IF we did, source_name in the event would be the
    # sanitized form — we verify that by triggering a long-name
    # diagnostic with a deep path.
    long_deep = ("/home/u/" + "/".join(f"d{i}" for i in range(15)) + "/x.pine") + "a" * 1000
    seen.clear()
    parse_code(
        '//@version=6\nindicator("x")',
        ParseOptions(source_name=long_deep, security_audit_hook=seen.append),
    )
    assert seen
    # The full original path must NOT appear in the event.
    assert long_deep not in seen[0].source_name
    # It was sanitized to something shorter.
    assert len(seen[0].source_name) < len(long_deep)


# ---------------------------------------------------------------------------
# parse_file integration
# ---------------------------------------------------------------------------


def test_parse_file_calls_hook_on_symlink_reject(tmp_path: pytest.TempPathFactory) -> None:
    real = tmp_path / "real.pine"  # type: ignore[attr-defined]
    real.write_text('//@version=6\nindicator("x")\n')
    link = tmp_path / "link.pine"  # type: ignore[attr-defined]
    os.symlink(str(real), str(link))
    seen: list[audit.SecurityAuditEvent] = []
    r = parse_file(str(link), ParseOptions(security_audit_hook=seen.append))
    assert r.ast is None
    assert any(e.code == "P2A9201" for e in seen)
    # The path in the event should be sanitized.
    assert any(str(real) not in e.source_name for e in seen)
