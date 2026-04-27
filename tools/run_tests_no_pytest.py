"""Tiny stdlib-only runner for environments where pytest is not installed.

By default it executes test_* functions from tests/unit. Pass
``--include-integration`` to also execute tests/integration. It supports tmp_path by
providing a temp dir Path. This runner intentionally avoids pytest and prints
file-level progress for low-resource agents.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]
include_integration = "--include-integration" in sys.argv
TEST_DIRS = [ROOT / "tests" / "unit"]
if include_integration:
    TEST_DIRS.append(ROOT / "tests" / "integration")
sys.path.insert(0, str(ROOT))

failures = []
count = 0
for test_dir in TEST_DIRS:
    if not test_dir.exists():
        continue
    for path in sorted(test_dir.glob("test_*.py")):
        print(f"FILE {test_dir.name}/{path.name}", flush=True)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        for name, func in sorted(vars(mod).items()):
            if name.startswith("test_") and callable(func):
                count += 1
                print(f"  RUN {name}", flush=True)
                try:
                    sig = inspect.signature(func)
                    if "tmp_path" in sig.parameters:
                        with tempfile.TemporaryDirectory() as td:
                            func(Path(td))
                    else:
                        func()
                    print(f"  OK {name}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    failures.append((path.name, name, exc))
                    print(f"FAIL {path.name}::{name}: {exc!r}", flush=True)
if failures:
    print(f"{len(failures)} failed / {count} executed", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)
print(f"{count} passed", flush=True)
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
