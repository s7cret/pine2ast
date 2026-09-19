"""Language-level consumer × library Pine version admission for imports.

This is the linker gate, not a Pine converter and not a second evaluator.
//@version of a library is never rewritten to the consumer version.

Authority:
- ``import`` / ``library()`` exist only in Pine v5+ (TradingView Libraries docs).
- A v6 script may import a v5 library; a v5 script may not import a v6 library
  (TradingView v6 FAQ: v5 scripts keep compiling; new language features are
  v6-only, so v6 libraries are not importable from v5).
"""

from __future__ import annotations

from typing import Literal

Decision = Literal["allowed", "rejected_by_language"]

# consumer_version, library_version -> decision
_MATRIX: dict[tuple[int, int], Decision] = {}
for consumer in range(1, 7):
    for library in range(1, 7):
        if consumer < 5 or library < 5:
            _MATRIX[(consumer, library)] = "rejected_by_language"
        elif consumer == library:
            _MATRIX[(consumer, library)] = "allowed"
        elif consumer == 6 and library == 5:
            _MATRIX[(consumer, library)] = "allowed"
        else:
            # Includes v5 consumer × v6 library.
            _MATRIX[(consumer, library)] = "rejected_by_language"

_REASONS = {
    "rejected_pre_v5": "import and library() exist only in Pine v5 or v6",
    "rejected_v5_imports_v6": "Pine v5 cannot import a v6 library",
    "allowed_same": "same-version library import",
    "allowed_v6_imports_v5": "Pine v6 may import a v5 library",
}


def decide_import_versions(consumer_version: int, library_version: int) -> tuple[Decision, str]:
    if consumer_version not in range(1, 7) or library_version not in range(1, 7):
        raise ValueError("Pine versions must be integers 1 through 6")
    decision = _MATRIX[(consumer_version, library_version)]
    if decision == "allowed":
        reason = (
            _REASONS["allowed_same"]
            if consumer_version == library_version
            else _REASONS["allowed_v6_imports_v5"]
        )
    elif consumer_version < 5 or library_version < 5:
        reason = _REASONS["rejected_pre_v5"]
    else:
        reason = _REASONS["rejected_v5_imports_v6"]
    return decision, reason


def allowed_import(consumer_version: int, library_version: int) -> bool:
    return decide_import_versions(consumer_version, library_version)[0] == "allowed"
