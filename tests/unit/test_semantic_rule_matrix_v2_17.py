from __future__ import annotations

import pytest

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes


def _error_codes(source: str, *, strict_builtin_namespaces: bool = False) -> set[str]:
    result = parse_code(
        source,
        ParseOptions(run_semantic=True, strict_builtin_namespaces=strict_builtin_namespaces),
    )
    return {diag.code for diag in result.diagnostics if diag.severity.value in {"ERROR", "FATAL"}}


@pytest.mark.parametrize(
    ("name", "source", "expected", "strict"),
    [
        (
            "equal_redeclares_same_scope",
            '//@version=6\nindicator("T")\nx = 1\nx = 2\n',
            codes.REDECLARATION,
            False,
        ),
        (
            "coloneq_requires_existing_symbol",
            '//@version=6\nindicator("T")\nx := 1\n',
            codes.REASSIGN_UNDECLARED,
            False,
        ),
        (
            "const_reassignment",
            '//@version=6\nindicator("T")\nconst int x = 1\nx := 2\n',
            codes.CONST_REASSIGNMENT,
            False,
        ),
        (
            "bool_v6_condition",
            '//@version=6\nindicator("T")\nif close\n    x = 1\n',
            codes.NON_BOOL_CONDITION,
            False,
        ),
        (
            "bool_na_literal_context",
            '//@version=6\nindicator("T")\nif na\n    x = 1\n',
            codes.NA_IN_BOOL_CONTEXT,
            False,
        ),
        (
            "bool_variable_cannot_be_na",
            '//@version=6\nindicator("T")\nbool b = na\n',
            codes.BOOL_CANNOT_BE_NA,
            False,
        ),
        (
            "history_on_literal",
            '//@version=6\nindicator("T")\nx = 1[2]\n',
            codes.HISTORY_ON_LITERAL,
            False,
        ),
        (
            "repeated_history_reference",
            '//@version=6\nindicator("T")\nx = close[1][2]\n',
            codes.REPEATED_HISTORY,
            False,
        ),
        (
            "history_offset_not_integer",
            '//@version=6\nindicator("T")\nx = close[1.5]\n',
            codes.HISTORY_OFFSET_NOT_INTEGER,
            False,
        ),
        (
            "break_outside_loop",
            '//@version=6\nindicator("T")\nbreak\n',
            codes.BREAK_CONTINUE_OUTSIDE_LOOP,
            False,
        ),
        (
            "continue_outside_loop",
            '//@version=6\nindicator("T")\ncontinue\n',
            codes.BREAK_CONTINUE_OUTSIDE_LOOP,
            False,
        ),
        (
            "nested_function",
            '//@version=6\nindicator("T")\nif true\n    f() => 1\n',
            codes.NESTED_FUNCTION,
            False,
        ),
        (
            "method_receiver_unknown_type",
            '//@version=6\nindicator("T")\nmethod bad(Unknown this) => 1\n',
            codes.METHOD_RECEIVER_TYPE_NOT_FOUND,
            False,
        ),
        (
            "import_alias_conflict",
            '//@version=6\nindicator("T")\nimport user/lib/1 as math\nx = math.foo()\n',
            codes.REDECLARATION,
            False,
        ),
        (
            "unknown_builtin_namespace_member",
            '//@version=6\nindicator("T")\nx = ta.definitely_missing(close)\n',
            codes.UNKNOWN_BUILTIN_MEMBER,
            True,
        ),
        (
            "unknown_namespace_object",
            '//@version=6\nindicator("T")\nx = missingns.value\n',
            codes.UNDECLARED_VARIABLE,
            False,
        ),
    ],
)
def test_v217_semantic_rule_matrix(name: str, source: str, expected: str, strict: bool) -> None:
    assert expected in _error_codes(source, strict_builtin_namespaces=strict), name
