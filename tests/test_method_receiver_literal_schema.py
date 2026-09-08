"""AST2.1 closes dependent Literal tag/value invariants before fresh inference."""

from copy import deepcopy
import json
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.ast import nodes
from pine2ast.ast.decode import ASTDecodeError, decode_program
from pine2ast.ast.schema import validate_ast_schema
from pine2ast.ast.serialize import ast_to_dict
from pine2ast.ast.visitors import walk
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, verify_consumer_bundle

TOKENS = [
    ("2", "int", int),
    ("0", "int", int),
    ("2.0", "float", float),
    (".5", "float", float),
    ("1e-2", "float", float),
    ("-2", "int", int),
    ("-2.0", "float", float),
    ("true", "bool", bool),
    ("false", "bool", bool),
    ('"text"', "string", str),
    ("#aabbcc", "color", str),
    ("#AABBCCDD", "color", str),
    ("na", "na", type(None)),
]


def syntax(token="2", *, feature=True, version=6):
    qualifier = "simple " if feature else ""
    text = f'//@version={version}\nindicator("Literal schema")\nmethod add({qualifier}int self)=>self+1\nx={token}\n'
    parsed = parse_code(text, ParseOptions(run_semantic=False))
    assert parsed.ok, parsed.diagnostics
    return parsed.ast


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("token,tag,expected_type", TOKENS, ids=[r[0] for r in TOKENS])
def test_actual_lexer_parser_literal_types_survive_canonical_json(
    version, token, tag, expected_type
):
    program = syntax(token, version=version)
    expr = program.items[-1].initializer
    if token.startswith("-"):
        assert isinstance(expr, nodes.UnaryExpr)
        expr = expr.operand
        assert expr.value > 0
    assert expr.literal_type == tag
    assert type(expr.value) is expected_type
    payload = ast_to_dict(program)
    restored = decode_program(json.loads(json.dumps(payload)))
    restored_value = restored.items[-1].initializer
    if isinstance(restored_value, nodes.UnaryExpr):
        restored_value = restored_value.operand
    assert type(restored_value.value) is expected_type
    assert ast_to_dict(restored) == payload


def test_positive_cases_cover_every_canonical_literal_tag():
    assert {row[1] for row in TOKENS} == set(
        get_args(get_type_hints(nodes.Literal)["literal_type"])
    )


@pytest.mark.parametrize("tag", ["int", "float", "bool", "string", "color", "na"])
@pytest.mark.parametrize(
    "value",
    [None, True, 2, 2.0, "text", {}, []],
    ids=["null", "bool", "int", "float", "string", "mapping", "list"],
)
def test_all_tag_value_type_combinations_follow_canonical_model(tag, value):
    program = syntax()
    literal = program.items[-1].initializer
    literal.literal_type = tag
    literal.value = deepcopy(value)
    exact_types = {
        "int": int,
        "float": float,
        "bool": bool,
        "string": str,
        "color": str,
        "na": type(None),
    }
    valid = type(value) is exact_types[tag] and tag != "color"
    report = validate_ast_schema(program)
    assert report.ok is valid
    if valid:
        assert ast_to_dict(decode_program(ast_to_dict(program))) == ast_to_dict(program)
    else:
        assert "AST_LITERAL_VALUE_INVALID" in {issue.code for issue in report.issues}
        with pytest.raises(ASTDecodeError):
            decode_program(ast_to_dict(program))


@pytest.mark.parametrize(
    "value", ["red", "#fff", "#gggggg", "#aabbccx", "#aabbccddeeff", float("inf"), float("nan")]
)
def test_invalid_color_shape_and_nonfinite_values_reject(value):
    program = syntax()
    literal = program.items[-1].initializer
    literal.literal_type = "color" if type(value) is str else "float"
    literal.value = value
    assert not validate_ast_schema(program).ok
    with pytest.raises(ASTDecodeError):
        decode_program(ast_to_dict(program))


def test_implicit_once_condition_uses_the_same_bool_literal_invariant():
    program = parse_code(
        '//@version=6\nindicator("Once literal")\nmethod add(simple int self)=>self+1\nonce\n    x=1\n',
        ParseOptions(run_semantic=False),
    ).ast
    condition = next(n for n in walk(program) if isinstance(n, nodes.OnceStructure)).condition
    assert condition.value is True and condition.literal_type == "bool"
    assert validate_ast_schema(program).ok
    decode_program(ast_to_dict(program))


def test_ast20_existing_model_validation_is_unchanged():
    program = syntax(feature=False)
    program.items[-1].initializer.value = {"untrusted": 1}
    assert program.schema_version == "2.0"
    assert validate_ast_schema(program).ok


FORGED = json.loads(
    (Path(__file__).parent / "data/method_receiver_forged_literals.json").read_text()
)


@pytest.mark.parametrize("attack", FORGED["rows"], ids=lambda r: r["id"])
def test_fully_resealed_source_free_forged_literals_reject_before_semantic_replay(
    monkeypatch, attack
):
    from pine2ast import ParsePipeline

    assert attack["observation"] == "ACCEPTED"  # Preserved pre-fix observation, not an expectation.

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid canonical Literal reached semantic inference")

    monkeypatch.setattr(ParsePipeline, "semantic_only", forbidden)
    with pytest.raises(ConsumerBundleError, match="schema is invalid"):
        verify_consumer_bundle(deepcopy(attack["bundle"]))


@pytest.mark.parametrize(
    "attack", ["shared_ast", "mapping_root", "list_root", "unknown_tag", "cycle_value"]
)
def test_malformed_shape_and_identity_are_controlled(attack):
    payload = ast_to_dict(syntax())
    if attack == "shared_ast":
        payload["items"].append(payload["items"][-1])
    elif attack == "mapping_root":
        with pytest.raises(ConsumerBundleError):
            verify_consumer_bundle({})
        return
    elif attack == "list_root":
        with pytest.raises(ConsumerBundleError):
            verify_consumer_bundle([])
        return
    elif attack == "unknown_tag":
        payload["items"][-1]["initializer"]["literal_type"] = "object"
    else:
        payload["items"][-1]["initializer"]["value"] = payload
    with pytest.raises(ASTDecodeError):
        decode_program(payload)
