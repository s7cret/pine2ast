"""Structural checks for the concrete Stage 6 requirement evidence graph."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "docs" / "stage6_requirement_traceability.json"


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _requirements() -> list[dict[str, object]]:
    rows = _manifest().get("requirements")
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    return rows


def _node_function_exists(node_id: str) -> bool:
    parts = node_id.split("::")
    if len(parts) < 2:
        return False
    test_file = ROOT / parts[0]
    if not test_file.is_file():
        return False
    function_name = parts[-1].split("[", 1)[0]
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        for node in ast.walk(tree)
    )


def test_frontend_requirement_inventory_is_complete_and_unique() -> None:
    manifest = _manifest()
    rows = _requirements()
    assert manifest["scope"] == "pine2ast-frontend"
    assert len(rows) == 66
    requirement_ids = [str(row.get("requirement_id", "")) for row in rows]
    assert all(requirement_ids)
    assert len(requirement_ids) == len(set(requirement_ids))
    assert all(str(row.get("owner", "")).lower().startswith("pine2ast") for row in rows)


def test_every_requirement_has_existing_implementation_reference() -> None:
    implementation_refs: set[str] = set()
    for row in _requirements():
        refs = row.get("implementation_refs")
        assert isinstance(refs, list) and refs
        for raw in refs:
            reference = str(raw)
            assert not Path(reference).is_absolute()
            rel = reference.split("#", 1)[0]
            if ".py:" in rel:
                rel = rel.split(".py:", 1)[0] + ".py"
            target = (ROOT / rel).resolve()
            target.relative_to(ROOT)
            assert target.is_file(), reference
            implementation_refs.add(reference)
    # Prevent a mass mapping of all requirements to one generic file.
    assert len(implementation_refs) >= 5


def test_every_requirement_has_concrete_existing_pytest_node() -> None:
    concrete_nodes: set[str] = set()
    for row in _requirements():
        nodes = row.get("pytest_nodes")
        assert isinstance(nodes, list) and nodes
        for raw in nodes:
            node_id = str(raw).replace("\\", "/")
            assert node_id.startswith("tests/")
            assert "::test_" in node_id or "::Test" in node_id
            assert _node_function_exists(node_id), node_id
            concrete_nodes.add(node_id)
        catalog_test_id = str(row.get("catalog_test_id", ""))
        assert catalog_test_id.startswith("stage6.")
        assert catalog_test_id not in nodes
    # The graph must represent multiple independent behavior groups.
    assert len(concrete_nodes) >= 10


def test_documentation_references_use_official_tradingview_origin() -> None:
    for row in _requirements():
        docs_ref = str(row.get("docs_ref", ""))
        parsed = urlparse(docs_ref)
        assert parsed.scheme == "https"
        assert parsed.netloc == "www.tradingview.com"
