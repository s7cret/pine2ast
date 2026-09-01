from __future__ import annotations

from typing import Any

from pine2ast.ast.nodes import Program
from pine2ast.frontend.ids import SECTION_CONTRACTS
from pine2ast.versioning import PineVersionContext
from pine2ast.semantic.static_validation import validate_static_semantics


def extract_validation_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> dict[str, Any]:
    """Return Release 4.0 static semantic issues as an OpenPine-facing contract."""

    profile = profile or program.version_context
    issues = validate_static_semantics(program, semantic_model=semantic_model, profile=profile)
    return {
        "contract": SECTION_CONTRACTS["static_validation"],
        "profile": f"pine_v{profile.pine_version}",
        "issue_count": len(issues),
        "issues": [issue.to_dict() for issue in issues],
    }
