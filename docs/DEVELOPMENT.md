# Development

## Setup

```bash
python -m pip install -e '.[dev]'
```

## Core checks

```bash
python -m compileall -q pine2ast tests
python -m pytest
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term
python -m pine2ast.quality duplicates pine2ast
python -m pine2ast.quality architecture pine2ast --max-lines 700
python -m pine2ast.release --root .
python -m pine2ast.distribution manifest --root .
bash scripts/wheel_smoke.sh
```

## Signature and compatibility checks

```bash
python -m pine2ast.semantic.signature_coverage --version 5 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.semantic.signature_coverage --version 6 --fail-on-missing --fail-under-signature-ready-ratio 1.0
python -m pine2ast.release --root . --json RELEASE_MANIFEST.json
python -m pine2ast.distribution manifest --root .
bash scripts/wheel_smoke.sh
```

## Optional checks

Run these when the dev dependencies are installed:

```bash
python -m ruff check .
python -m black --check .
python -m mypy pine2ast
```

## Final release checklist

For the GitHub tag, use a clean clone or clean working tree and run:

```bash
python -m pip install -e '.[dev]'
bash scripts/release_gate.sh
python -m pine2ast.distribution build-zip --root . --output ../pine2ast-4.0.2.zip
unzip -tq ../pine2ast-4.0.2.zip
```

The wheel smoke is intentionally separate from the deterministic source zip: it builds a wheel with `pip wheel`, installs it into a temporary virtual environment, parses a minimal Pine v6 script, and checks that the packaged CLI contract entrypoint imports correctly.

For constrained automation environments where third-party dev tools are unavailable, do not mark `ruff`, `black`, or `mypy` as passed. Use:

```bash
python tools/run_quality_gate.py --allow-missing-dev-tools --json .release_gate_reports/QUALITY_GATE_LOCAL_v4_0_1.json
```

and require the full strict gate in CI before tagging.

## Documentation policy

`docs/` should contain only canonical 4.0 docs. Patch-cycle notes belong in release notes or PR descriptions, not committed as permanent documentation files. The release gate fails on legacy planning documents outside the canonical docs set.
