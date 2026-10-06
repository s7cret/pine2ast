"""Fixed local numeric-input invariants, not runtime-derived expectations."""

import copy

import pytest

from pine2ast.catalog import CatalogRepository
from pine2ast.semantic.completeness import pinned_catalog_static_completeness


class PackRepository(CatalogRepository):
    def __init__(self, pack):
        self.value = pack

    def pack(self, version):
        assert self.value["pine_version"] == version
        return copy.deepcopy(self.value)


MUTATIONS = (
    "symbol",
    "parameter",
    "default_missing",
    "default_null",
    "false_as_zero",
    "true_as_one",
    "default_empty",
    "default_added",
    "qualifier_missing",
    "qualifier_widened",
    "required_missing",
    "required_changed",
    "type",
    "parameter_order",
    "return",
    "return_qualifier",
    "overload_missing",
    "overload_added",
    "overload_parameter",
    "overload_default",
    "overload_return",
    "overload_qualifier",
    "extra_positional",
    "identity",
)


def mutate(pack, name, mutation):
    functions = pack["sections"]["functions"]
    row = functions[name]
    params = {p["name"]: p for p in row["parameters"]}
    if mutation == "symbol":
        del functions[name]
    elif mutation == "parameter":
        row["parameters"].pop(1)
    elif mutation == "default_missing":
        del params["step"]["default"]
    elif mutation == "default_null":
        params["step"]["default"] = None
    elif mutation == "false_as_zero":
        params["confirm"]["default"] = 0
    elif mutation == "true_as_one":
        # v5 has no active: mutate the existing required flag instead.
        if "active" in params:
            params["active"]["default"] = 1
        else:
            params["defval"]["required"] = 1
    elif mutation == "default_empty":
        params["title"]["default"] = "changed"
    elif mutation == "default_added":
        params["minval"]["default"] = 0
    elif mutation == "qualifier_missing":
        del params["defval"]["qualifier_max"]
    elif mutation == "qualifier_widened":
        params["defval"]["qualifier_max"] = "series"
    elif mutation == "required_missing":
        del params["defval"]["required"]
    elif mutation == "required_changed":
        params["defval"]["required"] = False
    elif mutation == "type":
        params["defval"]["type"] = "string"
    elif mutation == "parameter_order":
        row["parameters"][1:3] = reversed(row["parameters"][1:3])
    elif mutation == "return":
        row["returns"] = "bool"
    elif mutation == "return_qualifier":
        row["return_qualifier"] = "series"
    elif mutation == "overload_missing":
        row["overloads"] = []
    elif mutation == "overload_added":
        row["overloads"].append(copy.deepcopy(row["overloads"][0]))
    elif mutation == "overload_parameter":
        row["overloads"][0]["parameters"].pop(2)
    elif mutation == "overload_default":
        row["overloads"][0]["parameters"][1].pop("default")
    elif mutation == "overload_return":
        row["overloads"][0]["returns"] = "bool"
    elif mutation == "overload_qualifier":
        row["overloads"][0]["parameters"][0]["qualifier_max"] = "series"
    elif mutation == "extra_positional":
        row["allow_extra_positional"] = True
    elif mutation == "identity":
        row["symbol_id"] += ":wrong"
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize("version", (5, 6))
@pytest.mark.parametrize("name", ("input.int", "input.float"))
@pytest.mark.parametrize("mutation", MUTATIONS)
def test_required_numeric_input_mutations_fail_closed(version, name, mutation):
    pack = CatalogRepository.default().pack(version)
    mutate(pack, name, mutation)
    report = pinned_catalog_static_completeness(version, repository=PackRepository(pack))
    assert not report.ok, (version, name, mutation)
    assert any(g["code"] == "REQUIRED_INPUT_CONTRACT" for g in report.gaps), report.gaps


@pytest.mark.parametrize("version", range(1, 5))
@pytest.mark.parametrize("name", ("input.int", "input.float"))
def test_required_numeric_inputs_cannot_be_backported(version, name):
    pack = CatalogRepository.default().pack(version)
    pack["sections"]["functions"][name] = CatalogRepository.default().pack(6)["sections"][
        "functions"
    ][name]
    report = pinned_catalog_static_completeness(version, repository=PackRepository(pack))
    assert not report.ok
    assert any(g["code"] == "REQUIRED_INPUT_CONTRACT" for g in report.gaps)


@pytest.mark.parametrize("version", range(1, 7))
def test_pristine_versions_keep_declared_scope(version):
    report = pinned_catalog_static_completeness(version)
    assert report.ok, report.gaps
    assert report.scope == (
        "documented_historical_static_snapshot"
        if version <= 4
        else "pinned_hash_bound_reference_catalog"
    )


@pytest.mark.parametrize("version", (5, 6))
def test_local_success_does_not_claim_external_authority_completeness(version):
    report = pinned_catalog_static_completeness(version)
    assert report.ok
    authority = report.to_dict()["numeric_input_authority"]
    assert authority["guard_basis"] == "LOCAL_CATALOG_INVARIANT"
    assert authority["external_contract_complete"] is False
    assert authority["status"] == "UNVERIFIED"
    assert authority["coverage_ratio_basis"] == "local_checks_not_external_requirements"
    unresolved = {row["dimension"]: row for row in authority["unresolved"]}
    expected = {"optional_text_defaults", "bounded_default_absence", "float_return_type"}
    if version == 5:
        expected |= {"display_membership_and_exact_signature", "step_default", "confirm_default"}
    assert expected <= unresolved.keys()
    assert all(row["status"] == "UNVERIFIED" for row in unresolved.values())
    assert all(row["source"] and row["section"] for row in authority["externally_evidenced"])
    assert not ({row["dimension"] for row in authority["externally_evidenced"]} & expected)


def test_unresolved_v5_signature_is_still_guarded_only_as_local_invariant():
    pack = CatalogRepository.default().pack(5)
    row = pack["sections"]["functions"]["input.float"]
    row["parameters"].append({"name": "display", "type": "display"})
    report = pinned_catalog_static_completeness(5, repository=PackRepository(pack))
    gaps = [g for g in report.gaps if g["code"] == "REQUIRED_INPUT_CONTRACT"]
    assert gaps
    assert all(g["basis"] == "LOCAL_CATALOG_INVARIANT" for g in gaps)
    assert all("local numeric-input invariant" in g["message"] for g in gaps)
    assert report.to_dict()["numeric_input_authority"]["external_contract_complete"] is False
