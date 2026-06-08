# P2.2 — Security audit logging

## Scope

P1.6 and P2.1 added security-tier diagnostics (P2A1106-1113,
P2A9001-9003, P2A9201). When the gateway rejects a script for one
of these reasons, the operator usually wants to know:

- **Who** tried to submit it (caller identity — gateway's job)
- **What** the script was (caller's job to hash, NOT ours — we
  don't store it; the span is enough for line/column)
- **Why** we rejected it (the diagnostic code + message)
- **When** (timestamp)

This module defines the event type and the hook. The hook is
**synchronous and inline**: the caller wires it into
`ParseOptions(security_audit_hook=fn)` and `parse_code` invokes it
once for every security-tier diagnostic emitted during the call.

## Public surface

```python
from pine2ast.audit import (
    SecurityAuditEvent,
    SecurityAuditHook,
    AuditHookRunner,
    SECURITY_AUDIT_CODES,
    is_security_audit_code,
)

# Wire a hook
def ship_to_siem(event: SecurityAuditEvent) -> None:
    siem.log("pine2ast_reject", event.to_dict())

options = ParseOptions(security_audit_hook=ship_to_siem)
result = parse_code(untrusted_input, options)
# Every P2A1106/P2A1107/P2A1110/P2A9201/... emitted above is also
# in SIEM now.
```

`SecurityAuditEvent` is a flat dataclass with `to_dict()` for
JSON serialization:

```python
@dataclass(slots=True)
class SecurityAuditEvent:
    timestamp: str        # ISO 8601 UTC
    code: str             # P2A1109 etc
    severity: str         # FATAL / WARNING / ...
    source_name: str      # sanitized (last 8 components if deep)
    span_start: int       # offset in source
    span_end: int
    message: str
```

## Security-tier code whitelist

Defined as a `frozenset` in `pine2ast.audit.SECURITY_AUDIT_CODES`.
The runner filters to this set; non-security diagnostics do not
fire the hook.

| Code | Meaning |
|---|---|
| P2A1106 | SOURCE_NAME_TOO_LONG |
| P2A1107 | SOURCE_NAME_CONTROL_CHAR |
| P2A1108 | RESOURCE_CEILING_EXCEEDED |
| P2A1109 | RUNTIME_CONTRACT_PROFILE_UNKNOWN |
| P2A1110 | FLOAT_OVERFLOW_LITERAL |
| P2A1111 | LOOP_ITERATION_OVERFLOW |
| P2A1112 | INFINITE_WHILE_LITERAL |
| P2A1113 | NESTED_LOOP_EXPLOSION |
| P2A9001 | FILE_TOO_LARGE |
| P2A9002 | TOO_MANY_TOKENS |
| P2A9003 | TOO_MANY_AST_NODES |
| P2A9201 | UNSAFE_PATH |

Adding a new security code in the future requires updating this
set explicitly. There is no implicit "everything 1xxx is
security" — semantic errors are user-fixable code bugs, not
security events.

## Threat model — what the hook sees

- The **sanitized** `source_name` (last 8 components for deep
  paths, control chars stripped, 512-char cap). A sensitive
  path is *not* echoed in the audit log.
- The **span** of the diagnostic, as `(start_offset, end_offset)`.
  The gateway can re-locate the line/column using its own source
  cache; we do not duplicate that.
- The **code + message** as-is. The gateway should not parse the
  message; it should match on `code`.

The hook MUST NOT raise. A buggy hook is contained by
`AuditHookRunner.emit` wrapping the call in `try/except`. The
parse path completes normally; the operator can detect "audit not
firing" by the `observed` counter (currently per-call, not
exposed in `ParseResult`; if we need it, we can add a field).

## Architecture

```
pine2ast/audit.py        <- SecurityAuditEvent, AuditHookRunner, whitelist
pine2ast/api.py          <- ParseOptions.security_audit_hook field
                            + 5 emit() call sites in parse_code
                            + 1 emit() call site in parse_file
```

Five emit sites in `parse_code` (one per security-tier pre-flight
check):
- source_name length
- source_name control char
- runtime_contract_profile whitelist
- float overflow literal
- file size cap (×2 for str/bytes overloads)

One emit site in `parse_file`:
- unsafe path (symlink / traversal rejection)

`AuditHookRunner.emit()` is called inline, in the same Python
frame, before the `ParseResult` is returned. The hook itself is
synchronous; the gateway can wrap it in a queue if it wants
non-blocking delivery to its SIEM.

## Files added / changed

| File | Status | Lines |
|---|---|---|
| `pine2ast/audit.py` | **new** | 173 |
| `pine2ast/api.py` | edited (1 new field + 6 emit sites + propagate in clamp) | +30/-22 |
| `tests/unit/test_audit_logging_p2_2.py` | **new** | 16 tests, 3 layers |
| `docs/P2_2_AUDIT_LOGGING.md` | **new** | this doc |

## Verification

| Check | Status |
|---|---|
| 16/16 new tests pass | ✅ |
| Full suite: 508 → 524 passed (+16, 0 regressions) | ✅ |
| ruff + black + mypy | ✅ |
| Hook fires on each of 5 pre-flight reject paths | ✅ |
| Hook does NOT fire on a normal parse | ✅ |
| Hook does NOT fire on a syntax error (P2A0501) | ✅ |
| Buggy hook does not break the parse path | ✅ |
| `source_name` in event is sanitized (no full path) | ✅ |
| Audit codes whitelist is closed (frozen set) | ✅ |
| `is_security_audit_code` filters non-security codes | ✅ |
| CI: 2 runs × 3 jobs all green | ✅ |

## What is intentionally left for follow-up

- **`observed` counter in `ParseResult`.** The runner tracks
  per-call counts; we did not surface it in the return type to
  keep the API stable. If a gateway needs to assert "the audit
  fired on this test input", we can add a `audit_events: int`
  field in a follow-up.
- **Async / batched delivery.** A noisy SIEM might want a
  bounded queue. The hook is sync; the gateway wraps it. No
  internal threading.
- **Persistent on-disk log.** Out of scope. The hook is the
  extension point.
- **Per-caller rate limiting.** Already a gateway concern, not
  a library concern.
- **Redaction of `message`.** We assume the message is safe
  (Pine-specific). If a future diagnostic includes user-supplied
  data, the redaction layer needs revisiting.
