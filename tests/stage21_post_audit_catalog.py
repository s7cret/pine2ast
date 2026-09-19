"""Helpers for historical whole-pack controls after the Stage 2.1 ta.rma audit repair."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

_FIXTURE = Path(__file__).with_name("fixtures") / "stage21_post_audit_catalog_delta.json"
_CUMULATIVE_FIXTURE = Path(__file__).with_name("fixtures") / "stage23_cumulative_catalog_delta.json"
_CAT04_FIXTURE = Path(__file__).with_name("fixtures") / "stage2_cat04_catalog_delta.json"


def _digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )


def _delta():
    data = json.loads(_FIXTURE.read_bytes())
    claimed = data.pop("content_hash")
    assert _digest(data) == claimed
    data["content_hash"] = claimed
    return data


def _cumulative_delta():
    data = json.loads(_CUMULATIVE_FIXTURE.read_bytes())
    claimed = data.pop("content_hash")
    assert _digest(data) == claimed
    data["content_hash"] = claimed
    return data


def _cat04_delta():
    data = json.loads(_CAT04_FIXTURE.read_bytes())
    claimed = data.pop("content_hash")
    assert _digest(data) == claimed
    data["content_hash"] = claimed
    return data


def restore_cat04_binary_search_authority(pack):
    """Roll CAT-04 v4 unavailability back so Stage 2.1 pack guards still apply.

    Current packs correctly omit array.binary_search* from v4. Historical
    whole-pack hashes still compare against the pre-CAT-04 identity.
    """
    lock = _cat04_delta()
    restored = deepcopy(pack)
    version = str(int(restored.get("version") or restored.get("pine_version") or 0))
    record = lock["versions"][version]
    assert restored["catalog_hash"] == record["after_catalog_hash"]
    assert restored["content_hash"] == record["after_content_hash"]
    assert restored["historical_projection_hash"] == lock["new_historical_projection_hash"]
    assert restored["source_manifest_hash"] == lock["new_source_manifest_hash"]
    source_id = lock["authority"]["id"]
    restored["provenance_sources"] = [
        source for source in restored.get("provenance_sources", []) if source.get("id") != source_id
    ]
    if "restored_functions" in record:
        functions = restored["sections"]["functions"]
        for name, row in record["restored_functions"].items():
            assert name not in functions
            functions[name] = deepcopy(row)
    restored["historical_projection_hash"] = lock["old_historical_projection_hash"]
    restored["source_manifest_hash"] = lock["old_source_manifest_hash"]
    restored["catalog_hash"] = record["before_catalog_hash"]
    restored["content_hash"] = record["before_content_hash"]
    return restored


def restore_stage21_baseline(pack):
    """Return a copy rolled back to the sealed Stage 2.1 catalog baseline.

    Later reviewed catalog changes remain valid product changes, but historical
    whole-pack guards must explicitly subtract them before comparing with the
    Stage 2.1 baseline. Every rollback is fail-closed: the current row must
    exactly equal the recorded reviewed ``after`` value before it is replaced
    with the corresponding ``before`` value.
    """
    restored = restore_stage2_audit_catalog(restore_cat04_binary_search_authority(pack))
    version = int(restored.get("version") or restored.get("pine_version") or 0)

    # Roll back reviewed post-2.1 catalog changes (Stage 2.2 bool signatures
    # and Stage 2.3 polyline local-scope correction).
    for record in _cumulative_delta().get("changes", []):
        if int(record.get("version", 0)) != version:
            continue
        section = record["section"]
        name = record["name"]
        current = restored["sections"][section][name]
        assert current == record["after"]
        restored["sections"][section][name] = deepcopy(record["before"])

    # Roll back the original Stage 2.1 reviewed ta.rma correction last.
    record = _delta()["versions"].get(str(version))
    if record is not None:
        current = restored["sections"]["functions"]["ta.rma"]
        assert current == record["after"]
        restored["sections"]["functions"]["ta.rma"] = deepcopy(record["before"])
    return restored


def restore_pre_audit_ta_rma(pack):
    """Backward-compatible name for historical guards.

    Since Stage 2.2/2.3 introduced separately reviewed catalog deltas, callers
    that compare against the pre-audit Stage 2.1 baseline must now subtract the
    complete sealed cumulative delta, not only ``ta.rma``.
    """
    return restore_stage21_baseline(pack)


def restore_stage2_audit_catalog(pack):
    """Verify current scoped changes before reconstructing the prior endpoint."""
    path = Path(__file__).with_name("fixtures") / "stage2_audit_catalog_delta.json"
    lock = json.loads(path.read_bytes())
    claimed = lock.pop("content_hash")
    assert _digest(lock) == claimed
    restored = deepcopy(pack)
    record = lock["versions"].get(str(pack.get("pine_version", pack.get("version"))))
    if record is None:
        return restored
    assert _digest(pack) == record["after_hash"]
    for change in record["changes"]:
        section, name = change["section"], change["name"]
        assert restored["sections"][section][name] == change["after"]
        restored["sections"][section][name] = deepcopy(change["before"])
    for key in list(restored):
        if key != "sections":
            del restored[key]
    restored.update(deepcopy(record["before_top"]))
    assert _digest(restored) == record["before_hash"]
    return restored
