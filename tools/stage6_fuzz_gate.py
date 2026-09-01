#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import random
import string
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "stage6_reports"
REPORTS.mkdir(parents=True, exist_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pine2ast import parse_code  # noqa: E402

SEED = 600627
CASES = 5000
rng = random.Random(SEED)
counts = {}
failures = []
transcript = []


def ident():
    return rng.choice(string.ascii_lowercase) + "".join(
        rng.choice(string.ascii_lowercase + string.digits) for _ in range(rng.randint(2, 10))
    )


for index in range(CASES):
    shape = rng.randrange(10)
    version = rng.randint(1, 6)
    name = ident()
    decl = "study" if version <= 4 else "indicator"
    annotation = "" if version == 1 and rng.random() < 0.5 else f"//@version={version}\n"
    expected_version = version
    if shape == 0:
        source = f'{annotation}{decl}("{name}")\nx=close\n'
    elif shape == 1:
        source = f'{annotation}{decl}("{name}")\nx=open+high-low\n'
    elif shape == 2:
        call = "sma(close,3)" if version <= 4 else "ta.sma(close,3)"
        source = f'{annotation}{decl}("{name}")\nx={call}\n'
    elif shape == 3:
        source = f'//@version={rng.randint(7, 99)}\nindicator("{name}")\nx=close\n'
        expected_version = None
    elif shape == 4:
        source = f'//@version={version}\n//@version={version}\n{decl}("{name}")\nx=close\n'
        expected_version = None
    elif shape == 5:
        source = f'{annotation}{decl}("//@version=99 {name}")\nx=close\n'
    elif shape == 6:
        call = "ta.sma(close,3)" if version <= 4 else "sma(close,3)"
        source = f'{annotation}{decl}("{name}")\nx={call}\n'
    elif shape == 7:
        source = f'{annotation}{decl}("{name}")\nif close\n    x=1\n'
    elif shape == 8:
        source = f'{annotation}{decl}("{name}")\nbool x=na\n'
    else:
        source = f'{annotation}{decl}("{name}")\nx=close\n// {ident()}\n'
    try:
        result = parse_code(source)
        actual_version = (
            getattr(getattr(result.ast, "version_context", None), "pine_version", None)
            if result.ast is not None
            else None
        )
        has_blocking = any(d.severity.value in {"ERROR", "FATAL"} for d in result.diagnostics)
        expected_valid = {
            0: True,
            1: True,
            2: True,
            3: False,
            4: False,
            5: True,
            6: False,
            7: version in {2, 3, 4, 5},
            8: version in {4, 5},
            9: True,
        }[shape]
        if expected_version is not None and actual_version != expected_version:
            failures.append(
                {
                    "index": index,
                    "shape": shape,
                    "expected_version": expected_version,
                    "actual_version": actual_version,
                }
            )
        if expected_valid and (result.ast is None or has_blocking or not result.ok):
            failures.append(
                {
                    "index": index,
                    "shape": shape,
                    "expected": "valid",
                    "actual_version": actual_version,
                    "codes": sorted({d.code for d in result.diagnostics}),
                }
            )
        if not expected_valid and not has_blocking:
            failures.append(
                {
                    "index": index,
                    "shape": shape,
                    "expected": "fail_closed",
                    "actual_version": actual_version,
                }
            )
        codes = sorted({d.code for d in result.diagnostics})
        transcript.append((shape, expected_version, actual_version, codes))
        counts[str(shape)] = counts.get(str(shape), 0) + 1
    except Exception as exc:
        failures.append(
            {"index": index, "shape": shape, "exception": type(exc).__name__, "message": str(exc)}
        )
report = {
    "schema_id": "pine2ast.stage6.fuzz.v1",
    "seed": SEED,
    "case_count": CASES,
    "shape_counts": counts,
    "failure_count": len(failures),
    "failures": failures[:100],
    "transcript_hash": "sha256:"
    + sha256(json.dumps(transcript, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
}
(REPORTS / "fuzz-gate.json").write_text(json.dumps(report, indent=2) + "\n")
raise SystemExit(0 if not failures else 1)
