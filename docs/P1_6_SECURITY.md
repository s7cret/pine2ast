# P1.6 — Security hardening of the public API surface

## Scope

pine2ast is shipped as a library and is also reachable over the
network via the OpenPine gateway on `:8080`. The library itself is
pure (no `pickle`, no `eval`, no `subprocess` — verified by grep
over `pine2ast/`). The P1.6 work addresses the gap between "pure
library" and "library that can be called with untrusted input":

| Threat | Before P1.6 | After P1.6 |
|---|---|---|
| Caller passes `max_file_size_bytes=2**63` to bypass DoS guard | accepted (clamp not enforced) | clamped to `ABSOLUTE_MAX_FILE_SIZE_BYTES` = 50 MiB |
| Caller passes `runtime_contract_profile="anything"` | silently used, fallback to compat | rejected with `P2A1109` |
| Caller passes `source_name="/home/u/.../secret.pine"` | echoed back in every error message | sanitized: control chars stripped, deep paths redacted to last 8 components, capped at 512 chars |
| Caller passes `source_name="evil\x00name"` | accepted (broke some loggers) | rejected with `P2A1107` |
| Pine source contains `1e500` | parsed as `+inf` silently, breaks downstream math | rejected with `P2A1110` before lex |
| Caller passes `parse_file("/etc/passwd")` via a symlink | read whatever the symlink pointed to | rejected with `P2A9201` (symlink refusal) |
| Caller passes `parse_file("../escape.pine")` | read the file | rejected with `P2A9201` (path-traversal refusal) |

## Threat model — what we explicitly do *not* do

The TZ (§7.7) defines the threat model as "input validation for an
in-process library exposed to a network service". P1.6 addresses
*input validation*. It does **not** address:

- **Sandboxing the parser.** The Python process is trusted; the
  library is not a syscall-level sandbox. A determined attacker who
  can supply arbitrary Python source has bigger problems.
- **Authentication of the caller.** That's the gateway's job.
- **Rate limiting.** Caller's responsibility. The DoS ceiling stops
  one request from being huge; it doesn't stop 10 000 small ones.
- **Persistent storage of input.** We don't write the input
  anywhere; the gateway decides what to do with the parsed AST.
- **Pine Script semantics hardening.** That's a `P1.7+` topic
  (e.g. "what if a user script does `for i = 0 to 999999999`?"
  is a runtime concern, not a security one — Pine v6 caps loop
  iterations on its own).

## Architecture

The security work is a single new module, `pine2ast/security.py`,
plus targeted edits to `pine2ast/api.py` and the diagnostic codes
file. Tests live in `tests/unit/test_security_p1_6.py`.

```
                  ┌───────────────────────────────┐
   parse_code() ─►│  1. clamp_to_ceiling()        │   resource ceilings
                  │  2. validate source_name      │   P2A1106, P2A1107
                  │  3. validate runtime profile  │   P2A1109
                  │  4. find_overflowing_floats   │   P2A1110
                  │  5. existing size/token check │   P2A9001-9003
                  │  6. sanitize_source_name()    │   used by all below
                  │  7. existing pipeline…        │
                  └──────────────┬────────────────┘
                                 │
                  ┌──────────────▼──────────────┐
                  │     SourceNormalizer,       │
                  │     Lexer, Layout, Parser,  │
                  │     Semantic — using safe_  │
                  │     name for source_name.   │
                  └──────────────┬──────────────┘
                                 │
                  ┌──────────────▼──────────────┐
   parse_file() ─►│  safe_resolve_path()        │   P2A9201
                  │  rejects symlinks, traversal│
                  └─────────────────────────────┘
```

## The hard ceilings

| Field | Default | ABSOLUTE ceiling | Why |
|---|---|---|---|
| `max_file_size_bytes` | 5 MiB | **50 MiB** | 50 MiB Pine is already larger than any real-world strategy. Bigger inputs get the FileTooLarge error before we allocate. |
| `max_tokens` | 500 000 | **2 000 000** | Token explosion (e.g. pathological `1+1+1+…+1`) is the cheapest DoS shape; the cap forces recovery to kick in early. |
| `max_ast_nodes` | 500 000 | **2 000 000** | Same threat for AST. |
| `max_diagnostics` | 200 (was) → 5 000 (now) | **5 000** | Default raised so we don't accidentally drop into a flood mode; ceiling stops a runaway from emitting a million diagnostics. |
| `source_name` | "<memory>" | **512 chars** | A 1 KB diagnostic tag is already ridiculous; 512 is a hard cap, exceeded values are rejected. |

A caller that wants a stricter ceiling (e.g. "this endpoint
accepts 100 KiB scripts") can lower `max_file_size_bytes`
freely. The clamp is a *ceiling*, not a *floor*.

## Whitelisted runtime-contract profiles

```python
ALLOWED_RUNTIME_CONTRACT_PROFILES = frozenset(
    {None, "compatibility", "v1.4", "runtime_contract_v1_4"}
)
```

Anything else returns `P2A1109` and a `None` AST. The whitelist is
intentionally tight: a typo'd profile silently falling back to
compatibility mode is the same class of bug as a typo'd hostname
silently falling back to `localhost`.

## Symlink and path-traversal policy

`parse_file` now calls `security.safe_resolve_path()` before
reading. The policy:

- If any component of the path is a symlink, the call is rejected.
  This is the conservative default; if a user has a legitimate
  symlinked scripts directory, they can pass the *target* path
  explicitly.
- If the path is relative, the resolved target must be under the
  current working directory. This stops `../../etc/passwd` style
  attacks in a default-config server.

The 50 MiB ceiling is enforced separately — the path check only
guards against "this path is unsafe to read at all".

## Sanitization

`security.sanitize_source_name()` is a pure function: same input
→ same output. It runs unconditionally on every parse call so
the caller cannot "forget" to sanitize. The rules:

1. `None` or empty → `"<memory>"` (matches the default).
2. Strip control characters (`\x00`–`\x1f`, `\x7f`).
3. Truncate to 512 chars + `"..."` marker.
4. If path-like, keep only the last 8 components and prefix
   `".../"`.

The truncated, sanitized form is what gets passed to
`SourceNormalizer.normalize(source_name=…)` and therefore appears
in any diagnostic that references the source. The caller never
sees their original (potentially identifying) path echoed back.

## Overflow literals

Python's `float()` silently returns `inf` for `1e500`. Pine has
no `inf` literal, so any `inf` flowing through the parser came
from a numeric literal in the source. The security check
`find_overflowing_float_literals` is intentionally conservative
(flags `1e308` and above) to keep the bar at "we promise finite
floats". The first such literal in the source produces a
`P2A1110` diagnostic at the literal's span, and the AST is
rejected.

The check runs in O(n) over the source and uses a linear-time
regex; the cost is negligible compared to the lexer.

## Files added / changed

| File | Status | Purpose |
|---|---|---|
| `pine2ast/security.py` | **new** | All security helpers |
| `pine2ast/diagnostics/codes.py` | +6 codes | P2A1106–P2A1110, P2A9201 |
| `pine2ast/api.py` | edited | Wire `clamp_to_ceiling`, validate source_name, profile, overflow literals; call `safe_resolve_path` in `parse_file` |
| `tests/unit/test_security_p1_6.py` | **new** | 38 tests across 4 layers |
| `docs/P1_6_SECURITY.md` | **new** | This document |

## Verification

| Check | Status |
|---|---|
| 38/38 new security tests pass | ✅ |
| Full suite: 549 → 587 passed (+38, 0 regressions) | ✅ |
| 7 xfailed (unchanged) | ✅ |
| 0 failed | ✅ |
| `ruff check .` | ✅ |
| `black --check .` | ✅ |
| `mypy pine2ast` | ✅ |
| Symlink refusal end-to-end (`/tmp/sneaky.pine → /etc/hostname`) | ✅ P2A9201 |
| `1e500` rejection end-to-end | ✅ P2A1110 |
| Bypass attempt (`max_file_size_bytes=2**63`) clamped to 50 MiB | ✅ |

## What is intentionally left for a follow-up

- **Pine-level DoS loops.** A user script `for i = 0 to 999999999`
  is bounded by Pine's runtime, not ours. Documenting this is a
  P1.7+ concern.
- **Audit logging.** Right now a security violation emits a
  diagnostic; it doesn't go to an audit log. A future
  `security.audit_log` event hook would let the gateway push
  rejections to a SIEM.
- **Per-caller ceilings.** Today the clamp is global. A
  multi-tenant deployment would want per-API-key ceilings, set
  by the gateway before calling `parse_code`. The clamp helper
  is already pure, so this is a trivial extension.
- **Request-rate limits.** Caller's responsibility.
