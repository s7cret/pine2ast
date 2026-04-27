# Mypy baseline v2.14.0

`mypy` is configured in `pyproject.toml` and wired into CI as an advisory baseline step for this hardening release. Production sign-off should promote the advisory step to blocking after the remaining type-noise, if any, is resolved in a normal dev environment with `pip install -e .[dev]`.
