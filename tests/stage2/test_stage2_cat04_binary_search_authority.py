"""CAT-04: array.binary_search* availability is v5+, not v4.

Independent authority (not the current catalog, not pinelib output):

- TradingView release notes, March 2022, added array.binary_search,
  array.binary_search_leftmost, and array.binary_search_rightmost on the
  v5 reference:
  https://www.tradingview.com/pine-script-docs/release-notes/#march-2022
- The archived v4 language reference lists array.avg / array.clear /
  array.sort / array.new_float and does not list binary_search*:
  https://www.tradingview.com/pine-script-reference/v4/
- v5 reference examples (sorted [-2, 0, 1, 5, 9]):
  binary_search(..., 0) -> 1; leftmost(..., 3) -> 2; rightmost(..., 3) -> 3.

Keep the symbols in the global denominator; v4 is UNAVAILABLE via negative
admission, not a deleted row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle

ROOT = Path(__file__).resolve().parents[2]
FAMILY = (
    "array.binary_search",
    "array.binary_search_leftmost",
    "array.binary_search_rightmost",
)


def _v4_search(callee: str) -> str:
    return (
        f'//@version=4\nstudy("cat04")\n'
        "a = array.new_float(0)\n"
        "array.push(a, 1.0)\n"
        f"x = {callee}(a, 1.0)\n"
    )


def _v5_search(callee: str) -> str:
    return (
        f'//@version=5\nindicator("cat04")\n'
        "a = array.from(5, -2, 0, 9, 1)\n"
        "array.sort(a)\n"
        f"x = {callee}(a, 0)\n"
    )


@pytest.mark.parametrize("name", FAMILY)
def test_v4_pack_does_not_admit_binary_search_family(name: str) -> None:
    pack = CatalogRepository.default().pack(4)
    assert name not in pack["sections"]["functions"]
    assert name not in pack["sections"].get("methods", {})


@pytest.mark.parametrize("name", FAMILY)
def test_v5_pack_keeps_binary_search_functions_without_sort_field(name: str) -> None:
    functions = CatalogRepository.default().pack(5)["sections"]["functions"]
    assert name in functions
    assert all(item["name"] != "sort_field" for item in functions[name]["parameters"])


@pytest.mark.parametrize("name", FAMILY)
def test_symbols_first_observed_version_is_v5(name: str) -> None:
    rows = [
        json.loads(line)
        for line in (ROOT / "catalog_source/symbols.jsonl").read_text().splitlines()
        if line
    ]
    function = next(
        row for row in rows if row["canonical_name"] == name and row["kind"] == "function"
    )
    assert function["first_observed_version"] == 5
    assert function["last_observed_version"] == 6


@pytest.mark.parametrize("name", FAMILY)
def test_v4_call_is_version_unavailable(name: str) -> None:
    source = _v4_search(name)
    result = parse_code(source)
    assert not result.ok
    emitted = {d.code for d in result.diagnostics}
    assert codes.UNKNOWN_BUILTIN_MEMBER in emitted
    assert codes.UNKNOWN_CALL in emitted
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("name", FAMILY)
def test_v5_namespace_call_is_admitted(name: str) -> None:
    result = parse_code(_v5_search(name))
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    assert build_consumer_bundle(_v5_search(name))["content_hash"]
