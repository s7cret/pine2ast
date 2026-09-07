"""Content-locked, offline Pine library inputs. No downloads or version fallback.

The publication revision in owner/name/revision is not the source's Pine version.
A store is detached from its inputs and a compilation resolves only its closure.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

SCHEMA = "pine2ast.library_lock.v1"
REF = re.compile(r"[A-Za-z_][A-Za-z0-9_]*/[A-Za-z_][A-Za-z0-9_]*/[1-9][0-9]*\Z")
HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_LIBRARIES = 64
MAX_SOURCE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 8_000_000
MAX_DEPTH = 24


class LibraryError(ValueError):
    """A deterministic admission failure with original source coordinates."""

    def __init__(
        self, code: str, message: str, *, source: str | None = None, line: int | None = None
    ) -> None:
        self.code, self.source, self.line = code, source, line
        where = f" [{source}:{line}]" if source is not None else ""
        super().__init__(f"{code}{where}: {message}")


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def source_hash(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(data).hexdigest()


def valid_ref(value: object) -> str:
    if type(value) is not str or len(value) > 240 or not REF.fullmatch(value):
        raise LibraryError("P2A_LIBRARY_REFERENCE", "expected exact owner/name/positive_revision")
    return value


def strict_json(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise LibraryError("P2A_LIBRARY_LOCK", f"duplicate JSON key: {k}")
            result[k] = v
        return result

    def invalid(value):
        raise LibraryError("P2A_LIBRARY_LOCK", f"nonfinite value: {value}")

    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, LibraryError):
            raise
        raise LibraryError("P2A_LIBRARY_LOCK", "invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise LibraryError("P2A_LIBRARY_LOCK", "lock root must be an object")
    return value


@dataclass(frozen=True, slots=True)
class LibraryStore:
    """Immutable sources validated against an explicit lock hash.

    `create` is for deliberate pin creation, not for admitting received content.
    Existing projects use `admit`/`from_directory` with the previously pinned hash.
    """

    _sources: Mapping[str, str]
    _lock: bytes

    @classmethod
    def create(cls, sources: Mapping[str, str]) -> "LibraryStore":
        if not isinstance(sources, Mapping) or not 1 <= len(sources) <= MAX_LIBRARIES:
            raise LibraryError("P2A_LIBRARY_LIMIT", "store must contain 1..64 libraries")
        for ref in sources:
            valid_ref(ref)
        rows, total = [], 0
        for ref in sorted(sources):
            source = sources[ref]
            if type(source) is not str:
                raise LibraryError("P2A_LIBRARY_SOURCE", "source must be UTF-8 text")
            size = len(source.encode("utf-8"))
            total += size
            if size > MAX_SOURCE_BYTES or total > MAX_TOTAL_BYTES:
                raise LibraryError("P2A_LIBRARY_LIMIT", "library source size limit exceeded")
            rows.append({"ref": ref, "sha256": source_hash(source), "path": ref + ".pine"})
        body = {"schema_id": SCHEMA, "libraries": rows}
        content_hash = source_hash(canonical(body))
        lock = {**body, "content_hash": content_hash}
        return cls.admit(lock, sources, expected_hash=content_hash)

    @classmethod
    def admit(
        cls, lock: Mapping, sources: Mapping[str, str], *, expected_hash: str
    ) -> "LibraryStore":
        if not isinstance(sources, Mapping):
            raise LibraryError("P2A_LIBRARY_SOURCE", "sources must map exact refs to text")
        try:
            value = strict_json(canonical(lock))
        except (TypeError, ValueError, RecursionError) as exc:
            raise LibraryError("P2A_LIBRARY_LOCK", "lock must be canonical JSON data") from exc
        if set(value) != {"schema_id", "libraries", "content_hash"} or value["schema_id"] != SCHEMA:
            raise LibraryError("P2A_LIBRARY_LOCK", "unexpected lock schema or fields")
        body = {k: v for k, v in value.items() if k != "content_hash"}
        if (
            type(expected_hash) is not str
            or not HASH.fullmatch(expected_hash)
            or expected_hash != value["content_hash"]
            or source_hash(canonical(body)) != expected_hash
        ):
            raise LibraryError("P2A_LIBRARY_LOCK_HASH", "lock differs from the pinned identity")
        rows = value["libraries"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LIBRARIES:
            raise LibraryError("P2A_LIBRARY_LIMIT", "store must contain 1..64 libraries")
        admitted, paths, total = {}, set(), 0
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"ref", "sha256", "path"}:
                raise LibraryError("P2A_LIBRARY_LOCK", "library descriptor fields are not exact")
            ref = valid_ref(row["ref"])
            path = row["path"]
            _relative_parts(path)
            if ref in admitted or path in paths:
                raise LibraryError("P2A_LIBRARY_LOCK", "duplicate revision or source path")
            paths.add(path)
            if type(row["sha256"]) is not str or not HASH.fullmatch(row["sha256"]):
                raise LibraryError("P2A_LIBRARY_LOCK", "invalid library source hash")
            text = sources.get(ref)
            if type(text) is not str:
                raise LibraryError(
                    "P2A_LIBRARY_MISSING", "locked library source is missing", source=ref
                )
            total += len(text.encode("utf-8"))
            if len(text.encode("utf-8")) > MAX_SOURCE_BYTES or total > MAX_TOTAL_BYTES:
                raise LibraryError("P2A_LIBRARY_LIMIT", "library source size limit exceeded")
            if source_hash(text) != row["sha256"]:
                raise LibraryError(
                    "P2A_LIBRARY_SOURCE_HASH", "source differs from lock", source=ref
                )
            admitted[ref] = text
        if set(sources) != set(admitted):
            raise LibraryError("P2A_LIBRARY_LOCK", "sources must exactly match lock inventory")
        return cls(MappingProxyType(admitted), canonical(value))

    @classmethod
    def from_directory(cls, lock_path: str | Path, *, expected_hash: str) -> "LibraryStore":
        """Read once using directory-relative, no-follow file descriptors on POSIX.

        Compiling uses captured bytes; files are never reread by the compiler or worker.
        Symlinks, traversal, devices and network sources are not accepted.
        """
        path = Path(lock_path).absolute()
        if not hasattr(os, "O_NOFOLLOW"):
            raise LibraryError("P2A_LIBRARY_FILESYSTEM", "safe no-follow file reads unavailable")
        # Open the root component by component, retaining an fd even if renamed.
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parent.parts[1:]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            lock = strict_json(_read_at(fd, path.name, 256_000))
            if set(lock) != {"schema_id", "libraries", "content_hash"}:
                raise LibraryError("P2A_LIBRARY_LOCK", "unexpected lock fields")
            # Validate identity and paths before reading any source named by the lock.
            body = {k: v for k, v in lock.items() if k != "content_hash"}
            if (
                lock["content_hash"] != expected_hash
                or source_hash(canonical(body)) != expected_hash
            ):
                raise LibraryError("P2A_LIBRARY_LOCK_HASH", "lock differs from pinned identity")
            rows = lock.get("libraries")
            if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LIBRARIES:
                raise LibraryError("P2A_LIBRARY_LIMIT", "invalid library inventory")
            sources, total = {}, 0
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"ref", "sha256", "path"}:
                    raise LibraryError("P2A_LIBRARY_LOCK", "invalid descriptor")
                ref = valid_ref(row["ref"])
                data = _read_at(fd, row["path"], MAX_SOURCE_BYTES)
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise LibraryError("P2A_LIBRARY_LIMIT", "total source limit exceeded")
                sources[ref] = data.decode("utf-8", errors="strict")
            return cls.admit(lock, sources, expected_hash=expected_hash)
        except (OSError, UnicodeError) as exc:
            raise LibraryError(
                "P2A_LIBRARY_FILESYSTEM", "unsafe, missing or non-UTF8 library file"
            ) from exc
        finally:
            os.close(fd)

    @property
    def content_hash(self) -> str:
        return json.loads(self._lock)["content_hash"]

    def lock(self) -> dict:
        return json.loads(self._lock)

    def source(self, ref: str) -> str:
        valid_ref(ref)
        try:
            return self._sources[ref]
        except KeyError as exc:
            raise LibraryError(
                "P2A_LIBRARY_MISSING", "exact publication is not in the lock", source=ref
            ) from exc


def _relative_parts(path: object) -> tuple[str, ...]:
    if (
        type(path) is not str
        or not path
        or len(path) > 512
        or "\\" in path
        or any(ord(c) < 32 for c in path)
    ):
        raise LibraryError("P2A_LIBRARY_PATH", "invalid library path")
    parts = tuple(path.split("/"))
    if any(p in {"", ".", ".."} or ":" in p for p in parts):
        raise LibraryError("P2A_LIBRARY_PATH", "library paths must be confined and relative")
    return parts


def _read_at(root_fd: int, name: str, limit: int) -> bytes:
    import stat

    parts = _relative_parts(name)
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(child, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise LibraryError("P2A_LIBRARY_PATH", "source must be a regular file")
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise LibraryError("P2A_LIBRARY_LIMIT", "file exceeds size limit")
        return data
    finally:
        os.close(fd)
