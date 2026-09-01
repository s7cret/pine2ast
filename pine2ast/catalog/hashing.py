from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_id(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def seal_hash(payload: dict[str, Any], *, field: str = "content_hash") -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != field}
    return {**body, field: sha256_id(body)}


def verify_hash(payload: dict[str, Any], *, field: str = "content_hash") -> bool:
    stored = payload.get(field)
    if not isinstance(stored, str):
        return False
    body = {key: value for key, value in payload.items() if key != field}
    return stored == sha256_id(body)


__all__ = ["canonical_json_bytes", "seal_hash", "sha256_id", "verify_hash"]
