from __future__ import annotations

from typing import Any

from pine2ast.ast.nodes import Program
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.static_validation import validate_static_semantics


def extract_validation_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    """Return Release 4.0 static semantic issues as an OpenPine-facing contract."""

    profile = profile or pine_language_profile(program.version or program.language_version)
    issues = validate_static_semantics(program, semantic_model=semantic_model, profile=profile)
    return {
        "contract": "openpine.static_validation.v1",
        "profile": f"pine_v{profile.version}",
        "issue_count": len(issues),
        "issues": [issue.to_dict() for issue in issues],
    }
