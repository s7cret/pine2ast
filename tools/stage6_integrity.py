"""Integrity primitives for Stage 6 release evidence.

The module deliberately keeps release evidence verifiable from a clean source
checkout.  It does not infer success from labels: every requirement must point
to an existing implementation location and to collected, passing pytest nodes.
"""

from __future__ import annotations

from hashlib import sha256
import ast
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "evidence",
    "htmlcov",
    "stage6_reports",
    "venv",
}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _is_source_file(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in _EXCLUDED_PARTS or part.endswith(".egg-info") for part in rel.parts):
        return False
    if path.suffix in _EXCLUDED_SUFFIXES or path.name in {".coverage", "coverage.json"}:
        return False
    return path.is_file()


def canonical_source_hash(root: Path | str) -> str:
    """Return a path-aware deterministic SHA-256 for the reviewable source tree.

    Generated evidence and build products are excluded to avoid a self-reference
    cycle. Relative paths, normalized executable modes, file sizes, and bytes are
    all included.
    """

    base = Path(root).resolve()
    digest = sha256()
    source_files: list[Path] = []
    for path in base.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"refusing symlink in source tree: {path.relative_to(base)}")
        if _is_source_file(base, path):
            source_files.append(path)
    for path in sorted(source_files, key=lambda item: item.as_posix()):
        rel = path.relative_to(base).as_posix().encode("utf-8")
        data = path.read_bytes()
        normalized_mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        digest.update(normalized_mode.to_bytes(4, "big"))
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return "sha256:" + digest.hexdigest()


def _canonical_json_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def verify_official_source_manifest(
    root: Path | str,
    *,
    manifest_path: str = "pine2ast/catalog/sources/source_manifest.json",
    mirror_path: str | None = "docs/official_sources/manifest.json",
    required_urls: Iterable[str] = (),
) -> dict[str, Any]:
    """Verify pinned official-source metadata and every local evidence record.

    The gate intentionally does not redistribute TradingView documentation
    bodies.  Instead, each official HTTPS URL is bound to a reviewed metadata
    record containing the page title and the section headings used by the
    requirement inventory.  Both the record bytes and their canonical source
    fingerprint are verified, so missing, substituted, or edited evidence fails
    closed.
    """

    base = Path(root).resolve()
    manifest = (base / manifest_path).resolve()
    issues: list[str] = []
    checked: list[dict[str, Any]] = []
    try:
        manifest.relative_to(base)
    except ValueError:
        return {
            "ok": False,
            "status": "FAIL",
            "source_count": 0,
            "verified_count": 0,
            "required_url_count": len(set(required_urls)),
            "issues": ["manifest escapes source root"],
            "sources": [],
        }
    try:
        manifest_bytes = manifest.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "ok": False,
            "status": "FAIL",
            "source_count": 0,
            "verified_count": 0,
            "required_url_count": len(set(required_urls)),
            "issues": [f"manifest unreadable: {exc}"],
            "sources": [],
        }
    if not isinstance(payload, dict):
        issues.append("manifest root is not an object")
        payload = {}
    rows = payload.get("sources", [])
    if not isinstance(rows, list) or not rows:
        issues.append("manifest has no source rows")
        rows = []

    expected_manifest_hash = str(payload.get("content_hash", ""))
    hash_payload = dict(payload)
    hash_payload.pop("content_hash", None)
    actual_manifest_hash = _canonical_json_hash(hash_payload)
    if expected_manifest_hash != actual_manifest_hash:
        issues.append("manifest content_hash mismatch")

    if mirror_path is not None:
        mirror = (base / mirror_path).resolve()
        try:
            mirror.relative_to(base)
        except ValueError:
            issues.append("manifest mirror escapes source root")
        else:
            try:
                mirror_payload = json.loads(mirror.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                issues.append(f"manifest mirror unreadable: {exc}")
            else:
                if mirror_payload != payload:
                    issues.append("manifest mirror differs from canonical manifest")

    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, raw in enumerate(rows):
        row_issues: list[str] = []
        if not isinstance(raw, dict):
            checked.append(
                {
                    "index": index,
                    "source_id": "",
                    "url": "",
                    "status": "FAILED",
                    "issues": ["source row is not an object"],
                }
            )
            continue
        source_id = str(raw.get("source_id", "")).strip()
        url = str(raw.get("url", "")).strip()
        if not source_id:
            row_issues.append("missing source_id")
        elif source_id in seen_ids:
            row_issues.append("duplicate source_id")
        seen_ids.add(source_id)
        if not url:
            row_issues.append("missing URL")
        elif url in seen_urls:
            row_issues.append("duplicate URL")
        seen_urls.add(url)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "www.tradingview.com":
            row_issues.append("URL is not an official TradingView HTTPS origin")
        if raw.get("status") != "RETRIEVED":
            row_issues.append("source status is not RETRIEVED")
        if raw.get("review_status") != "VERIFIED":
            row_issues.append("source review_status is not VERIFIED")

        evidence_ref = str(raw.get("evidence_path", "")).strip()
        evidence = (base / evidence_ref).resolve()
        if not evidence_ref:
            row_issues.append("missing evidence_path")
        else:
            try:
                evidence.relative_to(base)
            except ValueError:
                row_issues.append("evidence_path escapes source root")
            else:
                try:
                    evidence_bytes = evidence.read_bytes()
                    record = json.loads(evidence_bytes.decode("utf-8"))
                except (OSError, UnicodeError, ValueError) as exc:
                    row_issues.append(f"evidence unreadable: {exc}")
                else:
                    actual_evidence_hash = "sha256:" + sha256(evidence_bytes).hexdigest()
                    if raw.get("evidence_sha256") != actual_evidence_hash:
                        row_issues.append("evidence_sha256 mismatch")
                    if not isinstance(record, dict):
                        row_issues.append("evidence root is not an object")
                    else:
                        if record.get("source_id") != source_id:
                            row_issues.append("evidence source_id mismatch")
                        if record.get("url") != url:
                            row_issues.append("evidence URL mismatch")
                        if record.get("host") != "www.tradingview.com":
                            row_issues.append("evidence host mismatch")
                        if record.get("retrieval_status") != "SUCCESS":
                            row_issues.append("evidence retrieval_status is not SUCCESS")
                        if record.get("review_status") != "VERIFIED":
                            row_issues.append("evidence review_status is not VERIFIED")
                        if record.get("raw_body_redistributed") is not False:
                            row_issues.append("evidence redistribution policy is invalid")
                        fingerprint_payload = {
                            "source_id": record.get("source_id"),
                            "url": record.get("url"),
                            "title": record.get("title"),
                            "verified_headings": record.get("verified_headings"),
                        }
                        actual_fingerprint = _canonical_json_hash(fingerprint_payload)
                        if record.get("source_fingerprint") != actual_fingerprint:
                            row_issues.append("evidence source_fingerprint mismatch")
                        if raw.get("content_digest") != actual_fingerprint:
                            row_issues.append("manifest content_digest mismatch")
        checked.append(
            {
                "index": index,
                "source_id": source_id,
                "url": url,
                "status": "VERIFIED" if not row_issues else "FAILED",
                "issues": row_issues,
            }
        )

    required = {str(url) for url in required_urls if str(url)}
    missing_urls = sorted(required - seen_urls)
    if missing_urls:
        issues.append(f"{len(missing_urls)} required documentation URL(s) are not pinned")
    verified = sum(row["status"] == "VERIFIED" for row in checked)
    ok = bool(checked) and verified == len(checked) and not issues
    return {
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "manifest_path": manifest.relative_to(base).as_posix(),
        "manifest_content_hash": actual_manifest_hash,
        "source_count": len(checked),
        "verified_count": verified,
        "required_url_count": len(required),
        "missing_required_urls": missing_urls,
        "issues": issues,
        "sources": checked,
    }


def scan_shipping_ast_for_legacy_markers(
    root: Path | str,
    markers: Iterable[str],
    package_dir: str = "pine2ast",
    *,
    excluded_paths: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Scan Python syntax in the shipped package, never test/evidence fixtures.

    Only syntactic identifiers, keyword names, import aliases and exact string
    literals are considered.  Comments and prose therefore cannot produce a
    release blocker.
    """

    base = Path(root).resolve()
    package = base / package_dir
    wanted = set(markers)
    excluded = {str(path).replace("\\", "/") for path in excluded_paths}
    findings: list[dict[str, Any]] = []
    if not package.is_dir():
        return [{"path": package_dir, "line": 0, "kind": "missing-package", "marker": ""}]

    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(base)
        if relative.as_posix() in excluded:
            continue
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(
                {
                    "path": relative.as_posix(),
                    "line": getattr(exc, "lineno", 0) or 0,
                    "kind": "parse-error",
                    "marker": str(exc),
                }
            )
            continue

        def add(node: ast.AST, kind: str, value: str | None) -> None:
            if value in wanted:
                findings.append(
                    {
                        "path": relative.as_posix(),
                        "line": getattr(node, "lineno", 0),
                        "kind": kind,
                        "marker": value,
                    }
                )

        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                add(node, "identifier", node.id)
            elif isinstance(node, ast.Attribute):
                add(node, "attribute", node.attr)
            elif isinstance(node, ast.keyword):
                add(node, "keyword", node.arg)
            elif isinstance(node, ast.alias):
                add(node, "import", node.name)
                add(node, "import-alias", node.asname)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(node, "definition", node.name)
            elif isinstance(node, ast.arg):
                add(node, "argument", node.arg)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                add(node, "string-literal", node.value)
    return findings


def load_collected_nodes(path: Path | str) -> set[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        values = data.get("nodes", [])
    else:
        values = data
    return {str(node).replace("\\", "/") for node in values}


def _junit_node_id(case: ET.Element) -> str | None:
    file_attr = case.attrib.get("file", "").replace("\\", "/")
    classname = case.attrib.get("classname", "")
    name = case.attrib.get("name", "")
    if not name:
        return None
    class_parts = [part for part in classname.split(".") if part]
    extra_classes: list[str] = []
    if file_attr:
        path = file_attr
        module_name = Path(path).stem
        if module_name in class_parts:
            index = class_parts.index(module_name)
            extra_classes = class_parts[index + 1 :]
    else:
        module_index = next(
            (i for i, part in enumerate(class_parts) if part.startswith("test_")), None
        )
        if module_index is None:
            return None
        path = "/".join(class_parts[: module_index + 1]) + ".py"
        extra_classes = class_parts[module_index + 1 :]
    components = [path, *extra_classes, name]
    return "::".join(component for component in components if component)


def parse_junit_results(path: Path | str) -> dict[str, str]:
    """Map pytest node IDs to passed/failed/skipped from JUnit XML."""

    tree = ET.parse(path)
    results: dict[str, str] = {}
    for case in tree.getroot().iter("testcase"):
        node_id = _junit_node_id(case)
        if node_id is None:
            continue
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        results[node_id] = status
    return results


def _rows(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, list):
        return [row for row in manifest if isinstance(row, dict)]
    if isinstance(manifest, dict):
        for key in ("requirements", "rows", "items"):
            value = manifest.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _implementation_path(reference: str) -> str:
    value = reference.split("#", 1)[0]
    # Support path.py:symbol while preserving Windows drive notation.
    if ".py:" in value:
        value = value.split(".py:", 1)[0] + ".py"
    return value.replace("\\", "/")


def verify_traceability(
    manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    collected_nodes: Iterable[str],
    junit_results: Mapping[str, str],
    *,
    root: Path | str,
) -> dict[str, Any]:
    """Verify concrete per-requirement implementation and test evidence."""

    base = Path(root).resolve()
    collected = {node.replace("\\", "/") for node in collected_nodes}
    rows = _rows(manifest)
    seen: set[str] = set()
    seen_catalog_test_ids: set[str] = set()
    checked: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        requirement_id = str(row.get("requirement_id") or row.get("id") or "").strip()
        catalog_test_id = str(row.get("catalog_test_id") or "").strip()
        implementation_refs = _as_list(row.get("implementation_refs") or row.get("implementation"))
        pytest_nodes = _as_list(
            row.get("pytest_nodes") or row.get("test_nodes") or row.get("pytest_node_ids")
        )
        issues: list[str] = []
        if not requirement_id:
            issues.append("missing requirement_id")
        elif requirement_id in seen:
            issues.append("duplicate requirement_id")
        seen.add(requirement_id)
        if not catalog_test_id:
            issues.append("missing catalog_test_id")
        elif catalog_test_id in seen_catalog_test_ids:
            issues.append("duplicate catalog_test_id")
        seen_catalog_test_ids.add(catalog_test_id)
        if not implementation_refs:
            issues.append("missing implementation_refs")
        for reference in implementation_refs:
            rel = _implementation_path(reference)
            candidate = (base / rel).resolve()
            try:
                candidate.relative_to(base)
            except ValueError:
                issues.append(f"implementation escapes root: {reference}")
                continue
            if not candidate.is_file():
                issues.append(f"implementation missing: {reference}")
        if not pytest_nodes:
            issues.append("missing pytest_nodes")
        for node in pytest_nodes:
            normalized = node.replace("\\", "/")
            if normalized not in collected:
                issues.append(f"pytest node not collected: {node}")
            outcome = junit_results.get(normalized)
            if outcome != "passed":
                issues.append(f"pytest node outcome is {outcome or 'missing'}: {node}")
        checked.append(
            {
                "index": index,
                "requirement_id": requirement_id,
                "catalog_test_id": catalog_test_id,
                "implementation_refs": implementation_refs,
                "pytest_nodes": pytest_nodes,
                "status": "VERIFIED" if not issues else "FAILED",
                "issues": issues,
            }
        )

    verified = sum(item["status"] == "VERIFIED" for item in checked)
    return {
        "status": "PASS" if rows and verified == len(rows) else "FAIL",
        "requirements_total": len(rows),
        "requirements_verified": verified,
        "requirements_failed": len(rows) - verified,
        "requirements": checked,
    }


def stamp_json_report(path: Path | str, source_root_hash: str) -> None:
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        data = {"payload": data}
    data["source_root_hash"] = source_root_hash
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stamp_junit_report(path: Path | str, source_root_hash: str) -> None:
    target = Path(path)
    tree = ET.parse(target)
    root = tree.getroot()
    root.set("source_root_hash", source_root_hash)
    tree.write(target, encoding="utf-8", xml_declaration=True)


def verify_evidence_binding(paths: Iterable[Path | str], expected_hash: str) -> dict[str, Any]:
    checked: list[dict[str, str]] = []
    for raw in paths:
        path = Path(raw)
        actual = ""
        error = ""
        try:
            if path.suffix.lower() == ".xml":
                actual = ET.parse(path).getroot().attrib.get("source_root_hash", "")
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                actual = str(data.get("source_root_hash", "")) if isinstance(data, dict) else ""
        except (OSError, ValueError, ET.ParseError) as exc:
            error = str(exc)
        status = "PASS" if actual == expected_hash and not error else "FAIL"
        checked.append({"path": str(path), "actual": actual, "status": status, "error": error})
    return {
        "status": (
            "PASS" if checked and all(item["status"] == "PASS" for item in checked) else "FAIL"
        ),
        "files": checked,
    }
