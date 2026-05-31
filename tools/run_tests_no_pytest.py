"""Tiny stdlib-only runner for environments where pytest is not installed.

By default it executes plain ``test_*`` functions from ``tests/unit``. Pass
``--include-integration`` to also execute ``tests/integration``. The runner is
not a pytest replacement: pytest-only modules are reported as controlled skips
when pytest is unavailable, and unsupported fixtures/decorators are skipped
rather than crashing the release fallback gate.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).absolute().parents[1]
include_integration = "--include-integration" in sys.argv
TEST_DIRS = [ROOT / "tests" / "unit"]
if include_integration:
    TEST_DIRS.append(ROOT / "tests" / "integration")


def _pytest_available() -> bool:
    return importlib.util.find_spec("pytest") is not None


def _requires_pytest(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return "import pytest" in text or "from pytest" in text or "pytest." in text


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


PYTEST_AVAILABLE = _pytest_available()
failures: list[tuple[str, str, BaseException]] = []
passed = 0
skipped = 0
executed = 0

for test_dir in TEST_DIRS:
    if not test_dir.exists():
        continue
    for path in sorted(test_dir.glob("test_*.py")):
        rel = f"{test_dir.name}/{path.name}"
        print(f"FILE {rel}", flush=True)
        if not PYTEST_AVAILABLE and _requires_pytest(path):
            skipped += 1
            print(f"  SKIP module requires pytest: {rel}", flush=True)
            continue
        try:
            mod = _load_module(path)
        except ModuleNotFoundError as exc:
            if exc.name == "pytest":
                skipped += 1
                print(f"  SKIP module requires pytest: {rel}", flush=True)
                continue
            failures.append((path.name, "<module import>", exc))
            print(f"FAIL {path.name}::<module import>: {exc!r}", flush=True)
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append((path.name, "<module import>", exc))
            print(f"FAIL {path.name}::<module import>: {exc!r}", flush=True)
            continue

        for name, func in sorted(vars(mod).items()):
            if not (name.startswith("test_") and callable(func)):
                continue
            sig = inspect.signature(func)
            unsupported = sorted(set(sig.parameters) - {"tmp_path"})
            if unsupported:
                skipped += 1
                print(
                    f"  SKIP {name}: unsupported pytest fixtures {', '.join(unsupported)}",
                    flush=True,
                )
                continue
            executed += 1
            print(f"  RUN {name}", flush=True)
            try:
                if "tmp_path" in sig.parameters:
                    with tempfile.TemporaryDirectory() as td:
                        func(Path(td))
                else:
                    func()
                passed += 1
                print(f"  OK {name}", flush=True)
            except Exception as exc:  # noqa: BLE001
                failures.append((path.name, name, exc))
                print(f"FAIL {path.name}::{name}: {exc!r}", flush=True)

print(
    f"summary: {passed} passed / {skipped} skipped / {len(failures)} failed / {executed} executed",
    flush=True,
)
if failures:
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
