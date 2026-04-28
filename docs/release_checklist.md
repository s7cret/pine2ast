# Release packaging checklist

This checklist is current for v3.4 production packaging. Strict oracle mode is the default. Pending oracle mode is allowed only for RC packages and must not be described as `oracle_verified`.

## v3.4 production gate

```bash
python -m ruff check .
python -m black --check .
python -m mypy pine2ast
python -m pytest tests/unit tests/integration --cov=pine2ast --cov-report=term-missing --cov-report=xml
/usr/bin/python tools/run_tests_no_pytest.py
/usr/bin/python tools/run_tests_no_pytest.py --include-integration
bash scripts/release_gate.sh
python tools/build_release_zip.py . pine2ast_interpipe_v3_4_oracle_verified.zip --manifest RELEASE_MANIFEST_v3_4_oracle_verified.json
python tools/check_release_manifest.py RELEASE_MANIFEST_v3_4_oracle_verified.json
sha256sum pine2ast_interpipe_v3_4_oracle_verified.zip
```

`scripts/release_gate.sh` writes final logs under `reports/final/`. The standalone stdlib runner logs should be captured to `reports/final/TEST_RUN_STDLIB_FINAL.log` during release preparation.

## RC-only pending oracle gate

Use this only before external TradingView evidence is complete:

```bash
bash scripts/release_gate.sh --allow-pending-oracle
```

RC artifacts must use an `oracle_pending` suffix and must not replace production final logs unless the release is intentionally marked as pending.

## Evidence layout

- Root `FINAL_AUDIT_vX_Y.md`, root manifest and root final logs describe the latest production release only.
- Historical root artifacts move to `reports/archive_pre_vX_Y/`.
- TradingView evidence directories must be kept immutable unless new real evidence is collected. Do not edit screenshots/DOM/body captures to manufacture pass/fail status.
- `reports/final/COMPILE_ORACLE_FINAL.json` is generated from `tests/fixtures/compile_oracle` metadata and must agree with the evidence claims in the audit.

## Archive policy

`tools/build_release_zip.py` builds deterministic ZIP archives by sorting entries, pinning ZIP timestamps to `1980-01-01 00:00:00`, and normalizing file permissions.

The archive excludes VCS/cache/build/virtualenv/temp folders, compiled/native artifacts, other archives, and likely secrets by filename fragment. The generated manifest records SHA-256, file count, exclusion policy and checks for pycache, temp/venv, and secret-like filenames.

## Final audit checklist

Before committing a release, verify:

- package version and changelog match;
- AST schema compatibility is stated;
- pytest and stdlib fallback gates have logs;
- quality gate and compile-oracle reports are present;
- root release logs point to the new archive;
- no active final document references stale `v3_2_oracle_pending` except inside archive/history directories;
- deferred items are named plainly rather than hidden behind broad compatibility claims.
