from pathlib import Path

from pine2ast import parse_code
from pine2ast.diagnostics import codes
from pine2ast.testing.golden import compare_golden, generate_golden


def diag_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics]


def test_member_reassignment_to_declared_udt_variable_is_allowed():
    src = '''//@version=6
indicator("member")
type Pivot
    float y
p = Pivot.new(close)
p.y := high
'''
    got = diag_codes(src)
    assert codes.REASSIGN_UNDECLARED not in got
    assert codes.UNDECLARED_VARIABLE not in got


def test_member_reassignment_to_unknown_root_errors():
    src = '''//@version=6
indicator("member")
missing.y := high
'''
    assert codes.REASSIGN_UNDECLARED in diag_codes(src)


def test_unknown_function_call_is_semantic_error():
    src = '''//@version=6
indicator("unknown")
x = definitelyMissing(close)
'''
    assert codes.UNDECLARED_VARIABLE in diag_codes(src)


def test_builtin_qualifier_validation_for_const_only_input_title():
    src = '''//@version=6
indicator("qual")
t = close > open ? "A" : "B"
len = input.int(14, title = t)
'''
    got = diag_codes(src)
    assert codes.ARGUMENT_QUALIFIER in got


def test_builtin_qualifier_validation_accepts_const_title():
    src = '''//@version=6
indicator("qual")
len = input.int(14, title = "Length")
'''
    assert codes.ARGUMENT_QUALIFIER not in diag_codes(src)


def test_golden_generator_and_compare(tmp_path: Path):
    src = tmp_path / "basic.pine"
    src.write_text('''//@version=6
indicator("golden")
plot(close)
''', encoding="utf-8")
    info = generate_golden(src, ignore_spans=True)
    assert info["ok"] is True
    ok, message = compare_golden(src, ignore_spans=True)
    assert ok, message


def test_literal_initialized_variable_is_mutable_unless_explicit_const():
    src = '''//@version=6
indicator("mutable")
x = 0
x += 1
'''
    assert codes.CONST_REASSIGNMENT not in diag_codes(src)


def test_explicit_const_reassignment_still_errors():
    src = '''//@version=6
indicator("const")
const int x = 0
x += 1
'''
    assert codes.CONST_REASSIGNMENT in diag_codes(src)


def test_real_world_seed_corpus_validates_cleanly():
    from pine2ast.corpus import validate_corpus
    result = validate_corpus(Path(__file__).absolute().parents[1] / "fixtures" / "real_world" / "01_ma_indicator.pine")
    assert result["file_count"] == 1
    assert result["ok_count"] == result["file_count"]
    assert result["error_count"] == 0
