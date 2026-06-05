from pine2ast.api import parse_code, runtime_contract_v1_4_options
from pine2ast.ast.serialize import ast_to_dict


def test_runtime_contract_v1_4_parse_serializes_producer_metadata():
    result = parse_code(
        b'//@version=6\nindicator("x")\na = close\n', runtime_contract_v1_4_options()
    )
    assert result.ast is not None
    payload = ast_to_dict(result.ast)
    metadata = payload["producer_metadata"]
    assert metadata["contract"] == "pain.ast_contract.v1"
    assert metadata["producer"]["name"] == "pine2ast"
    assert metadata["schema_version"] == payload["schema_version"]
    assert metadata["pine_language_version"] == 6
    assert metadata["runtime_contract"] == "runtime_contract_v1_4"
    assert metadata["parser_gate"] == "pass"
    assert metadata["semantic_gate"] == "pass"


def test_runtime_contract_metadata_records_semantic_failure_gate():
    result = parse_code(
        b'//@version=6\nindicator("x")\nif 1\n    a = close\n',
        runtime_contract_v1_4_options(),
    )
    assert result.ast is not None
    assert any(d.severity.name in {"ERROR", "FATAL"} for d in result.diagnostics)

    metadata = ast_to_dict(result.ast)["producer_metadata"]
    assert metadata["parser_gate"] == "fail"
    assert metadata["semantic_gate"] == "fail"


def test_runtime_contract_metadata_distinguishes_semantic_not_run():
    result = parse_code(
        b'//@version=6\nindicator("x")\na = close\n',
        runtime_contract_v1_4_options(run_semantic=False),
    )
    assert result.ast is not None

    metadata = ast_to_dict(result.ast)["producer_metadata"]
    assert metadata["parser_gate"] == "pass"
    assert metadata["semantic_gate"] == "not_run"
