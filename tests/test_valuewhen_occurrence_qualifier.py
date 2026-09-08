"""Version-scoped occurrence admission, with literal whole-pack scope guards."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload


FIXTURE = Path(__file__).with_name("fixtures") / "valuewhen_occurrence_metadata.json"
EXPECTED = json.loads(FIXTURE.read_bytes())


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def script(version, body):
    return f'//@version={version}\nindicator("occurrence qualifier")\n{body}\n'


@pytest.mark.parametrize("version", range(1, 7))
def test_only_modern_occurrence_changes_in_complete_pack(version):
    path = Path(__file__).parents[1] / f"pine2ast/catalog_data/packs/pine_v{version}.pack.json"
    pack = json.loads(path.read_bytes())
    before = EXPECTED["producer_packs"][str(version)]
    if version <= 4:
        assert digest(pack["sections"]) == before["old_sections_hash"]
        assert digest(pack["rules"]) == before["old_rules_hash"]
    normalized = deepcopy(pack)
    for key in ("source_manifest_hash", "catalog_hash", "content_hash"):
        normalized.pop(key)
    assert digest(normalized) == before["expected_except_provenance_hash"]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("binding", ["positional", "named"])
@pytest.mark.parametrize("origin", ["const", "input", "simple"])
def test_weaker_qualifiers_keep_exact_canonical_argument_binding(version, binding, origin):
    prefix, value = {
        "const": ("", "0"),
        "input": ("occ=input.int(1)\n", "occ"),
        "simple": ("simple int occ=1\n", "occ"),
    }[origin]
    args = f"close > open, close, {value}" if binding == "positional" else f"occurrence={value}, source=close, condition=close > open"
    source = script(version, prefix + f"result=ta.valuewhen({args})\nplot(result)")
    parsed = parse_code(source)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(source)["content_hash"]
    call = next(c for c in semantic_facts_payload(parsed)["calls"] if c["callee"] == "ta.valuewhen")
    assert call["overload_id"] == "pine:function:ta.valuewhen#canonical"
    assert call["call_form"] == "NAMESPACE_FUNCTION" and call["return_type"] == "float"
    argument = next(a for a in call["arguments"] if a["parameter_name"] == "occurrence")
    assert argument["actual_qualifier"] == origin
    assert argument["max_qualifier"] == "simple"
    assert argument["actual_type"] == argument["expected_type"] == "int"
    assert argument["parameter_index"] == 2 and argument["binding"] == binding


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("binding", ["positional", "named"])
@pytest.mark.parametrize("origin", ["expression", "declaration"])
def test_series_occurrence_is_rejected_before_emission(version, binding, origin):
    prefix, value = ("", "bar_index % 2") if origin == "expression" else ("int occ=bar_index % 2\n", "occ")
    args = f"close > open, close, {value}" if binding == "positional" else f"occurrence={value}, source=close, condition=close > open"
    source = script(version, prefix + f"result=ta.valuewhen({args})\nplot(result)")
    result = parse_code(source)
    assert not result.ok
    assert any(d.code == "P2A1405" and "Argument occurrence " in d.message for d in result.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("value", ["true", "1.5", '"1"'])
def test_invalid_occurrence_types_remain_rejected(version, value):
    source = script(version, f"plot(ta.valuewhen(close > open, close, {value}))")
    assert not parse_code(source).ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_retained_historical_metadata_is_not_back_projected(version):
    row = CatalogRepository.default().readonly_view(version)["functions"]["valuewhen"]
    assert next(p for p in row["parameters"] if p["name"] == "occurrence")["qualifier_max"] == "series"


def test_literal_metadata_precedes_implementation():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == "ffb6e266a36ee0789acab13d872ea000b96f1c715cbfc2b736f698463319dbef"
