"""Helpers for historical whole-pack controls after the Stage 2.1 ta.rma audit repair."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

_FIXTURE = Path(__file__).with_name("fixtures") / "stage21_post_audit_catalog_delta.json"
_CUMULATIVE_FIXTURE = Path(__file__).with_name("fixtures") / "stage23_cumulative_catalog_delta.json"


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


def restore_stage21_baseline(pack):
    """Return a copy rolled back to the sealed Stage 2.1 catalog baseline.

    Later reviewed catalog changes remain valid product changes, but historical
    whole-pack guards must explicitly subtract them before comparing with the
    Stage 2.1 baseline. Every rollback is fail-closed: the current row must
    exactly equal the recorded reviewed ``after`` value before it is replaced
    with the corresponding ``before`` value.
    """
    restored = restore_stage2_audit_catalog(pack)
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
