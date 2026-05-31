from pathlib import Path

from tools import run_quality_gate


def test_quality_gate_subprocess_fallback_is_explicitly_unsafe() -> None:
    source = Path("tools/run_quality_gate.py").read_text(encoding="utf-8")
    fallback_call = '[py, "tools/run_tests_no_pytest.py"]'
    assert "--allow-subprocess-fallback" in source
    assert source.index(fallback_call) > source.index("if args.allow_subprocess_fallback:")
    assert '"unsafe_metadata"' in source


def test_quality_gate_requires_dev_tools_by_default() -> None:
    assert (
        run_quality_gate.should_require_dev_tools(
            strict_dev_tools=False,
            allow_missing_dev_tools=False,
        )
        is True
    )
    assert (
        run_quality_gate.should_require_dev_tools(
            strict_dev_tools=False,
            allow_missing_dev_tools=True,
        )
        is False
    )
    assert (
        run_quality_gate.should_require_dev_tools(
            strict_dev_tools=True,
            allow_missing_dev_tools=True,
        )
        is True
    )


def test_quality_gate_default_artifacts_do_not_write_repo_root() -> None:
    parser_defaults = [
        run_quality_gate.artifact_path(".release_gate_reports/QUALITY_GATE_LOCAL_v2_16_0.json"),
        run_quality_gate.artifact_path(".release_gate_reports/QUALITY_GATE_v2_16_0.json"),
        run_quality_gate.artifact_path(".release_gate_reports/BUILTIN_COVERAGE_v2_16_0.json"),
    ]

    assert all(".release_gate_reports" in path.parts for path in parser_defaults)


def test_quality_gate_runs_pytest_without_cov_args_when_pytest_cov_is_missing(monkeypatch) -> None:
    calls = []

    def fake_has_module(name: str) -> bool:
        return name == "pytest"

    def fake_run_cmd(cmd, *, required, timeout=300):
        calls.append((cmd, required, timeout))
        return {"cmd": cmd, "ok": True, "required": required}

    monkeypatch.setattr(run_quality_gate, "has_module", fake_has_module)
    monkeypatch.setattr(run_quality_gate, "run_cmd", fake_run_cmd)

    steps = run_quality_gate.pytest_gate_steps("/python", strict_dev_tools=True)

    assert calls == [(["/python", "-m", "pytest"], True, 300)]
    assert not any(arg.startswith("--cov") for arg in calls[0][0])
    assert steps[1]["cmd"] == ["pytest-cov"]
    assert steps[1]["required"] is True
    assert steps[1]["ok"] is False


def test_quality_gate_uses_cov_args_when_pytest_cov_is_available(monkeypatch) -> None:
    calls = []

    def fake_has_module(name: str) -> bool:
        return name in {"pytest", "pytest_cov"}

    def fake_run_cmd(cmd, *, required, timeout=300):
        calls.append((cmd, required, timeout))
        return {"cmd": cmd, "ok": True, "required": required}

    monkeypatch.setattr(run_quality_gate, "has_module", fake_has_module)
    monkeypatch.setattr(run_quality_gate, "run_cmd", fake_run_cmd)

    steps = run_quality_gate.pytest_gate_steps("/python", strict_dev_tools=True)

    assert calls == [
        (
            ["/python", "-m", "pytest", "--cov=pine2ast", "--cov-report=term-missing"],
            True,
            300,
        )
    ]
    assert steps == [{"cmd": calls[0][0], "ok": True, "required": True}]
