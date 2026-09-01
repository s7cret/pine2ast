from __future__ import annotations

import random
import string

from .introspection import FrontendIntrospectionError, effective_version, parse_source, result_ok
from .model import GateFinding, GateResult, content_hash


def _title(rng: random.Random) -> str:
    return "fuzz-" + "".join(rng.choice(string.ascii_lowercase) for _ in range(10))


def _valid_source(version: int, rng: random.Random, *, explicit: bool = True) -> str:
    annotation = f"//@version={version}\n" if explicit else ""
    declaration = "study" if version <= 4 else "indicator"
    return (
        f"{annotation}// {rng.randrange(0, 10**9)}\n"
        f'{declaration}("{_title(rng)}")\n'
        f"x = close + {rng.randrange(0, 100)}\n"
    )


def run_fuzz_gate(*, cases: int = 2000, seed: int = 0x50A2) -> GateResult:
    """Deterministically fuzz the one-version kernel across Pine v1-v6."""

    rng = random.Random(seed)
    findings: list[GateFinding] = []
    shape_counts: dict[str, int] = {}
    transcript: list[tuple[str, int | None, bool]] = []

    for index in range(cases):
        shape = index % 11
        spaces = " " * rng.randrange(0, 4)
        if shape <= 5:
            version = shape + 1
            source = _valid_source(version, rng, explicit=version != 1)
            expected_version, expected_ok = version, True
            label = f"valid-v{version}"
        elif shape == 6:
            source = _valid_source(1, rng, explicit=False)
            expected_version, expected_ok = 1, True
            label = "default-v1"
        elif shape == 7:
            version = rng.randrange(7, 100)
            source = f'{spaces}//@version={version}\nindicator("{_title(rng)}")\n'
            expected_version, expected_ok = None, False
            label = "future"
        elif shape == 8:
            source = f'//@version=6\n//@version=5\nindicator("{_title(rng)}")\n'
            expected_version, expected_ok = None, False
            label = "duplicate"
        elif shape == 9:
            source = f'//@version=4\nstudy("{_title(rng)}")\nmarker = "//@version=6"\n'
            expected_version, expected_ok = 4, True
            label = "fake-in-string"
        else:
            source = f'//@version=1\nstudy("{_title(rng)}")\nx := 1\n'
            expected_version, expected_ok = 1, False
            label = "v1-newer-operator"

        result = parse_source(source, source_name=f"fuzz-{index}.pine")
        ok = result_ok(result)
        observed_version: int | None = None
        try:
            observed_version = effective_version(result)
        except FrontendIntrospectionError:
            pass
        shape_counts[label] = shape_counts.get(label, 0) + 1
        transcript.append((label, observed_version, ok))
        if ok != expected_ok:
            findings.append(
                GateFinding(
                    "S5_FUZZ_OUTCOME",
                    f"case {index} ({label}) expected ok={expected_ok}, got {ok}",
                )
            )
            break
        if expected_version is not None and observed_version != expected_version:
            findings.append(
                GateFinding(
                    "S5_FUZZ_VERSION",
                    f"case {index} ({label}) expected version={expected_version}, got {observed_version}",
                )
            )
            break
        if expected_version is None and observed_version is not None:
            findings.append(
                GateFinding(
                    "S5_FUZZ_FALLBACK",
                    f"case {index} ({label}) unexpectedly produced Pine v{observed_version}",
                )
            )
            break

    return GateResult(
        "stage5.version-fuzz",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "requested_cases": cases,
            "executed_cases": sum(shape_counts.values()),
            "seed": seed,
            "shape_counts": shape_counts,
            "transcript_hash": content_hash(transcript),
        },
    )
