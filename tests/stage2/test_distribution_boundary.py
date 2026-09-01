from pathlib import Path

import pine2ast.api as public_api

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_runtime_sources_are_physically_absent():
    forbidden = [
        "pine2ast/language_profiles.py",
        "pine2ast/runtime_contract.py",
        "pine2ast/runtime_contract_v1_4",
        "pine2ast/compatibility",
        "pine2ast/semantic/builtin_registry.py",
        "pine2ast/semantic/builtins_v5.json",
        "pine2ast/semantic/builtins_v6.json",
    ]
    assert all(not (ROOT / item).exists() for item in forbidden)


def test_no_forbidden_legacy_identifiers_in_production_python():
    forbidden = {
        "strict_v6",
        "target_version",
        "language_version",
        "compatibility_mode",
        "runtime_contract_v1_4",
        "runtime_contract_profile",
        "legacy_4x",
        "strict_5x",
        "implicit_version_rewrite",
        "pine_language_profile",
        "OPENPINE_RC5_COMPILER_COMPAT",
        "_openpine_rc5_parse_options",
    }
    hits = []
    for path in (ROOT / "pine2ast").rglob("*.py"):
        if path.as_posix().endswith("/hardening/hygiene.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append((path.relative_to(ROOT).as_posix(), token))
    assert not hits


def test_native_rc6_api_never_exports_rc5_runtime_contract(monkeypatch):
    monkeypatch.setenv("OPENPINE_RC5_COMPILER_COMPAT", "1")

    assert not hasattr(public_api, "runtime_contract_v1_4_options")


def test_legacy_registry_inputs_are_audit_only():
    assert (ROOT / "catalog_migration_inputs/rc5/builtins_v5.rc5.json").exists()
    assert (ROOT / "catalog_migration_inputs/rc5/builtins_v6.rc5.json").exists()
