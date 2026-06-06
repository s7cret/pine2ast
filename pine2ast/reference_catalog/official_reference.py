from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.request import urlopen

from pine2ast.semantic.builtin_registry import load_builtin_registry

TRADINGVIEW_ORIGIN = "https://www.tradingview.com"
STATIC_ORIGIN = "https://static.tradingview.com"


class OfficialReferenceError(ValueError):
    """Raised when TradingView reference data cannot be discovered or parsed."""


@dataclass(frozen=True)
class OfficialReferenceIndex:
    pine_version: int
    source_url: str
    bundle_url: str
    categories: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "pain.official_pine_reference_index.v1",
            "pine_version": self.pine_version,
            "source": {
                "reference_url": self.source_url,
                "bundle_url": self.bundle_url,
                "basis": "TradingView pine-script-reference webpack reference payload",
            },
            "categories": self.categories,
            "counts": {key: len(value) for key, value in self.categories.items()},
        }


def fetch_official_reference_index(
    version: int, *, timeout: float = 20.0
) -> OfficialReferenceIndex:
    if version not in {5, 6}:
        raise OfficialReferenceError("only Pine v5 and v6 official indexes are supported")
    page_url = f"{TRADINGVIEW_ORIGIN}/pine-script-reference/v{version}/"
    page_html = _fetch_text(page_url, timeout=timeout)
    script_urls = _script_urls(page_html)
    runtime_url = _select_script(script_urls, "runtime.")
    runtime_js = _fetch_text(runtime_url, timeout=timeout)
    reference_js = _reference_loader_js(script_urls, timeout=timeout)
    chunk_id = _reference_payload_chunk_id(reference_js, version)
    bundle_url = _chunk_url(runtime_js, chunk_id)
    bundle_js = _fetch_text(bundle_url, timeout=timeout)
    return OfficialReferenceIndex(
        pine_version=version,
        source_url=page_url,
        bundle_url=bundle_url,
        categories=_extract_reference_categories(bundle_js),
    )


def load_official_reference_index(path: str) -> OfficialReferenceIndex:
    payload = json.loads(_read_text(path))
    if payload.get("schema_version") != "pain.official_pine_reference_index.v1":
        raise OfficialReferenceError("official reference index schema mismatch")
    source = payload.get("source", {})
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        raise OfficialReferenceError("official reference index categories must be an object")
    return OfficialReferenceIndex(
        pine_version=int(payload["pine_version"]),
        source_url=str(source.get("reference_url", "")),
        bundle_url=str(source.get("bundle_url", "")),
        categories={
            str(key): sorted({str(item) for item in value})
            for key, value in categories.items()
            if isinstance(value, list)
        },
    )


def official_reference_diff_payload(index: OfficialReferenceIndex) -> dict[str, Any]:
    local = load_builtin_registry()
    local_categories = {
        "functions": set(local.get("functions", {})),
        "variables": set(local.get("variables", {})),
        "types": set(local.get("types", {})),
        "namespaces": set(local.get("namespaces", {})),
    }
    official_categories = {key: set(value) for key, value in index.categories.items()}
    comparable = ("functions", "variables", "types")
    missing_by_category = {
        key: sorted(official_categories.get(key, set()) - local_categories.get(key, set()))
        for key in comparable
    }
    extra_by_category = {
        key: sorted(local_categories.get(key, set()) - official_categories.get(key, set()))
        for key in comparable
    }
    namespace_counts = Counter(
        name.split(".", 1)[0] if "." in name else "<global>"
        for name in missing_by_category["functions"]
    )
    missing_count = sum(len(v) for v in missing_by_category.values())
    official_count = sum(len(official_categories.get(key, set())) for key in comparable)
    modeled_count = official_count - missing_count
    return {
        "schema_version": "pain.official_pine_reference_diff.v1",
        "pine_version": index.pine_version,
        "source": index.to_dict()["source"],
        "summary": {
            "official_comparable_count": official_count,
            "local_modeled_count": modeled_count,
            "missing_official_count": missing_count,
            "coverage_ratio": None if official_count == 0 else modeled_count / official_count,
        },
        "missing_by_category": missing_by_category,
        "extra_local_by_category": extra_by_category,
        "missing_function_namespaces": dict(sorted(namespace_counts.items())),
    }


def official_reference_gate_payload(
    index: OfficialReferenceIndex, baseline_path: str
) -> dict[str, Any]:
    baseline = json.loads(_read_text(baseline_path))
    if baseline.get("schema_version") != "pain.official_pine_reference_gap_baseline.v1":
        raise OfficialReferenceError("official reference gap baseline schema mismatch")
    if int(baseline.get("pine_version")) != index.pine_version:
        raise OfficialReferenceError("official reference gap baseline Pine version mismatch")

    diff = official_reference_diff_payload(index)
    current_missing = {key: set(value) for key, value in diff["missing_by_category"].items()}
    baseline_missing = {
        str(key): {str(item) for item in value}
        for key, value in baseline.get("missing_by_category", {}).items()
        if isinstance(value, list)
    }
    categories = sorted(set(current_missing) | set(baseline_missing))
    new_missing = {
        key: sorted(current_missing.get(key, set()) - baseline_missing.get(key, set()))
        for key in categories
    }
    resolved_missing = {
        key: sorted(baseline_missing.get(key, set()) - current_missing.get(key, set()))
        for key in categories
    }
    max_missing = baseline.get("max_missing_official_count")
    min_coverage = baseline.get("min_coverage_ratio")
    summary = diff["summary"]
    failures: list[str] = []
    if any(new_missing.values()):
        failures.append("new official reference gaps detected")
    if isinstance(max_missing, int) and summary["missing_official_count"] > max_missing:
        failures.append("official missing count exceeds baseline")
    if isinstance(min_coverage, (float, int)) and summary["coverage_ratio"] < float(min_coverage):
        failures.append("official coverage ratio fell below baseline")

    return {
        "schema_version": "pain.official_pine_reference_gate.v1",
        "status": "fail" if failures else "pass",
        "failures": failures,
        "pine_version": index.pine_version,
        "source": diff["source"],
        "summary": summary,
        "baseline": {
            "path": baseline_path,
            "max_missing_official_count": max_missing,
            "min_coverage_ratio": min_coverage,
        },
        "new_missing_by_category": new_missing,
        "resolved_missing_by_category": resolved_missing,
        "diff": diff,
    }


def _fetch_text(url: str, *, timeout: float) -> str:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed official HTTPS URLs.
        return response.read().decode("utf-8", errors="replace")


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _script_urls(html: str) -> list[str]:
    urls = re.findall(r'https://static\.tradingview\.com/static/bundles/[^"\s]+\.js', html)
    unique: list[str] = []
    for url in urls:
        if url not in unique:
            unique.append(unescape(url))
    if not unique:
        raise OfficialReferenceError("no TradingView bundle URLs found on reference page")
    return unique


def _select_script(urls: list[str], marker: str) -> str:
    for url in urls:
        if marker in url:
            return url
    raise OfficialReferenceError(f"could not find {marker!r} bundle")


def _reference_loader_js(urls: list[str], *, timeout: float) -> str:
    for url in urls:
        text = _fetch_text(url, timeout=timeout)
        if "getReference" in text and "PineLanguage.V6" in text:
            return text
    raise OfficialReferenceError("could not find TradingView reference loader bundle")


def _reference_payload_chunk_id(reference_js: str, version: int) -> int:
    case_match = re.search(
        rf"case\s+\w+\.PineLanguage\.V{version}:(.*?);break",
        reference_js,
    )
    if not case_match:
        raise OfficialReferenceError(f"could not discover Pine v{version} reference payload chunk")
    chunk_ids = re.findall(r"\.e\((\d+)\)", case_match.group(1))
    if not chunk_ids:
        raise OfficialReferenceError(f"could not discover Pine v{version} reference payload chunk")
    return int(chunk_ids[-1])


def _chunk_url(runtime_js: str, chunk_id: int) -> str:
    lang_pattern = rf"if\({chunk_id}===e\)return\"__LANG__\.\"\+e\+\"\.([a-f0-9]+)\.js\""
    lang_match = re.search(lang_pattern, runtime_js)
    if lang_match:
        return f"{STATIC_ORIGIN}/static/bundles/en.{chunk_id}.{lang_match.group(1)}.js"
    hash_match = re.search(rf"(?<!\d){chunk_id}:\"([a-f0-9]+)\"", runtime_js)
    if hash_match:
        return f"{STATIC_ORIGIN}/static/bundles/{chunk_id}.{hash_match.group(1)}.js"
    raise OfficialReferenceError(f"could not resolve TradingView chunk URL for {chunk_id}")


def _extract_reference_categories(bundle_js: str) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    for key in (
        "functions",
        "variables",
        "methods",
        "constants",
        "types",
        "keywords",
        "operators",
        "annotations",
    ):
        array_source = _array_source(bundle_js, key)
        items = _top_level_objects(array_source)
        names: list[str] = []
        for item in items:
            name = _first_string_prop(item, "originalName" if key == "methods" else "name")
            if name is None and key == "methods":
                name = _first_string_prop(item, "name")
            if name:
                names.append(name)
        categories[key] = sorted(set(names))
    return categories


def _array_source(source: str, key: str) -> str:
    start = source.find(f"{key}:[")
    if start < 0:
        raise OfficialReferenceError(f"could not find {key} array in reference bundle")
    open_idx = source.find("[", start)
    return _balanced_slice(source, open_idx, "[", "]")


def _balanced_slice(source: str, start: int, open_char: str, close_char: str) -> str:
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(source)):
        char = source[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return source[start : idx + 1]
    raise OfficialReferenceError(f"unterminated {open_char}{close_char} block")


def _top_level_objects(array_source: str) -> list[str]:
    objects: list[str] = []
    square_depth = 0
    curly_depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for idx, char in enumerate(array_source):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth -= 1
        elif char == "{":
            if square_depth == 1 and curly_depth == 0:
                start = idx
            curly_depth += 1
        elif char == "}":
            curly_depth -= 1
            if square_depth == 1 and curly_depth == 0 and start is not None:
                objects.append(array_source[start : idx + 1])
                start = None
    return objects


def _first_string_prop(source: str, prop: str) -> str | None:
    match = re.search(rf'(?<![A-Za-z0-9_]){re.escape(prop)}:"((?:\\.|[^"\\])*)"', source)
    if not match:
        return None
    return match.group(1).replace('\\"', '"').replace("\\\\", "\\")
