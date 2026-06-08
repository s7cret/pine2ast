"""P2.2: Security audit logging for parse_code / parse_file.

P1.6 and P2.1 added security-tier diagnostics (P2A1106-1113, P2A9201,
P2A9001-9003). When the gateway rejects a script for one of these
reasons, the operator usually wants to know:

  - who tried to submit it (caller identity — gateway's job to add)
  - what the script was (caller's job to hash, NOT ours — we don't
    store it; the span is enough for line/column)
  - why we rejected it (the diagnostic)
  - when (timestamp)

This module defines the event type and the hook. The hook is
synchronous and inline: the caller wires it into
``ParseOptions(security_audit_hook=fn)`` and ``parse_code`` invokes
it once for every security-tier diagnostic emitted during the call.
The caller decides whether to ship the event to a SIEM, a local
file, a logger, or just ``print``.

What this is NOT:

  - An async queue. We don't add background threads; the gateway
    can wrap the hook in a queue if it wants non-blocking delivery.
  - A persistent log. We don't write to disk.
  - A redaction layer. The diagnostic message has already been
    sanitized by ``security.sanitize_source_name``; the hook
    receives the sanitized form.

Example (gateway side):

.. code-block:: python

    from pine2ast.audit import SecurityAuditEvent

    def ship_to_siem(event: SecurityAuditEvent) -> None:
        siem.log("pine2ast_reject", event.to_dict())

    options = ParseOptions(security_audit_hook=ship_to_siem)
    result = parse_code(untrusted_input, options)
    # Every P2A1106/P2A1107/P2A1110/P2A9201/etc emitted above is
    # also in siem now.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from pine2ast.diagnostics import Diagnostic


# Diagnostic codes that constitute "security-tier" rejections. The
# gateway's SIEM rule fires only on these. We list them by code so
# that adding a new security code in the future requires updating
# this set explicitly (no implicit "everything 1xxx is security").
SECURITY_AUDIT_CODES: frozenset[str] = frozenset(
    {
        "P2A1106",  # SOURCE_NAME_TOO_LONG
        "P2A1107",  # SOURCE_NAME_CONTROL_CHAR
        "P2A1108",  # RESOURCE_CEILING_EXCEEDED
        "P2A1109",  # RUNTIME_CONTRACT_PROFILE_UNKNOWN
        "P2A1110",  # FLOAT_OVERFLOW_LITERAL
        "P2A1111",  # LOOP_ITERATION_OVERFLOW
        "P2A1112",  # INFINITE_WHILE_LITERAL
        "P2A1113",  # NESTED_LOOP_EXPLOSION
        "P2A9001",  # FILE_TOO_LARGE
        "P2A9002",  # TOO_MANY_TOKENS
        "P2A9003",  # TOO_MANY_AST_NODES
        "P2A9201",  # UNSAFE_PATH
    }
)


@dataclass(slots=True)
class SecurityAuditEvent:
    """A single security-tier rejection event.

    Fields are designed to be JSON-serializable so the gateway can
    ship them to a structured log / SIEM without further work.
    """

    timestamp: str
    code: str
    severity: str
    source_name: str
    span_start: int
    span_end: int
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "code": self.code,
            "severity": self.severity,
            "source_name": self.source_name,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "message": self.message,
        }


SecurityAuditHook = Callable[["SecurityAuditEvent"], None]


def is_security_audit_code(code: str) -> bool:
    """Return True if ``code`` is in the security audit set."""
    return code in SECURITY_AUDIT_CODES


def make_event(
    diagnostic: "Diagnostic",
    *,
    source_name: str,
) -> SecurityAuditEvent:
    """Build a SecurityAuditEvent from a Diagnostic + sanitized
    source name. The diagnostic's span is flattened to
    (start_offset, end_offset) for JSON-friendliness; line/col
    is recoverable on the consumer side from the source map if
    needed.

    ``diagnostic`` is duck-typed: we only read ``code``, ``severity``,
    ``span``, and ``message``. The Protocol-style import avoids a
    circular import between ``pine2ast.audit`` and
    ``pine2ast.diagnostics`` (which itself imports from
    ``pine2ast.lexer.token``).
    """
    span = diagnostic.span
    severity = diagnostic.severity
    return SecurityAuditEvent(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        code=diagnostic.code,
        severity=severity.name if hasattr(severity, "name") else str(severity),
        source_name=source_name,
        span_start=span.start_offset,
        span_end=span.end_offset,
        message=diagnostic.message,
    )


class AuditHookRunner:
    """Helper that safely invokes a security audit hook.

    The runner owns the contract: it filters diagnostics to the
    security tier, builds events, and wraps the call in a
    try/except so a buggy hook never breaks the parse path. The
    gateway can also call ``runner.observed`` to see how many
    events were emitted during a single ``parse_code`` call.
    """

    def __init__(self, hook: Optional[SecurityAuditHook]) -> None:
        self._hook = hook
        self.observed: int = 0

    def emit(self, diagnostic: "Diagnostic", *, source_name: str) -> None:
        """If ``diagnostic`` is security-tier, build an event and
        call the hook. Silently no-op for non-security diagnostics
        and for ``None`` hooks."""
        if self._hook is None:
            return
        if not is_security_audit_code(diagnostic.code):
            return
        event = make_event(diagnostic, source_name=source_name)
        try:
            self._hook(event)
            self.observed += 1
        except Exception:  # noqa: BLE001 — a buggy hook must not break the parse path
            # Intentionally swallow. The parse path must remain
            # robust even if the audit pipeline is broken. The
            # operator can detect "audit not firing" via the
            # ``observed`` counter on a known-bad input.
            pass
