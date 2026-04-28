from __future__ import annotations

from pine2ast.reference_catalog import load_entries


def test_load_entries_returns_p0_catalog_entries() -> None:
    entries = load_entries()
    ids = {entry.id for entry in entries}

    assert "ta.ema" in ids
    assert "strategy.entry" in ids
    assert "request.security" in ids
    assert "close" in ids
    assert all(entry.priority == "P0" for entry in entries)


def test_stateful_entries_are_marked_with_history_context() -> None:
    by_id = {entry.id: entry for entry in load_entries()}

    assert by_id["ta.ema"].stateful is True
    assert by_id["ta.ema"].requires_history is True
    assert by_id["request.security"].stateful is True
