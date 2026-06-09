"""v5 mode + migration diagnostics: //@version=5 parses in compat mode, v6-only builtins emit V6_ONLY_BUILTIN warning."""
from pine2ast import parse_code, ParseOptions
from pine2ast.diagnostics import codes
from pine2ast.semantic.builtin_registry import load_builtin_registry


# v5 mode options: strict_v6=False so //@version=5 is accepted
V5_OPTS = ParseOptions(strict_v6=False)


def test_footprint_namespace_emits_migration_warning():
    """footprint.* is v6-only — v5 script gets a warning, not an error."""
    src = '''//@version=5
indicator("T")
x = footprint.buy_volume(0)
plot(close)
'''
    r = parse_code(src, V5_OPTS)
    assert r.ast is not None
    assert r.ast.version == 5
    mig_warnings = [d for d in r.diagnostics
                    if d.code == codes.V6_ONLY_BUILTIN and d.severity.value == "WARNING"]
    assert len(mig_warnings) >= 1, (
        f"Expected at least 1 V6_ONLY_BUILTIN warning, "
        f"got: {[(d.code, d.severity.value, d.message) for d in r.diagnostics]}"
    )
    # The footprint namespace usage must be WARNING, not ERROR
    footprint_diags = [d for d in r.diagnostics if 'footprint' in d.message]
    assert all(d.severity.value == "WARNING" for d in footprint_diags), (
        f"Expected all footprint diagnostics WARNING, "
        f"got: {[(d.code, d.severity.value) for d in footprint_diags]}"
    )


def test_currency_variable_emits_migration_warning():
    """currency.AED is v6-only — v5 script gets a warning, not an error."""
    src = '''//@version=5
indicator("T")
plot(currency.AED)
'''
    r = parse_code(src, V5_OPTS)
    assert r.ast is not None
    assert r.ast.version == 5
    aed_diags = [d for d in r.diagnostics if 'AED' in d.message]
    assert all(d.severity.value in ("WARNING", "INFO") for d in aed_diags), (
        f"Expected AED diagnostics WARNING/INFO, "
        f"got: {[(d.code, d.severity.value) for d in aed_diags]}"
    )


def test_v6_script_has_no_migration_warning():
    """v6 script with v6-only builtins stays clean."""
    src = '''//@version=6
indicator("T")
x = footprint.buy_volume(0)
plot(close)
'''
    r = parse_code(src)
    assert r.ast is not None
    assert r.ast.version == 6
    mig_warnings = [d for d in r.diagnostics if d.code == codes.V6_ONLY_BUILTIN]
    assert len(mig_warnings) == 0, f"v6 should not emit V6_ONLY_BUILTIN, got: {mig_warnings}"


def test_v5_native_builtin_clean():
    """ta.sma is in v5 — no migration warning."""
    src = '''//@version=5
indicator("T")
x = ta.sma(close, 14)
plot(x)
'''
    r = parse_code(src, V5_OPTS)
    assert r.ast is not None
    mig_warnings = [d for d in r.diagnostics if d.code == codes.V6_ONLY_BUILTIN]
    assert len(mig_warnings) == 0


def test_builtins_v5_subregistry_is_correct():
    """v5 registry is a strict subset of v6."""
    v5 = load_builtin_registry(pine_version=5)
    v6 = load_builtin_registry(pine_version=6)
    assert len(v5["functions"]) < len(v6["functions"])
    assert len(v5["methods"]) < len(v6["methods"])
    # v6-only entries absent from v5
    assert "footprint.buy_volume" not in v5["functions"]
    assert "volume_row.delta" not in v5["functions"]
    assert "currency.AED" not in v5["variables"]


def test_v5_unsupported_version_is_warning_not_error():
    """With strict_v6=False, //@version=5 emits UNSUPPORTED_VERSION as WARNING."""
    src = '''//@version=5
indicator("T")
plot(close)
'''
    r = parse_code(src, V5_OPTS)
    unsupported_errs = [d for d in r.diagnostics
                       if d.code == codes.UNSUPPORTED_VERSION and d.severity.value == "ERROR"]
    assert len(unsupported_errs) == 0
    unsupported_warns = [d for d in r.diagnostics
                        if d.code == codes.UNSUPPORTED_VERSION and d.severity.value == "WARNING"]
    assert len(unsupported_warns) >= 1


def test_unknown_namespace_still_errors_in_v5():
    """A namespace that is neither v5 nor v6 still errors in v5 (not downgraded)."""
    src = '''//@version=5
indicator("T")
x = totallyMadeUpNamespace.do_something()
'''
    r = parse_code(src, V5_OPTS)
    errs = [d for d in r.diagnostics
            if d.code == codes.UNDECLARED_VARIABLE
            and 'totallyMadeUpNamespace' in d.message
            and d.severity.value == "ERROR"]
    assert len(errs) >= 1, (
        f"Expected UNDECLARED_VARIABLE ERROR for non-v6 namespace, "
        f"got: {[(d.code, d.severity.value, d.message) for d in r.diagnostics]}"
    )


def test_volume_row_namespace_detected_as_v6_only():
    """volume_row.* is v6-only — v5 script gets a migration warning."""
    src = '''//@version=5
indicator("T")
x = volume_row.delta(0)
'''
    r = parse_code(src, V5_OPTS)
    mig_warnings = [d for d in r.diagnostics if d.code == codes.V6_ONLY_BUILTIN]
    assert len(mig_warnings) >= 1, (
        f"Expected V6_ONLY_BUILTIN for volume_row, "
        f"got: {[(d.code, d.severity.value, d.message) for d in r.diagnostics]}"
    )
