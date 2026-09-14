import copy
import json
import subprocess
import sys
from pathlib import Path

from pine2ast.catalog import CatalogRepository, CatalogStatus, validate_catalog_pack

ROOT = Path(__file__).resolve().parents[2]


def test_all_six_packs_are_valid_and_hash_bound():
    repo = CatalogRepository.default()
    hashes = set()
    for version in range(1, 7):
        pack = repo.pack(version)
        validate_catalog_pack(pack)
        assert pack["pine_version"] == version
        assert repo.identity(version).catalog_hash == pack["catalog_hash"]
        hashes.add(pack["catalog_hash"])
    assert len(hashes) == 6


def test_historical_and_modern_statuses_are_honest():
    repo = CatalogRepository.default()
    for version in range(1, 5):
        identity = repo.identity(version)
        pack = repo.pack(version)
        assert identity.status is CatalogStatus.HISTORICAL_STATIC_SNAPSHOT
        assert "historical" in pack["coverage_basis"]
        assert pack["sections"]["functions"]
        assert pack["sections"]["variables"]
    for version in (5, 6):
        assert repo.identity(version).status is CatalogStatus.STATIC_COMPLETE
        assert repo.pack(version)["sections"]["functions"]


def test_cached_catalog_is_not_mutable_by_consumers():
    repo = CatalogRepository.default()
    first = repo.view(6)
    original = copy.deepcopy(first)
    first["functions"].clear()
    second = repo.view(6)
    assert second == original


def test_sequential_deltas_contain_only_declared_operations():
    for version in range(1, 7):
        rows = [
            json.loads(line)
            for line in (ROOT / f"catalog_source/deltas/v{version}.jsonl").read_text().splitlines()
            if line
        ]
        assert rows
        assert all(row["op"] in {"ADD", "PATCH", "REMOVE", "RENAME"} for row in rows)
    v6_rows = [
        json.loads(line)
        for line in (ROOT / "catalog_source/deltas/v6.jsonl").read_text().splitlines()
        if line
    ]
    view = CatalogRepository.default().view(6)
    assert len(v6_rows) < sum(
        len(view[name]) for name in ("functions", "variables", "methods", "types", "namespaces")
    )


def test_migration_report_is_lossless_for_v5_v6_and_clean_for_all_versions():
    report = json.loads((ROOT / "catalog_reports/migration_report.json").read_text())
    assert report["ok"] is True
    assert report["migration_loss_count"] == 0
    assert all(value == 0 for value in report["invariants"].values())
    assert set(report["pack_hashes"]) == {"1", "2", "3", "4", "5", "6"}


def test_generated_catalog_has_no_drift_from_any_working_directory(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/catalog/build_catalog.py"),
            "--root",
            str(ROOT),
            "--check",
        ],
        cwd=tmp_path,
        check=True,
    )


# ---------------------------------------------------------------------------
# CAT-01a: barstate.* catalog rows
#
# The official Pine reference registry exposes exactly seven barstate.*
# variables (isfirst, islast, isnew, isrealtime, isconfirmed, ishistory,
# islastconfirmedhistory).  They have been present since Pine v1 and must
# not be backported or removed by any v1..v6 catalog pack.  These tests
# lock that contract in: they fail loudly if any row goes missing, if a
# modern-only barstate.* symbol sneaks into a historical pack, or if the
# first/last_observed_version metadata is rewritten.
# ---------------------------------------------------------------------------

_BARSTATE_OFFICIAL_VARIABLES: tuple[str, ...] = (
    "barstate.isconfirmed",
    "barstate.isfirst",
    "barstate.ishistory",
    "barstate.islast",
    "barstate.islastconfirmedhistory",
    "barstate.isnew",
    "barstate.isrealtime",
)


def _barstate_variables_in_pack(pack: dict) -> set[str]:
    return {
        name
        for name, definition in pack["sections"]["variables"].items()
        if name.startswith("barstate.")
    }


def _barstate_variables_in_view(view) -> set[str]:
    return {name for name in view["variables"] if name.startswith("barstate.")}


def test_barstate_namespace_is_present_in_every_pack():
    repo = CatalogRepository.default()
    for version in range(1, 7):
        pack = repo.pack(version)
        assert "barstate" in pack["sections"]["namespaces"], (
            f"barstate namespace missing from v{version} pack"
        )
        definition = pack["sections"]["namespaces"]["barstate"]
        assert definition["name"] == "barstate"
        assert definition["symbol_id"] == "pine:namespace:barstate"


def test_barstate_namespace_is_immutable_across_v1_through_v6():
    repo = CatalogRepository.default()
    symbol_ids = {
        version: repo.pack(version)["sections"]["namespaces"]["barstate"]["symbol_id"]
        for version in range(1, 7)
    }
    assert len(set(symbol_ids.values())) == 1, (
        f"barstate namespace symbol_id drifted across versions: {symbol_ids}"
    )


def test_barstate_variables_are_complete_in_every_pack():
    repo = CatalogRepository.default()
    expected = set(_BARSTATE_OFFICIAL_VARIABLES)
    for version in range(1, 7):
        pack = repo.pack(version)
        validate_catalog_pack(pack)
        observed = _barstate_variables_in_pack(pack)
        missing = expected - observed
        extra = observed - expected
        assert not missing, (
            f"v{version} pack is missing barstate variables: {sorted(missing)}"
        )
        assert not extra, (
            f"v{version} pack exposes undocumented barstate variables: {sorted(extra)}"
        )


def test_barstate_variable_inventory_does_not_shrink_across_versions():
    repo = CatalogRepository.default()
    per_version = {
        version: len(_barstate_variables_in_view(repo.view(version)))
        for version in range(1, 7)
    }
    counts = set(per_version.values())
    assert len(counts) == 1, (
        f"barstate variable inventory shrank or grew across versions: {per_version}"
    )


def test_no_barstate_symbol_is_backported_from_modern_into_historical():
    """NEGATIVE-pair guard: every barstate.* variable present in v6 must
    already exist in v1 and v2.  A modern-only barstate symbol sneaking
    into a historical pack would be a backport and is rejected here.
    """
    repo = CatalogRepository.default()
    v6_barstate = _barstate_variables_in_view(repo.view(6))
    v1_barstate = _barstate_variables_in_view(repo.view(1))
    v2_barstate = _barstate_variables_in_view(repo.view(2))
    backported_into_v1 = v6_barstate - v1_barstate
    backported_into_v2 = v6_barstate - v2_barstate
    assert not backported_into_v1, (
        f"v1 exposes barstate variables that are v6-only (backport): "
        f"{sorted(backported_into_v1)}"
    )
    assert not backported_into_v2, (
        f"v2 exposes barstate variables that are v6-only (backport): "
        f"{sorted(backported_into_v2)}"
    )


def test_barstate_symbols_metadata_spans_full_v1_to_v6_range():
    """symbols.jsonl is the canonical inventory; barstate entries must
    claim first_observed_version=1 and last_observed_version=6.  Any
    rewrite of these ranges is a regression and is rejected here.
    """
    rows = [
        json.loads(line)
        for line in (ROOT / "catalog_source/symbols.jsonl").read_text().splitlines()
        if line
    ]
    by_name = {row["canonical_name"]: row for row in rows}
    assert "barstate" in by_name
    barstate_ns = by_name["barstate"]
    assert barstate_ns["first_observed_version"] == 1
    assert barstate_ns["last_observed_version"] == 6
    assert barstate_ns["kind"] == "namespace"
    assert barstate_ns["section"] == "namespaces"
    for canonical_name in _BARSTATE_OFFICIAL_VARIABLES:
        assert canonical_name in by_name, (
            f"symbols.jsonl is missing {canonical_name}"
        )
        entry = by_name[canonical_name]
        assert entry["first_observed_version"] == 1, (
            f"{canonical_name} first_observed_version drifted to "
            f"{entry['first_observed_version']}"
        )
        assert entry["last_observed_version"] == 6, (
            f"{canonical_name} last_observed_version drifted to "
            f"{entry['last_observed_version']}"
        )
        assert entry["kind"] == "variable"
        assert entry["section"] == "variables"


def test_barstate_symbols_metadata_matches_pack_inventory_exactly():
    rows = [
        json.loads(line)
        for line in (ROOT / "catalog_source/symbols.jsonl").read_text().splitlines()
        if line
    ]
    by_name = {row["canonical_name"]: row for row in rows}
    declared = {name for name in by_name if name.startswith("barstate.")}
    assert declared == set(_BARSTATE_OFFICIAL_VARIABLES), (
        "symbols.jsonl barstate inventory drifted: "
        f"declared={sorted(declared)} expected={sorted(_BARSTATE_OFFICIAL_VARIABLES)}"
    )


def test_v1_delta_originally_added_the_barstate_namespace_and_variables():
    """The historical v1 snapshot must declare barstate as a namespace
    and every official barstate.* variable as a variable, via ADD ops.
    Any change here means the historical origin has been rewritten.
    """
    v1_rows = [
        json.loads(line)
        for line in (ROOT / "catalog_source/deltas/v1.jsonl").read_text().splitlines()
        if line
    ]
    namespace_rows = {
        row["name"]: row
        for row in v1_rows
        if row.get("op") == "ADD" and row.get("section") == "namespaces"
    }
    variable_rows = {
        row["name"]: row
        for row in v1_rows
        if row.get("op") == "ADD" and row.get("section") == "variables"
    }
    assert "barstate" in namespace_rows, "v1 delta did not add barstate namespace"
    assert namespace_rows["barstate"]["symbol_id"] == "pine:namespace:barstate"
    for canonical_name in _BARSTATE_OFFICIAL_VARIABLES:
        assert canonical_name in variable_rows, (
            f"v1 delta did not add {canonical_name}"
        )
        assert variable_rows[canonical_name]["symbol_id"] == (
            f"pine:variable:{canonical_name}"
        )


def test_barstate_entries_have_no_remove_ops_in_any_delta():
    """barstate.* is part of the historical public surface from v1
    onward; no delta may REMOVE any barstate row, otherwise modern code
    would silently lose access to a historical API.
    """
    for version in range(1, 7):
        rows = [
            json.loads(line)
            for line in (ROOT / f"catalog_source/deltas/v{version}.jsonl")
            .read_text()
            .splitlines()
            if line
        ]
        removes = [
            row
            for row in rows
            if row.get("op") == "REMOVE"
            and isinstance(row.get("symbol_id"), str)
            and (
                row["symbol_id"].endswith(":barstate")
                or ":barstate." in row["symbol_id"]
            )
        ]
        assert not removes, (
            f"v{version} delta contains barstate REMOVE rows: {removes}"
        )


def test_barstate_namespace_appears_only_once_per_pack():
    repo = CatalogRepository.default()
    for version in range(1, 7):
        pack = repo.pack(version)
        assert pack["sections"]["namespaces"].get("barstate", {}).get("name") == "barstate"
        barstate_ids = [
            name
            for name, definition in pack["sections"]["namespaces"].items()
            if definition.get("symbol_id", "").endswith(":barstate")
        ]
        assert len(barstate_ids) == 1, (
            f"v{version} pack has duplicate barstate namespace entries: {barstate_ids}"
        )


# ---------------------------------------------------------------------------
# CAT-01b: input.* core (bool/color/float/string/source/integer/int/timeframe)
#
# Authority is the in-tree catalog_source/symbols.jsonl and the v1..v6
# deltas.  The historical v1..v4 surface exposes typed inputs as
# constants and variables keyed under the official Pine names
# (input.bool, input.color, input.float, input.integer, input.source,
# input.string).  Pine v5 removes those legacy rows and introduces typed
# function families instead; the v5+ family adds input.int (no legacy
# alias) and input.timeframe (no legacy counterpart).
#
# These tests lock in the exact kind/section/first/last metadata for
# every official row and reject modern-only rows leaking into v1..v4.
# Out-of-scope families (input.enum, input.price, input.session,
# input.symbol, input.text_area, input.time, input.resolution, bare
# input) are not asserted here — they remain for CAT-01c-input-rest.
# ---------------------------------------------------------------------------

_INPUT_CORE_LEGACY_NAMES: tuple[str, ...] = (
    "input.bool",
    "input.color",
    "input.float",
    "input.integer",
    "input.source",
    "input.string",
)


def _input_core_constant_symbol_id(name: str) -> str:
    return f"pine:constant:legacy.{name}"


def _input_core_variable_symbol_id(name: str) -> str:
    return f"pine:variable:legacy.{name}"


def _input_core_function_symbol_id(name: str) -> str:
    return f"pine:function:{name}"


def _read_symbols_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / "catalog_source/symbols.jsonl").read_text().splitlines()
        if line
    ]


def _read_delta_rows(version: int) -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / f"catalog_source/deltas/v{version}.jsonl")
        .read_text()
        .splitlines()
        if line
    ]


def test_input_core_legacy_constant_rows_have_full_v1_to_v4_range():
    """Every official input.* core constant must claim
    first_observed_version=1 and last_observed_version=4 in symbols.jsonl.
    """
    rows = _read_symbols_rows()
    by_name_kind = {(row["canonical_name"], row["kind"]): row for row in rows}
    for name in _INPUT_CORE_LEGACY_NAMES:
        entry = by_name_kind.get((name, "constant"))
        assert entry is not None, (
            f"symbols.jsonl is missing constant row for {name}"
        )
        assert entry["first_observed_version"] == 1, (
            f"{name} constant first_observed_version drifted to "
            f"{entry['first_observed_version']}"
        )
        assert entry["last_observed_version"] == 4, (
            f"{name} constant last_observed_version drifted to "
            f"{entry['last_observed_version']}"
        )
        assert entry["section"] == "constants"
        assert entry["symbol_id"] == _input_core_constant_symbol_id(name)


def test_input_core_legacy_variable_rows_have_full_v1_to_v4_range():
    """Every official input.* core variable must claim
    first_observed_version=1 and last_observed_version=4 in symbols.jsonl.
    """
    rows = _read_symbols_rows()
    by_name_kind = {(row["canonical_name"], row["kind"]): row for row in rows}
    for name in _INPUT_CORE_LEGACY_NAMES:
        entry = by_name_kind.get((name, "variable"))
        assert entry is not None, (
            f"symbols.jsonl is missing variable row for {name}"
        )
        assert entry["first_observed_version"] == 1, (
            f"{name} variable first_observed_version drifted to "
            f"{entry['first_observed_version']}"
        )
        assert entry["last_observed_version"] == 4, (
            f"{name} variable last_observed_version drifted to "
            f"{entry['last_observed_version']}"
        )
        assert entry["section"] == "variables"
        assert entry["symbol_id"] == _input_core_variable_symbol_id(name)


def test_input_core_modern_function_rows_have_full_v5_to_v6_range():
    """Every official input.* core function must claim
    first_observed_version=5 and last_observed_version=6 in symbols.jsonl.

    input.int and input.timeframe are v5+ only — they have no legacy
    constant/variable counterparts in v1..v4.
    """
    rows = _read_symbols_rows()
    by_name_kind = {(row["canonical_name"], row["kind"]): row for row in rows}
    modern_names = (
        "input.bool",
        "input.color",
        "input.float",
        "input.int",
        "input.source",
        "input.string",
        "input.timeframe",
    )
    for name in modern_names:
        entry = by_name_kind.get((name, "function"))
        assert entry is not None, (
            f"symbols.jsonl is missing function row for {name}"
        )
        assert entry["first_observed_version"] == 5, (
            f"{name} function first_observed_version drifted to "
            f"{entry['first_observed_version']}"
        )
        assert entry["last_observed_version"] == 6, (
            f"{name} function last_observed_version drifted to "
            f"{entry['last_observed_version']}"
        )
        assert entry["section"] == "functions"
        assert entry["symbol_id"] == _input_core_function_symbol_id(name)


def test_input_core_legacy_rows_present_in_every_historical_pack():
    """v1..v4 packs must each contain every official input.* core
    constant AND every official input.* core variable.  No legacy row
    may be silently dropped from any historical pack.

    In v1..v3 the legacy constants are keyed by their short names
    (bool, color, float, integer, source, string); in v4 they are
    RENAMEd to their official dotted names (input.bool, ...).
    """
    repo = CatalogRepository.default()
    short_legacy_constants = {
        "input.bool": "bool",
        "input.color": "color",
        "input.float": "float",
        "input.integer": "integer",
        "input.source": "source",
        "input.string": "string",
    }
    for version in range(1, 5):
        pack = repo.pack(version)
        validate_catalog_pack(pack)
        constants = set(pack["sections"]["constants"])
        variables = set(pack["sections"]["variables"])
        expected_constant_keys = (
            {short_legacy_constants[name] for name in _INPUT_CORE_LEGACY_NAMES}
            if version < 4
            else set(_INPUT_CORE_LEGACY_NAMES)
        )
        for key in expected_constant_keys:
            assert key in constants, (
                f"v{version} pack is missing constant {key}"
            )
            if version < 4:
                # The short key's symbol_id already encodes the dotted
                # official name — confirm it matches.
                dotted = next(
                    name
                    for name, short in short_legacy_constants.items()
                    if short == key
                )
                assert pack["sections"]["constants"][key]["symbol_id"] == (
                    _input_core_constant_symbol_id(dotted)
                )
            else:
                assert pack["sections"]["constants"][key]["symbol_id"] == (
                    _input_core_constant_symbol_id(key)
                )
        for name in _INPUT_CORE_LEGACY_NAMES:
            assert name in variables, (
                f"v{version} pack is missing variable {name}"
            )
            assert pack["sections"]["variables"][name]["symbol_id"] == (
                _input_core_variable_symbol_id(name)
            )


def test_input_core_modern_function_rows_present_only_in_v5_v6_packs():
    """input.bool/color/float/source/string/int/timeframe functions are
    typed function families — they exist in v5 and v6 only and must
    not leak into v1..v4 historical packs.
    """
    repo = CatalogRepository.default()
    modern_names = (
        "input.bool",
        "input.color",
        "input.float",
        "input.int",
        "input.source",
        "input.string",
        "input.timeframe",
    )
    for version in range(1, 5):
        pack = repo.pack(version)
        functions = set(pack["sections"]["functions"])
        leaked = [name for name in modern_names if name in functions]
        assert not leaked, (
            f"v{version} pack leaks modern input.* core function rows: "
            f"{sorted(leaked)}"
        )
    for version in (5, 6):
        pack = repo.pack(version)
        functions = set(pack["sections"]["functions"])
        for name in modern_names:
            assert name in functions, (
                f"v{version} pack is missing function {name}"
            )
            assert pack["sections"]["functions"][name]["symbol_id"] == (
                _input_core_function_symbol_id(name)
            )


def test_input_core_modern_function_rows_excluded_from_legacy_sections_in_v5_v6():
    """v5/v6 packs remove the legacy constant/variable rows for the
    official input.* core families.  No legacy constant or variable row
    may persist after the v5 typed-input migration.
    """
    repo = CatalogRepository.default()
    for version in (5, 6):
        pack = repo.pack(version)
        constants = set(pack["sections"]["constants"])
        variables = set(pack["sections"]["variables"])
        for name in _INPUT_CORE_LEGACY_NAMES:
            assert name not in constants, (
                f"v{version} pack still exposes legacy constant {name} "
                f"after the typed-input migration"
            )
            assert name not in variables, (
                f"v{version} pack still exposes legacy variable {name} "
                f"after the typed-input migration"
            )


def test_input_core_modern_functions_are_exclusive_to_their_family():
    """input.integer (legacy) and input.int (v5+ function) are NOT
    aliases — symbols.jsonl must declare input.integer as a constant
    and variable only, and input.int as a function only.
    """
    rows = _read_symbols_rows()
    by_name_kind = {(row["canonical_name"], row["kind"]): row for row in rows}

    # input.integer is exclusively legacy (constant + variable, no function).
    assert (("input.integer", "constant")) in by_name_kind
    assert (("input.integer", "variable")) in by_name_kind
    assert (("input.integer", "function")) not in by_name_kind, (
        "input.integer must not be exposed as a function — that role is "
        "filled by input.int in v5+"
    )

    # input.int is exclusively modern (function only, no legacy counterpart).
    assert (("input.int", "function")) in by_name_kind
    assert (("input.int", "constant")) not in by_name_kind, (
        "input.int must not be exposed as a legacy constant"
    )
    assert (("input.int", "variable")) not in by_name_kind, (
        "input.int must not be exposed as a legacy variable"
    )


def test_input_core_no_modern_function_backports_into_historical_packs():
    """NEGATIVE-pair guard: no modern input.* core function row may
    appear in a v1..v4 pack.  The historical surface is a closed set;
    leaking a v5+ function into a historical pack is a backport.
    """
    repo = CatalogRepository.default()
    modern = {
        "input.bool",
        "input.color",
        "input.float",
        "input.int",
        "input.source",
        "input.string",
        "input.timeframe",
    }
    for version in range(1, 5):
        pack = repo.pack(version)
        functions = set(pack["sections"]["functions"])
        leaked = modern & functions
        assert not leaked, (
            f"v{version} pack backports modern input.* core function "
            f"rows: {sorted(leaked)}"
        )


def test_input_core_no_legacy_rows_survive_into_modern_packs():
    """NEGATIVE-pair guard: every legacy input.* core constant and
    variable must have been removed by v5.  Any residual legacy row
    in a modern pack means the v5 typed-input migration is incomplete.
    """
    repo = CatalogRepository.default()
    for version in (5, 6):
        pack = repo.pack(version)
        constants = set(pack["sections"]["constants"])
        variables = set(pack["sections"]["variables"])
        surviving_constants = constants & set(_INPUT_CORE_LEGACY_NAMES)
        surviving_variables = variables & set(_INPUT_CORE_LEGACY_NAMES)
        assert not surviving_constants, (
            f"v{version} pack keeps legacy input.* core constants: "
            f"{sorted(surviving_constants)}"
        )
        assert not surviving_variables, (
            f"v{version} pack keeps legacy input.* core variables: "
            f"{sorted(surviving_variables)}"
        )


def test_input_core_v1_delta_originally_added_legacy_constants_and_variables():
    """v1 must declare each legacy input.* core constant and variable
    via ADD ops.  Any change here rewrites the historical origin.

    v1 ADD constants are keyed by short names (bool, color, ...) but
    their symbol_id encodes the official dotted form.  v1 ADD
    variables are already keyed by the dotted official name.
    """
    v1_rows = _read_delta_rows(1)
    constant_rows = {
        row["symbol_id"]: row
        for row in v1_rows
        if row.get("op") == "ADD" and row.get("section") == "constants"
    }
    variable_rows = {
        row["name"]: row
        for row in v1_rows
        if row.get("op") == "ADD" and row.get("section") == "variables"
    }
    short_legacy_constants = {
        "input.bool": "bool",
        "input.color": "color",
        "input.float": "float",
        "input.integer": "integer",
        "input.source": "source",
        "input.string": "string",
    }
    for name, short in short_legacy_constants.items():
        expected_symbol_id = _input_core_constant_symbol_id(name)
        assert expected_symbol_id in constant_rows, (
            f"v1 delta did not add legacy constant {short} ("
            f"symbol_id={expected_symbol_id})"
        )
    for name in _INPUT_CORE_LEGACY_NAMES:
        assert name in variable_rows, (
            f"v1 delta did not add legacy variable {name}"
        )
        assert variable_rows[name]["symbol_id"] == (
            _input_core_variable_symbol_id(name)
        )


def test_input_core_v4_delta_renames_legacy_constants_to_dotted_names():
    """v4 must RENAME the short legacy constant keys (bool, color,
    float, integer, source, string) to their official dotted names
    (input.bool, input.color, ...).  Any other value rewrites history.
    """
    v4_rows = _read_delta_rows(4)
    renames = {
        row["symbol_id"]: row
        for row in v4_rows
        if row.get("op") == "RENAME" and row.get("section") == "constants"
    }
    for name in _INPUT_CORE_LEGACY_NAMES:
        expected_symbol_id = _input_core_constant_symbol_id(name)
        assert expected_symbol_id in renames, (
            f"v4 delta did not RENAME legacy constant to {name} "
            f"(symbol_id={expected_symbol_id})"
        )


def test_input_core_v5_delta_adds_modern_functions_and_removes_legacy_rows():
    """v5 must ADD the typed-function rows for every official input.*
    core family and REMOVE the legacy constant/variable rows for the
    same families.  The migration is the boundary between historical
    and modern API.

    REMOVE rows carry only {op, symbol_id} — the section is encoded
    in the symbol_id prefix.
    """
    v5_rows = _read_delta_rows(5)
    add_functions = {
        row["name"]: row
        for row in v5_rows
        if row.get("op") == "ADD" and row.get("section") == "functions"
    }
    removed_constant_symbol_ids = {
        row["symbol_id"]
        for row in v5_rows
        if row.get("op") == "REMOVE"
        and isinstance(row.get("symbol_id"), str)
        and row["symbol_id"].startswith("pine:constant:")
    }
    removed_variable_symbol_ids = {
        row["symbol_id"]
        for row in v5_rows
        if row.get("op") == "REMOVE"
        and isinstance(row.get("symbol_id"), str)
        and row["symbol_id"].startswith("pine:variable:")
    }
    modern_names = (
        "input.bool",
        "input.color",
        "input.float",
        "input.int",
        "input.source",
        "input.string",
        "input.timeframe",
    )
    for name in modern_names:
        assert name in add_functions, (
            f"v5 delta did not ADD typed function {name}"
        )
        assert add_functions[name]["symbol_id"] == (
            _input_core_function_symbol_id(name)
        )
    for name in _INPUT_CORE_LEGACY_NAMES:
        assert _input_core_constant_symbol_id(name) in removed_constant_symbol_ids, (
            f"v5 delta did not REMOVE legacy constant {name}"
        )
        assert _input_core_variable_symbol_id(name) in removed_variable_symbol_ids, (
            f"v5 delta did not REMOVE legacy variable {name}"
        )


def test_input_core_inventory_is_stable_across_modern_packs():
    """v5 and v6 packs must agree on the typed-function inventory for
    the seven canonical input.* core families.  No inventory shrink
    is allowed across modern packs.
    """
    repo = CatalogRepository.default()
    modern_names = {
        "input.bool",
        "input.color",
        "input.float",
        "input.int",
        "input.source",
        "input.string",
        "input.timeframe",
    }
    per_version = {
        version: {
            name
            for name in repo.pack(version)["sections"]["functions"]
            if name in modern_names
        }
        for version in (5, 6)
    }
    counts = {version: len(rows) for version, rows in per_version.items()}
    assert counts[5] == counts[6] == len(modern_names), (
        f"input.* core modern function inventory shrank: {counts}"
    )
    assert per_version[5] == per_version[6] == modern_names, (
        f"input.* core modern function inventory drifted between "
        f"v5 and v6: v5={sorted(per_version[5])} v6={sorted(per_version[6])}"
    )


def test_input_core_legacy_inventory_is_stable_across_historical_packs():
    """v1..v4 packs must agree on the legacy input.* core inventory
    (variable rows always use the dotted official name; constants
    transition from short keys in v1..v3 to dotted keys in v4 via the
    v4 RENAME delta).  No inventory shrink is allowed across historical
    packs.
    """
    repo = CatalogRepository.default()
    per_version_variables = {
        version: {
            name
            for name in repo.pack(version)["sections"]["variables"]
            if name in _INPUT_CORE_LEGACY_NAMES
        }
        for version in range(1, 5)
    }
    counts = {version: len(rows) for version, rows in per_version_variables.items()}
    assert all(count == len(_INPUT_CORE_LEGACY_NAMES) for count in counts.values()), (
        f"input.* core legacy variable inventory shrank across v1..v4: {counts}"
    )
    expected_variables = set(_INPUT_CORE_LEGACY_NAMES)
    drift = {v: sorted(r) for v, r in per_version_variables.items()}
    assert all(rows == expected_variables for rows in per_version_variables.values()), (
        f"input.* core legacy variable inventory drifted across v1..v4: {drift}"
    )

    # Constants: v1..v3 use short keys, v4 uses the dotted official
    # names after the v4 RENAME delta.  The symbol_ids encode the same
    # official dotted name either way, so we lock that down.
    short_legacy_constants = {
        "input.bool": "bool",
        "input.color": "color",
        "input.float": "float",
        "input.integer": "integer",
        "input.source": "source",
        "input.string": "string",
    }
    for version in range(1, 4):
        pack = repo.pack(version)
        constants = pack["sections"]["constants"]
        for dotted, short in short_legacy_constants.items():
            assert short in constants, (
                f"v{version} pack is missing legacy constant {short}"
            )
            assert constants[short]["symbol_id"] == (
                _input_core_constant_symbol_id(dotted)
            ), (
                f"v{version} legacy constant {short} symbol_id drifted: "
                f"{constants[short]['symbol_id']}"
            )
    v4_pack = repo.pack(4)
    v4_constants = v4_pack["sections"]["constants"]
    for dotted in _INPUT_CORE_LEGACY_NAMES:
        assert dotted in v4_constants, (
            f"v4 pack is missing legacy constant {dotted}"
        )
        assert v4_constants[dotted]["symbol_id"] == (
            _input_core_constant_symbol_id(dotted)
        )
