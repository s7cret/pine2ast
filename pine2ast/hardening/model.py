from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence, cast


def to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, Enum):
        return to_plain(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_plain(value.to_dict())
    if is_dataclass(value):
        # ``is_dataclass`` also accepts dataclass *types*.  ``to_plain`` is a
        # value serializer, so only instances reach this branch in supported
        # call sites; the cast records that invariant for static checkers.
        return to_plain(asdict(cast(Any, value)))
    if hasattr(value, "__dict__"):
        return {str(k): to_plain(v) for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)


def canonical_json(value: Any) -> str:
    return json.dumps(
        to_plain(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def file_hash(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


@dataclass(frozen=True, slots=True)
class GateFinding:
    code: str
    message: str
    blocking: bool = True
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
        }
        if self.details is not None:
            result["details"] = to_plain(self.details)
        return result


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    status: str
    findings: Sequence[GateFinding]
    metrics: Mapping[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == "PASS" and not any(f.blocking for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "ok": self.ok,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": to_plain(self.metrics),
        }
