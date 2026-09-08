"""Independent UTF-8 / JSON escape boundaries for the shared admission budget."""

import pytest

from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError, ASTReplayLimits


@pytest.mark.parametrize(
    "text,canonical_bytes",
    [
        ("", 2),
        ("a", 3),
        ('"', 4),
        ("\\", 4),
        ("\n", 4),
        ("\0", 8),
        ("\x1f", 8),
        ("\x7f", 3),
        ("\u0080", 4),
        ("\u07ff", 4),
        ("\u0800", 5),
        ("\uffff", 5),
        ("\U00010000", 6),
        ("\U0010ffff", 6),
        ('a"\n€', 10),
    ],
)
def test_exact_literal_json_byte_limit_and_one_byte_short(text, canonical_bytes):
    ASTAdmissionBudget(ASTReplayLimits(max_bytes=canonical_bytes)).preflight(text)
    with pytest.raises(ASTDecodeError, match="byte limit"):
        ASTAdmissionBudget(ASTReplayLimits(max_bytes=canonical_bytes - 1)).preflight(text)


def test_every_control_character_retains_short_or_hex_escape_size():
    short = {8, 9, 10, 12, 13}
    for code in range(32):
        exact = 4 if code in short else 8  # Two quotes plus two/six escape bytes.
        ASTAdmissionBudget(ASTReplayLimits(max_bytes=exact)).preflight(chr(code))
        with pytest.raises(ASTDecodeError, match="byte limit"):
            ASTAdmissionBudget(ASTReplayLimits(max_bytes=exact - 1)).preflight(chr(code))


@pytest.mark.parametrize("text", ["\ud800", "\udfff", "x\ud800y"])
def test_surrogates_remain_controlled_errors(text):
    with pytest.raises(ASTDecodeError, match="surrogate"):
        ASTAdmissionBudget().preflight(text)


def test_string_length_is_checked_before_bounded_utf8_encoding():
    with pytest.raises(ASTDecodeError, match="string limit"):
        ASTAdmissionBudget(ASTReplayLimits(max_string_length=1)).preflight("x\ud800")
