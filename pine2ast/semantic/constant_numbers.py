"""Bounded numeric kernels for the producer's existing constant-value facts."""

import math
import operator
from decimal import Decimal
from typing import cast

_OMITTED = object()
_COMPARISONS = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def comparison_constant(left: object, right: object, operation: str) -> bool | None:
    """v6 finite numeric comparison, with documented nine-digit float operands.

    Exact decimal midpoint tie behavior is not independently established for
    comparisons. Such values remain unknown rather than borrowing math.round's
    tie policy. All other rounding uses that existing decimal kernel.
    """
    if (
        operation not in _COMPARISONS
        or type(left) not in (int, float)
        or type(right) not in (int, float)
    ):
        return None
    if any(isinstance(value, int) and value.bit_length() > 4096 for value in (left, right)):
        return None
    if type(left) is type(right) is int:
        return bool(_COMPARISONS[operation](left, right))
    try:
        operands = (float(cast(int | float, left)), float(cast(int | float, right)))
    except (OverflowError, ValueError):
        return None
    rounded = []
    for value in operands:
        if not math.isfinite(value):
            return None
        numerator, denominator = Decimal(str(value)).as_integer_ratio()
        if 2 * ((numerator * 1_000_000_000) % denominator) == denominator:
            return None
        result = round_constant(value, 9)
        if result is None:
            return None
        rounded.append(result)
    return bool(_COMPARISONS[operation](*rounded))


def round_constant(number: object, precision: object = _OMITTED) -> int | float | None:
    """Nearest decimal value; half ties choose the larger value.

    ``None`` is unknown/NA evidence, never a Python conversion. Precision omission
    selects int; explicit precision selects float. Irrelevant extreme precision
    is decided before allocating powers. This is a compile-time resource bound,
    not a Pine numeric-domain limit: oversized integers are simply not folded.
    """
    if type(number) not in (int, float):
        return None
    if isinstance(number, float) and not math.isfinite(number):
        return None
    if isinstance(number, int) and number.bit_length() > 4096:
        return None
    omitted = precision is _OMITTED
    if not omitted and type(precision) is not int:
        return None
    decimal = Decimal(str(number))
    places = 0 if omitted else cast(int, precision)
    exponent = decimal.as_tuple().exponent
    assert isinstance(exponent, int)
    if not decimal or places >= -exponent:
        return int(decimal) if omitted else _finite_float(decimal)
    if places < -decimal.adjusted() - 1:
        return 0 if omitted else 0.0
    numerator, denominator = decimal.as_integer_ratio()
    scale = 10 ** abs(places)
    if places >= 0:
        numerator *= scale
    else:
        denominator *= scale
    quotient, remainder = divmod(numerator, denominator)
    rounded = quotient + int(2 * remainder >= denominator)
    if omitted:
        return rounded
    try:
        result = rounded / scale if places >= 0 else float(rounded * scale)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _finite_float(number: Decimal) -> float | None:
    result = float(number)
    return result if math.isfinite(result) else None
