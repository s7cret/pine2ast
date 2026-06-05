from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOT = ROOT / "pine2ast"
FORBIDDEN_IMPORTS = ("pinelib", "backtest_engine", "openpine")


def test_pine2ast_frontend_does_not_import_runtime_or_orchestration_layers() -> None:
    offenders: list[str] = []
    for path in sorted(PRODUCTION_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORTS or alias.name.startswith(
                        tuple(name + "." for name in FORBIDDEN_IMPORTS)
                    ):
                        offenders.append(path.relative_to(ROOT).as_posix())
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in FORBIDDEN_IMPORTS or module.startswith(
                    tuple(name + "." for name in FORBIDDEN_IMPORTS)
                ):
                    offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
