from pine2ast import parse_code


def test_invalid_builtin_call_has_no_selected_overload():
    result = parse_code("//@version=6\nindicator('x')\nx = ta.sma(close, 'bad')\n")
    bundle = result.semantic_model.semantic_facts
    call = next(item for item in bundle.calls if item.callee == "ta.sma")
    assert call.resolution_status == "INVALID"
    assert call.overload_id is None
    assert any(item.code in {"P2A1406", "P2A2008"} for item in result.diagnostics)
