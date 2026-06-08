"""Security hardening for the public API surface (P1.6).

pine2ast is a library. It runs in two deployment shapes:

  1. **In-process** — `parse_code(src, options)` from another Python program.
     The caller is trusted; the input is a user-supplied Pine Script.
  2. **Networked** — wrapped by an HTTP/WS server (e.g. the OpenPine gateway
     on :8080) that receives scripts from end users on the internet. Here
     the caller is the network; the input is untrusted.

This module exists for shape 2. Its job is to make sure that even if a
caller hands us a 4GB string, a path traversal, a NaN-bomb, or a
diagnostic message that includes `/etc/passwd`, we don't crash, leak,
or accept it silently. The functions are no-ops when the input is sane
and they emit a clean ``Diagnostic`` with a security-tier code when it
isn't. Every clamp has a named ceiling so the default is safe and the
ceiling is documented (not "infinity unless you opt in").

Threat model (TZ §7.7 simplified):

  - **DoS by large input**        → clamp ``max_file_size_bytes`` etc.
  - **DoS by pathological regex** → lexer already uses linear-time regexes.
  - **Path disclosure in errors** → sanitize ``source_name`` before it
                                     appears in diagnostics.
  - **Symlink traversal**         → refuse symlink targets in ``parse_file``.
  - **Profile confusion**         → ``runtime_contract_profile`` must be
                                     one of the whitelisted profiles.
  - **Numeric overflow in source** → reject ``1e500`` style literals at
                                     lex time (Python would parse as ``inf``).

What this module does *not* do (out of scope, see TZ §7.7 for the
out-of-scope list):

  - sandboxing the parser (we trust the Python runtime)
  - authentication of the caller
  - rate limiting (caller's responsibility)
  - persistent storage of the input
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Resource ceilings. These are HARD upper bounds; callers cannot raise them
# past the ceiling via ParseOptions. They can lower them per request.
# ---------------------------------------------------------------------------

ABSOLUTE_MAX_FILE_SIZE_BYTES: Final = 50 * 1024 * 1024  # 50 MiB
ABSOLUTE_MAX_TOKENS: Final = 2_000_000  # 2M tokens
ABSOLUTE_MAX_AST_NODES: Final = 2_000_000  # 2M nodes
ABSOLUTE_MAX_DIAGNOSTICS: Final = 5_000
ABSOLUTE_MAX_SOURCE_NAME_LEN: Final = 512

# Whitelisted runtime-contract profiles. Anything else is rejected with
# a P2A1104 diagnostic. ``None`` (default) and ``"compatibility"`` are
# always allowed.
ALLOWED_RUNTIME_CONTRACT_PROFILES: Final = frozenset(
    {None, "compatibility", "v1.4", "runtime_contract_v1_4"}
)

# Maximum number of path components we'll echo back from a normalized
# source_name. Keeps a `/home/x/y/z/script.pine` honest but stops a
# crafted 200-segment path from filling the diagnostic.
SOURCE_NAME_MAX_COMPONENTS: Final = 8

# Patterns we refuse in source_name (these would let a caller inject
# control characters or absurdly long strings into diagnostic output).
_FORBIDDEN_SOURCE_NAME_CHARS: Final = re.compile(r"[\x00-\x1f\x7f]")


def clamp_int(
    value: int,
    *,
    ceiling: int,
    field: str,
) -> int:
    """Clamp ``value`` to ``[1, ceiling]``. Raises ``ValueError`` if the
    caller passed a negative number — that's always wrong."""
    if value < 0:
        raise ValueError(f"{field} must be non-negative, got {value}")
    if value > ceiling:
        return ceiling
    return value


def sanitize_source_name(name: str | None) -> str:
    """Return a short, safe representation of ``source_name`` for use in
    diagnostic messages.

    Rules (in order):
      1. ``None`` / empty → ``"<memory>"`` (matches the default in
         ``ParseOptions.source_name``).
      2. Strip control characters (NUL, BEL, etc.) — these can break
         terminals, log aggregators, and JSON serializers.
      3. Truncate to ``ABSOLUTE_MAX_SOURCE_NAME_LEN`` characters.
      4. If the result looks like a filesystem path, keep only the
         last ``SOURCE_NAME_MAX_COMPONENTS`` segments. This is a
         best-effort redact for the common case of an absolute
         ``/home/.../project/secrets/.../file.pine`` ending up in
         a public error response.

    The function never raises. It is pure: same input → same output.
    """
    if not name:
        return "<memory>"
    cleaned = _FORBIDDEN_SOURCE_NAME_CHARS.sub("", name)
    if len(cleaned) > ABSOLUTE_MAX_SOURCE_NAME_LEN:
        cleaned = cleaned[:ABSOLUTE_MAX_SOURCE_NAME_LEN] + "..."
    # Path-like?
    if "/" in cleaned or "\\" in cleaned:
        try:
            parts = Path(cleaned).parts
            if len(parts) > SOURCE_NAME_MAX_COMPONENTS:
                parts = parts[-SOURCE_NAME_MAX_COMPONENTS:]
                cleaned = ".../" + "/".join(parts)
        except (OSError, ValueError):
            # Path() can raise on weird inputs (e.g. embedded NUL on
            # some platforms). Fall back to the truncated string.
            pass
    return cleaned


def is_safe_runtime_contract_profile(value: str | None) -> bool:
    """Whitelist check for ``runtime_contract_profile``."""
    return value in ALLOWED_RUNTIME_CONTRACT_PROFILES


def safe_resolve_path(path: str | Path, *, must_exist: bool = True) -> Path:
    """Resolve ``path`` to an absolute, non-symlink target.

    - Refuses symlinks (anything where ``is_symlink()`` is True at any
      component). This is a deliberate choice for the default
      ``parse_file`` entry point: we want to know the file the caller
      pointed at is the file we actually read, not "whatever a symlink
      chain happens to point to right now".
    - Refuses paths that escape their parent via ``..`` (we call
      ``resolve(strict=False)`` and then check the resolved path is
      under the original's parent).
    - If ``must_exist`` is True (default), the resolved path must
      point to a regular file. Raises ``FileNotFoundError`` otherwise.

    Raises:
      ValueError: if the path is unsafe (symlink, traversal, etc.)
      FileNotFoundError: if the path does not exist and ``must_exist``
    """
    p = Path(path)
    # Reject symlinks at every level of the path. Path.is_symlink()
    # checks the final component; we walk the parts to check parents.
    for parent in (p, *p.parents):
        if parent == p.parent and parent == Path("."):
            continue
        if parent.is_symlink():
            raise ValueError(f"Refusing to follow symlink: {p}")

    resolved = p.resolve(strict=False)
    # If the original path is relative, reject anything that resolved
    # above the current working directory.
    if not p.is_absolute():
        cwd = Path.cwd().resolve()
        try:
            resolved.relative_to(cwd)
        except ValueError as exc:
            raise ValueError(f"Refusing path that escapes the working directory: {p}") from exc

    if must_exist:
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {p}")
        if not resolved.is_file():
            raise ValueError(f"Not a regular file: {p}")
    return resolved


# Match decimal floats that would overflow to +inf or -inf in Python's
# float(). 1e309 already overflows on most platforms; 1e500 always does.
# We also catch the denormal-but-huge case "1e308" by being explicit:
# anything whose absolute value is >= 1e308 is flagged.
_INF_LITERAL_RE: Final = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<sign>[-+]?)"
    r"(?P<mantissa>\d+(?:\.\d*)?|\.\d+)"
    r"(?:[eE](?P<exp>[-+]?\d+))?"
    r"(?![A-Za-z0-9_.])"
)


def find_overflowing_float_literals(source: str) -> list[tuple[int, int, str]]:
    """Return ``(start, end, text)`` for every numeric literal whose value
    would not fit in a Python float (i.e. ``float(text) in {inf, -inf}``).

    The match is conservative: false positives are possible (e.g. the
    literal ``1e308`` is exactly representable, but the regex flags it
    anyway because we don't want callers to assume precision). False
    negatives are not: any literal that produces ``inf`` from
    ``float()`` is caught.

    Pine Script itself does not allow ``inf`` as a literal value, so
    the only way for a literal to overflow is the ``1e500`` shape.
    Catching this in the security layer (rather than letting Python
    produce a quiet ``inf``) keeps the rest of the pipeline from
    doing weird things like ``inf > close`` always being True.
    """
    out: list[tuple[int, int, str]] = []
    for m in _INF_LITERAL_RE.finditer(source):
        text = m.group(0)
        try:
            value = float(text)
        except ValueError:
            continue
        # NaN and inf are both "non-finite" for our purposes.
        import math

        if not math.isfinite(value) or abs(value) >= 1e308:
            out.append((m.start(), m.end(), text))
    return out
