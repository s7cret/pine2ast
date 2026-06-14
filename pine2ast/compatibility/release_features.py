from __future__ import annotations

import json
from importlib import resources
from typing import Any


def load_v6_release_features() -> dict[str, Any]:
    """Load the Release 4.0 Pine v6 release-note feature matrix."""

    text = (
        resources.files("pine2ast") / "compatibility" / "release_features_v6_4_0.json"
    ).read_text(encoding="utf-8")
    return json.loads(text)


def release_feature_summary(payload: dict[str, Any] | None = None) -> dict[str, int]:
    payload = payload or load_v6_release_features()
    counts: dict[str, int] = {}
    for feature in payload.get("features", []):
        status = str(feature.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def validate_release_feature_matrix(
    payload: dict[str, Any] | None = None, *, allow_not_started: bool = False
) -> tuple[str, ...]:
    """Return machine-readable validation errors for the v6 release matrix.

    The matrix is part of the frontend contract, so CI can fail when a release-note
    item has an unknown status, duplicate id, or an accidentally open
    ``not_started`` status after Release 4.0 hardening.
    """

    payload = payload or load_v6_release_features()
    allowed = {str(status) for status in payload.get("status_values", [])}
    seen: set[str] = set()
    errors: list[str] = []
    for index, feature in enumerate(payload.get("features", [])):
        feature_id = str(feature.get("id") or "")
        status = str(feature.get("status") or "unknown")
        if not feature_id:
            errors.append(f"features[{index}] has no id")
        elif feature_id in seen:
            errors.append(f"duplicate feature id: {feature_id}")
        seen.add(feature_id)
        if status not in allowed:
            errors.append(f"{feature_id or index} has unknown status: {status}")
        if status == "not_started" and not allow_not_started:
            errors.append(f"{feature_id or index} is still not_started")
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m pine2ast.compatibility.release_features")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--allow-not-started", action="store_true")
    args = parser.parse_args(argv)
    payload = load_v6_release_features()
    errors = validate_release_feature_matrix(payload, allow_not_started=args.allow_not_started)
    output = json.dumps(
        {
            "ok": not errors,
            "summary": release_feature_summary(payload),
            "errors": list(errors),
            "feature_count": len(payload.get("features", [])),
        },
        ensure_ascii=False,
        indent=2,
    )
    if args.json_path:
        from pathlib import Path

        Path(args.json_path).write_text(output, encoding="utf-8")
        print(args.json_path)
    else:
        print(output)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
