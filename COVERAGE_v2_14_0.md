# Coverage v2.14.0

Coverage is configured in `pyproject.toml` with `fail_under = 90` for the `pine2ast` package and is enforced by CI with:

```bash
python -m pytest --cov=pine2ast --cov-report=term-missing --cov-report=xml
```

The current sandbox does not have `pytest-cov` installed, so this artifact documents the configured gate rather than a local coverage percentage.
