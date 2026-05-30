from pathlib import Path


def test_quality_gate_subprocess_fallback_is_explicitly_unsafe() -> None:
    source = Path("tools/run_quality_gate.py").read_text(encoding="utf-8")
    fallback_call = '[py, "tools/run_tests_no_pytest.py"]'
    assert "--allow-subprocess-fallback" in source
    assert source.index(fallback_call) > source.index("if args.allow_subprocess_fallback:")
    assert '"unsafe_metadata"' in source
