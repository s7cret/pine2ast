"""Keyword spellings for a projected library span.

Lexical lowering concatenates a library body after the consumer header. A word
that is a keyword only in the consumer version must stay an identifier inside
an older library span.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from pine2ast.catalog import CatalogRepository
from pine2ast.lexer.token import SourceSpan
from pine2ast.policy.models import syntax_policy_from_catalog
from pine2ast.versioning.context import PineVersionContext, VersionOrigin


@lru_cache(maxsize=6)
def keyword_spellings_for_version(version: int) -> frozenset[str]:
    catalog = CatalogRepository.default()
    identity = catalog.identity(version)
    context = PineVersionContext(
        pine_version=version,
        origin=VersionOrigin.COMPILER_ANNOTATION,
        annotation_span=SourceSpan.zero(),
        spec_snapshot_ref=identity.spec_snapshot_ref,
        catalog_hash=identity.catalog_hash,
    )
    return syntax_policy_from_catalog(context, catalog.readonly_view(version)).keyword_spellings


def origin_keyword_spans(
    receipt: Mapping[str, Any] | None,
) -> tuple[tuple[int, int, frozenset[str]], ...]:
    if not isinstance(receipt, Mapping):
        return ()
    sources = receipt.get("sources")
    projection = receipt.get("projection")
    if not isinstance(sources, Mapping) or not isinstance(projection, list):
        return ()
    rows: list[tuple[int, int, frozenset[str]]] = []
    for row in projection:
        if not isinstance(row, Mapping) or row.get("source") not in sources:
            continue
        version = int(sources[row["source"]]["pine_version"])
        rows.append(
            (
                int(row["generated_start"]),
                int(row["generated_end"]),
                keyword_spellings_for_version(version),
            )
        )
    return tuple(rows)
