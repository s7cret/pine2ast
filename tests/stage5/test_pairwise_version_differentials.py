from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository


def _codes(source: str) -> set[str]:
    return {item.code for item in parse_code(source).diagnostics if item.is_error}


def test_v1_to_v2_additive_syntax_delta():
    body = "study('x')\nif true\n    x = 1\n"
    assert _codes(body)
    assert not _codes("//@version=2\n" + body)


def test_v2_to_v3_binding_and_bool_arithmetic_delta():
    body = "study('x')\na = b + true\nb = 1\n"
    assert not _codes("//@version=2\n" + body)
    assert _codes("//@version=3\n" + body)


def test_v3_to_v4_typed_na_and_ternary_delta():
    typed = "study('x')\nfloat x = na\n"
    assert _codes("//@version=3\n" + typed)
    assert not _codes("//@version=4\n" + typed)

    expression = "study('x')\nx = true ? 1 : 2\n"
    v3 = parse_code("//@version=3\n" + expression)
    v4 = parse_code("//@version=4\n" + expression)
    r3 = next(
        item for item in v3.semantic_model.semantic_facts.facts if item.kind == "ConditionalExpr"
    )
    r4 = next(
        item for item in v4.semantic_model.semantic_facts.facts if item.kind == "ConditionalExpr"
    )
    assert "operator.ternary.eager.v3" in r3.semantic_rule_ids
    assert "operator.ternary.lazy.v4" in r4.semantic_rule_ids


def test_historical_renames_keep_stable_symbol_identity():
    repo = CatalogRepository.default()
    v3 = repo.view(3)
    v4 = repo.view(4)
    v5 = repo.view(5)
    assert v4["functions"]["study"]["symbol_id"] == v5["functions"]["indicator"]["symbol_id"]
    assert v4["functions"]["sma"]["symbol_id"] == v5["functions"]["ta.sma"]["symbol_id"]
    assert (
        v4["functions"]["security"]["symbol_id"] == v5["functions"]["request.security"]["symbol_id"]
    )
    assert (
        v3["variables"]["tickerid"]["symbol_id"] == v5["variables"]["syminfo.tickerid"]["symbol_id"]
    )
