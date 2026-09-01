from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.versioning.context import (
    SUPPORTED_PINE_VERSIONS,
    PineVersionContext,
    VersionOrigin,
)

_VERSION_PREFIX = "//@version"
_VERSION_RE = re.compile(r"^//@version\s*=\s*([0-9]+)\s*$")


@dataclass(frozen=True, slots=True)
class _AnnotationCandidate:
    raw: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class VersionResolution:
    context: PineVersionContext | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.context is not None and not any(item.is_error for item in self.diagnostics)


class PineVersionResolver:
    """Resolve the Pine major version before lexing/parsing without guessing."""

    def __init__(
        self,
        catalog_identity: Callable[[int], tuple[str, str]],
    ) -> None:
        self._catalog_identity = catalog_identity

    def resolve(
        self,
        source: str,
        *,
        expected_pine_version: int | None = None,
    ) -> VersionResolution:
        candidates = _scan_version_annotations(source)
        diagnostics: list[Diagnostic] = []
        if len(candidates) > 1:
            for duplicate in candidates[1:]:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        codes.DUPLICATE_VERSION_ANNOTATION,
                        "Pine source must contain at most one //@version compiler annotation.",
                        duplicate.span,
                    )
                )
            return VersionResolution(None, tuple(diagnostics))

        if not candidates:
            version = 1
            origin = VersionOrigin.TRADINGVIEW_DEFAULT_V1
            annotation_span = None
            diagnostics.append(
                Diagnostic(
                    Severity.INFO,
                    codes.VERSION_DEFAULTED_TO_V1,
                    "No //@version annotation was found; TradingView semantics default to Pine v1.",
                    SourceSpan.zero(),
                )
            )
        else:
            candidate = candidates[0]
            match = _VERSION_RE.fullmatch(candidate.raw)
            if match is None:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        codes.INVALID_VERSION_ANNOTATION,
                        "Invalid Pine compiler annotation; expected //@version=<1..6>.",
                        candidate.span,
                    )
                )
                return VersionResolution(None, tuple(diagnostics))
            version = int(match.group(1))
            origin = VersionOrigin.COMPILER_ANNOTATION
            annotation_span = candidate.span

        if version not in SUPPORTED_PINE_VERSIONS:
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    codes.UNSUPPORTED_VERSION,
                    f"Unsupported Pine major version {version}; known versions are 1 through 6.",
                    annotation_span or SourceSpan.zero(),
                )
            )
            return VersionResolution(None, tuple(diagnostics))

        if expected_pine_version is not None:
            if (
                type(expected_pine_version) is not int
                or expected_pine_version not in SUPPORTED_PINE_VERSIONS
            ):
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        codes.INVALID_EXPECTED_VERSION,
                        "expected_pine_version must be one of 1..6.",
                        SourceSpan.zero(),
                    )
                )
                return VersionResolution(None, tuple(diagnostics))
            if expected_pine_version != version:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        codes.VERSION_EXPECTATION_MISMATCH,
                        (
                            f"Source resolves to Pine v{version}, but the caller expected "
                            f"Pine v{expected_pine_version}. The caller cannot override source semantics."
                        ),
                        annotation_span or SourceSpan.zero(),
                    )
                )
                return VersionResolution(None, tuple(diagnostics))

        spec_snapshot_ref, catalog_hash = self._catalog_identity(version)
        context = PineVersionContext(
            pine_version=version,
            origin=origin,
            annotation_span=annotation_span,
            spec_snapshot_ref=spec_snapshot_ref,
            catalog_hash=catalog_hash,
        )
        return VersionResolution(context, tuple(diagnostics))


def _scan_version_annotations(source: str) -> list[_AnnotationCandidate]:
    """Linear scanner that ignores annotation-like text inside strings.

    Pine has line comments and quoted strings, including triple-quoted multiline
    strings in current v6.  The scanner accepts a compiler annotation only when
    the comment is the first non-whitespace token on its physical line.
    """

    result: list[_AnnotationCandidate] = []
    i = 0
    line = 1
    col = 1
    line_non_ws = False
    quote: str | None = None
    triple = False
    escaped = False
    n = len(source)

    while i < n:
        ch = source[i]
        if ch == "\n":
            i += 1
            line += 1
            col = 1
            line_non_ws = False
            escaped = False
            if quote is not None and not triple:
                quote = None
            continue

        if quote is not None:
            if escaped:
                escaped = False
                i += 1
                col += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                col += 1
                continue
            delimiter = quote * (3 if triple else 1)
            if source.startswith(delimiter, i):
                i += len(delimiter)
                col += len(delimiter)
                quote = None
                triple = False
                continue
            i += 1
            col += 1
            continue

        if ch in {'"', "'"}:
            delimiter = ch * 3
            triple = source.startswith(delimiter, i)
            quote = ch
            width = 3 if triple else 1
            i += width
            col += width
            line_non_ws = True
            continue

        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            start_i = i
            start_line = line
            start_col = col
            end = source.find("\n", i)
            if end < 0:
                end = n
            raw = source[start_i:end].strip()
            if not line_non_ws and raw.startswith(_VERSION_PREFIX):
                result.append(
                    _AnnotationCandidate(
                        raw=raw,
                        span=SourceSpan(
                            start_offset=start_i,
                            end_offset=end,
                            start_line=start_line,
                            start_col=start_col,
                            end_line=start_line,
                            end_col=start_col + (end - start_i),
                        ),
                    )
                )
            col += end - i
            i = end
            continue

        if not ch.isspace():
            line_non_ws = True
        i += 1
        col += 1

    return result


__all__ = ["PineVersionResolver", "VersionResolution"]
