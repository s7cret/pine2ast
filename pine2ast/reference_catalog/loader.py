from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from pine2ast.reference_catalog.schema import CatalogEntry

CATALOG_RESOURCE = "pine_v6_reference_catalog.json"
MATRIX_RESOURCE = "parity_matrix.json"


def _resource_path(name: str) -> Path:
    return Path(str(files("pine2ast.reference_catalog").joinpath(name)))


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path) if path is not None else _resource_path(CATALOG_RESOURCE)
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def load_entries(path: str | Path | None = None) -> list[CatalogEntry]:
    payload = load_catalog(path)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("catalog entries must be an array")
    return [CatalogEntry.from_dict(item) for item in entries]


def load_parity_matrix(path: str | Path | None = None) -> dict[str, Any]:
    matrix_path = Path(path) if path is not None else _resource_path(MATRIX_RESOURCE)
    return json.loads(matrix_path.read_text(encoding="utf-8"))
