from __future__ import annotations

import pytest

from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries


@pytest.mark.parametrize("version", [5, 6])
def test_frontend_admission_retains_structured_original_diagnostics(version):
    source = f'//@version={version}\nstrategy("Ошибка")\nvalue = missing_name\n'
    with pytest.raises(ConsumerBundleError) as caught:
        build_consumer_bundle(source, source_name="задача.pine", producer_commit="a" * 40)
    exc = caught.value
    assert str(exc) == "frontend result contains production-blocking diagnostics"
    assert exc.source_name == "задача.pine"
    rows = exc.diagnostics
    assert rows and rows[0]["span"]["start_line"] == 3
    assert rows[0]["code"] == "P2A1101"
    rows[0]["message"] = "mutated"
    assert exc.diagnostics[0]["message"] != "mutated"


@pytest.mark.parametrize("version", [5, 6])
def test_library_syntax_diagnostic_points_to_actual_line_not_one(version):
    store = LibraryStore.create(
        {
            "qa/Broken/1": f'//@version={version}\nlibrary("X")\n// comment\nexport bad(float x)=>\n    x + )\n'
        }
    )
    with pytest.raises(LibraryError) as caught:
        link_libraries(
            f'//@version={version}\nstrategy("t")\nimport qa/Broken/1 as lib\nx=lib.bad(close)\n',
            store,
        )
    assert caught.value.source == "qa/Broken/1"
    assert caught.value.line == 5
    assert isinstance(caught.value.column, int)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("version", [5, 6])
def test_batched_projection_matches_every_scalar_offset_and_does_not_mutate_receipt(
    version, newline
):
    store = LibraryStore.create(
        {
            "qa/S/1": f'//@version={version}\nlibrary("S")\n// Юникод\nexport f(float x)=>x+1\n'.replace(
                "\n", newline
            )
        }
    )
    linked = link_libraries(
        f'//@version={version}\nstrategy("t")\nimport qa/S/1 as l\nx=l.f(close)\n',
        store,
        source_name="root.pine",
    )
    before = linked.receipt()
    offsets = list(range(len(linked.code) + 2))
    values = linked.original_locations(offsets)
    assert values == [linked.original_location(i) for i in offsets]
    assert linked.receipt() == before
    assert {r["source"] for r in values if r} == {"qa/S/1", "root.pine"}
    assert values[-1] is None
    for row in values:
        if row:
            text = before["sources"][row["source"]]["text"]
            assert row["line"] == text.count("\n", 0, row["offset"]) + 1
            assert row["column"] == row["offset"] - text.rfind("\n", 0, row["offset"])


@pytest.mark.parametrize("bad", [-1, True, 1.0, None, "1"])
def test_projection_rejects_invalid_offsets(bad):
    store = LibraryStore.create({"qa/S/1": '//@version=6\nlibrary("S")\nexport f(float x)=>x\n'})
    linked = link_libraries(
        '//@version=6\nstrategy("t")\nimport qa/S/1 as s\nx=s.f(close)\n', store
    )
    with pytest.raises(ValueError, match="nonnegative integer"):
        linked.original_locations([0, bad])
